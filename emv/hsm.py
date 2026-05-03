"""
S5 — HSM simulé : chiffrement des données sensibles en RAM.
Simule un Hardware Security Module (HSM) qui protège les clés cryptographiques
en les chiffrant avec une clé KEK (Key Encryption Key) Fernet éphémère,
générée au démarrage et jamais persistée sur disque.

Toutes les clés maîtresses (MDK, CVK, etc.) sont stockées chiffrées en RAM.
Les opérations cryptographiques déchiffrent la clé à la demande, utilisent la
valeur en clair uniquement le temps de l'opération, puis effacent la variable.
"""

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
HSM_KEY_TYPES = {
    "MDK_AC":     "Master Derivation Key — Application Cryptogram",
    "MDK_ENC":    "Master Derivation Key — Encryption",
    "MDK_MAC":    "Master Derivation Key — MAC",
    "CVK1":       "Card Verification Key 1",
    "CVK2":       "Card Verification Key 2",
    "SECRET_KEY": "Application Secret Key",
    "CUSTOM":     "Custom key",
}


@dataclass
class KeyMetadata:
    key_id: str
    key_type: str
    description: str
    loaded_at: float = field(default_factory=time.time)
    use_count: int = 0
    is_active: bool = True


class HsmKeyStore:
    """
    Stockage chiffré des clés cryptographiques en RAM.
    Les clés sont chiffrées via une KEK Fernet éphémère.
    La KEK est générée au démarrage et jamais persistée.
    """

    def __init__(self):
        self._kek: bytes = Fernet.generate_key()
        self._fernet = Fernet(self._kek)
        self._wrapped_keys: Dict[str, bytes] = {}
        self._metadata: Dict[str, KeyMetadata] = {}
        self._lock = threading.RLock()
        self._access_log: List[dict] = []
        self._max_log = 200
        logger.info("[HSM] KeyStore initialisé — KEK éphémère générée (%d bits)", 256)

    def load_key(self, key_id: str, raw_bytes: bytes,
                 key_type: str = "CUSTOM", description: str = "") -> None:
        """Charge une clé en la chiffrant avec la KEK."""
        if not raw_bytes:
            raise ValueError("raw_bytes ne peut pas être vide")
        with self._lock:
            wrapped = self._fernet.encrypt(raw_bytes)
            self._wrapped_keys[key_id] = wrapped
            self._metadata[key_id] = KeyMetadata(
                key_id=key_id, key_type=key_type,
                description=description or HSM_KEY_TYPES.get(key_type, "Clé personnalisée"),
            )
            # Effacement de la variable locale (best-effort en Python)
            del raw_bytes
            self._log_access(key_id, "LOAD")
            logger.debug("[HSM] Clé '%s' chargée et chiffrée (%s)", key_id, key_type)

    def get_key(self, key_id: str) -> bytes:
        """Déchiffre et retourne la clé demandée."""
        with self._lock:
            wrapped = self._wrapped_keys.get(key_id)
            if wrapped is None:
                raise KeyError("Clé '{}' introuvable dans le HSM".format(key_id))
            meta = self._metadata[key_id]
            if not meta.is_active:
                raise PermissionError("Clé '{}' désactivée".format(key_id))
            try:
                raw = self._fernet.decrypt(wrapped)
            except InvalidToken:
                raise RuntimeError("Erreur de déchiffrement HSM pour clé '{}'".format(key_id))
            meta.use_count += 1
            self._log_access(key_id, "USE")
            return raw

    def revoke_key(self, key_id: str) -> bool:
        """Désactive une clé (sans la supprimer)."""
        with self._lock:
            if key_id not in self._metadata:
                return False
            self._metadata[key_id].is_active = False
            self._log_access(key_id, "REVOKE")
            logger.warning("[HSM] Clé '%s' révoquée", key_id)
            return True

    def delete_key(self, key_id: str) -> bool:
        """Supprime une clé du stockage (irrécupérable)."""
        with self._lock:
            if key_id not in self._wrapped_keys:
                return False
            # Écrasement avant suppression
            self._wrapped_keys[key_id] = b'\x00' * len(self._wrapped_keys[key_id])
            del self._wrapped_keys[key_id]
            del self._metadata[key_id]
            self._log_access(key_id, "DELETE")
            return True

    def has_key(self, key_id: str) -> bool:
        with self._lock:
            return key_id in self._wrapped_keys

    def list_keys(self) -> List[dict]:
        """Retourne les métadonnées des clés (sans valeurs)."""
        with self._lock:
            return [
                {
                    "key_id": meta.key_id,
                    "key_type": meta.key_type,
                    "description": meta.description,
                    "loaded_at": meta.loaded_at,
                    "use_count": meta.use_count,
                    "is_active": meta.is_active,
                }
                for meta in self._metadata.values()
            ]

    def get_status(self) -> dict:
        with self._lock:
            return {
                "keys_loaded": len(self._wrapped_keys),
                "keys_active": sum(1 for m in self._metadata.values() if m.is_active),
                "keys_revoked": sum(1 for m in self._metadata.values() if not m.is_active),
                "total_operations": sum(m.use_count for m in self._metadata.values()),
                "kek_algorithm": "Fernet (AES-128-CBC + HMAC-SHA256)",
                "kek_ephemeral": True,
                "kek_persisted": False,
            }

    def _log_access(self, key_id: str, operation: str):
        entry = {
            "key_id": key_id,
            "operation": operation,
            "timestamp": time.time(),
        }
        self._access_log.append(entry)
        if len(self._access_log) > self._max_log:
            self._access_log = self._access_log[-self._max_log:]

    def get_access_log(self) -> List[dict]:
        with self._lock:
            return list(self._access_log)

    def rotate_kek(self) -> None:
        """
        Rotation de la KEK : re-chiffre toutes les clés avec une nouvelle KEK.
        Opération atomique (verrou maintenu pendant toute l'opération).
        """
        with self._lock:
            new_kek = Fernet.generate_key()
            new_fernet = Fernet(new_kek)
            new_wrapped: Dict[str, bytes] = {}
            for key_id, wrapped in self._wrapped_keys.items():
                raw = self._fernet.decrypt(wrapped)
                new_wrapped[key_id] = new_fernet.encrypt(raw)
                del raw
            self._kek = new_kek
            self._fernet = new_fernet
            self._wrapped_keys = new_wrapped
            logger.info("[HSM] KEK pivotée — %d clés re-chiffrées", len(new_wrapped))
            self._log_access("*", "KEK_ROTATE")


