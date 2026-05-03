"""
A3 — Configuration YAML/TOML rechargeable à chaud.
Charge un fichier config.yaml (ou config.toml) en complément des variables
d'environnement. Supporte le rechargement à chaud par polling ou à la demande
via POST /api/v1/config/reload.
Priorité : variables d'environnement > fichier de config > valeurs par défaut.
"""

import logging
import os
import threading
import time
import tomllib
from typing import Any, Dict, Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_FILES = ["config.yaml", "config.yml", "config.toml"]
_RELOAD_INTERVAL_SECS = int(os.getenv("CONFIG_RELOAD_INTERVAL", "10"))


def _load_yaml(path: str) -> dict:
    if not _YAML_AVAILABLE:
        raise ImportError("PyYAML non installé — pip install pyyaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_toml(path: str) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _load_file(path: str) -> dict:
    """Charge un fichier YAML ou TOML selon son extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        return _load_yaml(path)
    if ext == ".toml":
        return _load_toml(path)
    # Essai YAML d'abord, puis TOML
    try:
        return _load_yaml(path)
    except Exception:
        return _load_toml(path)


def _deep_merge(base: dict, override: dict) -> dict:
    """Fusionne override dans base récursivement."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _apply_env_overrides(cfg: dict) -> dict:
    """
    Applique les variables d'environnement sur la config chargée.
    Les clés ENV_VAR correspondent aux chemins `section.key` en majuscules
    séparés par `__`. Ex: `SERVER__PORT` → cfg["server"]["port"].
    """
    for key, val in os.environ.items():
        if "__" in key:
            parts = key.lower().split("__")
            d = cfg
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = val
    return cfg


class ConfigManager:
    """
    Gestionnaire de configuration rechargeable — singleton thread-safe.
    Charge config.yaml / config.toml + variables d'environnement.
    Lance optionnellement un thread de polling pour le rechargement automatique.
    """

    _instance: Optional["ConfigManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, config_path: Optional[str] = None,
                 watch: bool = True,
                 reload_interval: int = _RELOAD_INTERVAL_SECS):
        self._config_path: Optional[str] = config_path or self._find_config_file()
        self._config: dict = {}
        self._last_mtime: float = 0.0
        self._reload_count: int = 0
        self._reload_errors: int = 0
        self._watch: bool = watch
        self._reload_interval: int = reload_interval
        self._rlock = threading.RLock()
        self._watcher_thread: Optional[threading.Thread] = None

        self._load()

        if watch and self._config_path:
            self._start_watcher()

    @classmethod
    def get_instance(cls, config_path: Optional[str] = None,
                     watch: bool = True) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config_path=config_path, watch=watch)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Réinitialise le singleton (utile pour les tests)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._watch = False
            cls._instance = None

    # ── Chargement ────────────────────────────────────────────────────────────

    def _find_config_file(self) -> Optional[str]:
        for fname in _DEFAULT_CONFIG_FILES:
            if os.path.isfile(fname):
                return fname
        return None

    def _load(self):
        """Charge (ou recharge) la configuration depuis le fichier."""
        with self._rlock:
            raw: dict = {}
            if self._config_path and os.path.isfile(self._config_path):
                try:
                    raw = _load_file(self._config_path)
                    self._last_mtime = os.path.getmtime(self._config_path)
                    logger.info("[CONFIG] Fichier chargé : %s", self._config_path)
                except Exception as exc:
                    self._reload_errors += 1
                    logger.error("[CONFIG] Erreur de chargement '%s' : %s",
                                 self._config_path, exc)
                    return
            else:
                logger.debug("[CONFIG] Aucun fichier de config trouvé — defaults only")

            merged = _apply_env_overrides(raw)
            self._config = merged
            self._reload_count += 1

    def reload(self) -> dict:
        """Recharge la configuration à la demande. Retourne un rapport."""
        before_count = self._reload_count
        self._load()
        return {
            "reloaded": self._reload_count > before_count,
            "config_path": self._config_path,
            "reload_count": self._reload_count,
            "reload_errors": self._reload_errors,
        }

    def _check_and_reload(self):
        """Vérifie si le fichier a changé et recharge si nécessaire."""
        if not self._config_path or not os.path.isfile(self._config_path):
            return
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime > self._last_mtime:
                logger.info("[CONFIG] Changement détecté — rechargement automatique")
                self._load()
        except OSError:
            pass

    def _start_watcher(self):
        """Démarre le thread de surveillance du fichier de config."""
        def _watcher():
            while self._watch:
                time.sleep(self._reload_interval)
                if not self._watch:
                    break
                self._check_and_reload()

        self._watcher_thread = threading.Thread(
            target=_watcher, daemon=True, name="config-watcher")
        self._watcher_thread.start()
        logger.info("[CONFIG] Watcher démarré (intervalle: %ds)", self._reload_interval)

    # ── Accès aux valeurs ─────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Accès par clé pointée (ex: 'server.port') ou clé plate.
        Retourne default si la clé n'existe pas.
        """
        with self._rlock:
            parts = key.split(".")
            d: Any = self._config
            for part in parts:
                if not isinstance(d, dict):
                    return default
                d = d.get(part)
                if d is None:
                    return default
            return d

    def get_section(self, section: str) -> dict:
        """Retourne une section entière de la config (dict)."""
        with self._rlock:
            return dict(self._config.get(section, {}))

    def get_all(self) -> dict:
        """Retourne une copie de la configuration complète."""
        with self._rlock:
            return dict(self._config)

    def set(self, key: str, value: Any):
        """Définit une valeur en mémoire (non persistée sur disque)."""
        with self._rlock:
            parts = key.split(".")
            d = self._config
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = value

    # ── Statut ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        with self._rlock:
            return {
                "config_path": self._config_path,
                "config_path_exists": bool(
                    self._config_path and os.path.isfile(self._config_path)),
                "last_mtime": self._last_mtime,
                "reload_count": self._reload_count,
                "reload_errors": self._reload_errors,
                "watch_enabled": self._watch,
                "reload_interval_secs": self._reload_interval,
                "yaml_available": _YAML_AVAILABLE,
                "toml_available": True,
                "keys_loaded": list(self._config.keys()),
            }


# ── Accès rapide au singleton ─────────────────────────────────────────────────

def get_config_manager() -> ConfigManager:
    return ConfigManager.get_instance()


def get_config(key: str, default: Any = None) -> Any:
    """Raccourci global : get_config('server.port', 5000)."""
    return get_config_manager().get(key, default)