class SimulatedHSM:
    """
    HSM simulé — façade principale.
    Charge automatiquement les clés depuis la Config et les protège en RAM.
    Compatible avec les appels emv/crypto.py via get_mdk_ac(), get_cvk(), etc.
    """

    _instance: Optional["SimulatedHSM"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._store = HsmKeyStore()
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "SimulatedHSM":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            cls._instance = None

    def initialize_from_config(self, config) -> int:
        """
        Charge les clés depuis l'objet Config dans le HSM.
        Retourne le nombre de clés chargées.
        """
        loaded = 0
        key_map = {
            "MDK_AC":  ("MDK_AC",  getattr(config, "MDK_AC",  None)),
            "MDK_ENC": ("MDK_ENC", getattr(config, "MDK_ENC", None)),
            "MDK_MAC": ("MDK_MAC", getattr(config, "MDK_MAC", None)),
            "CVK1":    ("CVK1",    getattr(config, "CVK1",    None)),
            "CVK2":    ("CVK2",    getattr(config, "CVK2",    None)),
        }
        secret = getattr(config, "SECRET_KEY", None)
        if secret:
            sk_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
            self._store.load_key("SECRET_KEY", sk_bytes, "SECRET_KEY")
            loaded += 1

        for key_id, (key_type, raw) in key_map.items():
            if raw:
                self._store.load_key(key_id, raw, key_type)
                loaded += 1

        self._initialized = True
        logger.info("[HSM] Initialisé depuis Config — %d clés chargées et chiffrées", loaded)
        return loaded

    # ── Accesseurs métier ─────────────────────────────────────────────────────

    def get_mdk_ac(self) -> bytes:
        return self._store.get_key("MDK_AC")

    def get_mdk_enc(self) -> bytes:
        return self._store.get_key("MDK_ENC")

    def get_mdk_mac(self) -> bytes:
        return self._store.get_key("MDK_MAC")

    def get_cvk1(self) -> bytes:
        return self._store.get_key("CVK1")

    def get_cvk2(self) -> bytes:
        return self._store.get_key("CVK2")

    def get_secret_key(self) -> str:
        return self._store.get_key("SECRET_KEY").decode("utf-8")

    def get_key(self, key_id: str) -> bytes:
        return self._store.get_key(key_id)

    def load_key(self, key_id: str, raw_bytes: bytes,
                 key_type: str = "CUSTOM", description: str = ""):
        self._store.load_key(key_id, raw_bytes, key_type, description)

    def rotate_kek(self):
        self._store.rotate_kek()

    def revoke_key(self, key_id: str) -> bool:
        return self._store.revoke_key(key_id)

    def is_initialized(self) -> bool:
        return self._initialized

    # ── Statut ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        status = self._store.get_status()
        status["initialized"] = self._initialized
        status["hsm_type"] = "Simulated HSM (Fernet KEK)"
        status["compliance"] = ["FIPS-140-2 compatible (simulation)", "PCI-DSS key protection"]
        return status

    def get_key_inventory(self) -> List[dict]:
        return self._store.list_keys()

    def get_access_log(self) -> List[dict]:
        return self._store.get_access_log()


def get_hsm() -> SimulatedHSM:
    return SimulatedHSM.get_instance()
