"""
A2 — Mode dégradé simulé / Chaos Engineering.
Injection de pannes contrôlées sur les endpoints pour tester la résilience
du serveur EMV : timeouts, erreurs réseau, erreurs internes, pannes partielles.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    TIMEOUT         = "TIMEOUT"
    NETWORK_ERROR   = "NETWORK_ERROR"
    INTERNAL_ERROR  = "INTERNAL_ERROR"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    SLOW_RESPONSE   = "SLOW_RESPONSE"


class ChaosException(Exception):
    """Levée par inject_chaos() lorsqu'une panne est simulée."""
    def __init__(self, failure_type: FailureType, message: str, endpoint: str):
        super().__init__(message)
        self.failure_type = failure_type
        self.endpoint = endpoint


@dataclass
class EndpointChaosConfig:
    """Configuration de chaos pour un endpoint ou groupe d'endpoints."""
    failure_rate: float = 0.0          # 0.0 – 1.0 (probabilité de panne)
    failure_types: List[FailureType] = field(default_factory=lambda: [FailureType.INTERNAL_ERROR])
    latency_ms: int = 0                # Délai ajouté en ms (0 = désactivé)
    latency_jitter_ms: int = 0        # Variation aléatoire du délai
    enabled: bool = True


@dataclass
class ChaosStats:
    """Compteurs d'injections de pannes."""
    total_requests: int = 0
    injected_failures: int = 0
    injected_latencies: int = 0
    failures_by_type: Dict[str, int] = field(default_factory=dict)
    failures_by_endpoint: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "injected_failures": self.injected_failures,
            "injected_latencies": self.injected_latencies,
            "failure_rate_observed": round(
                self.injected_failures / self.total_requests, 4)
                if self.total_requests > 0 else 0.0,
            "failures_by_type": dict(self.failures_by_type),
            "failures_by_endpoint": dict(self.failures_by_endpoint),
        }


class DegradedModeManager:
    """
    Gestionnaire du mode dégradé — singleton thread-safe.
    Permet d'activer/désactiver et de configurer l'injection de pannes
    par endpoint ou globalement.
    """

    _instance: Optional["DegradedModeManager"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._global_enabled: bool = False
        self._global_failure_rate: float = 0.1
        self._global_failure_types: List[FailureType] = [FailureType.INTERNAL_ERROR]
        self._global_latency_ms: int = 0
        self._endpoint_configs: Dict[str, EndpointChaosConfig] = {}
        self._stats: ChaosStats = ChaosStats()
        self._rlock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "DegradedModeManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Configuration ────────────────────────────────────────────────────────

    def enable(self, failure_rate: float = 0.1,
               failure_types: Optional[List[str]] = None,
               latency_ms: int = 0):
        """Active le mode dégradé global."""
        with self._rlock:
            self._global_enabled = True
            self._global_failure_rate = max(0.0, min(1.0, failure_rate))
            if failure_types:
                self._global_failure_types = [FailureType(ft) for ft in failure_types]
            self._global_latency_ms = max(0, latency_ms)
            logger.warning(
                "[CHAOS] Mode dégradé ACTIVÉ — rate=%.1f%% latency=%dms types=%s",
                failure_rate * 100, latency_ms,
                [ft.value for ft in self._global_failure_types])

    def disable(self):
        """Désactive le mode dégradé global."""
        with self._rlock:
            self._global_enabled = False
            logger.info("[CHAOS] Mode dégradé DÉSACTIVÉ")

    def reset(self):
        """Réinitialise toute la configuration et les compteurs."""
        with self._rlock:
            self._global_enabled = False
            self._global_failure_rate = 0.1
            self._global_failure_types = [FailureType.INTERNAL_ERROR]
            self._global_latency_ms = 0
            self._endpoint_configs.clear()
            self._stats = ChaosStats()
            logger.info("[CHAOS] Configuration réinitialisée")

    def configure_endpoint(self, endpoint_tag: str,
                           failure_rate: float = 0.1,
                           failure_types: Optional[List[str]] = None,
                           latency_ms: int = 0,
                           latency_jitter_ms: int = 0,
                           enabled: bool = True):
        """Configure le chaos pour un endpoint spécifique."""
        with self._rlock:
            fts = [FailureType(ft) for ft in (failure_types or ["INTERNAL_ERROR"])]
            self._endpoint_configs[endpoint_tag] = EndpointChaosConfig(
                failure_rate=max(0.0, min(1.0, failure_rate)),
                failure_types=fts,
                latency_ms=max(0, latency_ms),
                latency_jitter_ms=max(0, latency_jitter_ms),
                enabled=enabled,
            )
            logger.info("[CHAOS] Endpoint '%s' configuré — rate=%.1f%% latency=%dms",
                        endpoint_tag, failure_rate * 100, latency_ms)

    def remove_endpoint(self, endpoint_tag: str):
        """Supprime la configuration chaos d'un endpoint."""
        with self._rlock:
            self._endpoint_configs.pop(endpoint_tag, None)

    # ── Injection ────────────────────────────────────────────────────────────

    def inject_chaos(self, endpoint_tag: str = "default"):
        """
        Point d'injection principal. Appelé au début de chaque handler.
        - Applique la latence configurée (sleep).
        - Lance une ChaosException si une panne est tirée au sort.
        Ne fait rien si le mode dégradé est désactivé.
        """
        with self._rlock:
            self._stats.total_requests += 1

            ep_cfg = self._endpoint_configs.get(endpoint_tag)

            # Résolution : config endpoint > config globale
            if ep_cfg and ep_cfg.enabled:
                enabled = True
                failure_rate = ep_cfg.failure_rate
                failure_types = ep_cfg.failure_types
                latency_ms = ep_cfg.latency_ms
                jitter_ms = ep_cfg.latency_jitter_ms
            elif self._global_enabled:
                enabled = True
                failure_rate = self._global_failure_rate
                failure_types = self._global_failure_types
                latency_ms = self._global_latency_ms
                jitter_ms = 0
            else:
                return  # mode inactif

        # Appliquer la latence (hors lock pour éviter le deadlock)
        if latency_ms > 0:
            jitter = random.randint(0, jitter_ms) if jitter_ms > 0 else 0
            sleep_ms = latency_ms + jitter
            time.sleep(sleep_ms / 1000.0)
            with self._rlock:
                self._stats.injected_latencies += 1
            logger.debug("[CHAOS] Latence injectée %dms sur '%s'", sleep_ms, endpoint_tag)

        # Tirer la panne
        if random.random() < failure_rate:
            failure_type = random.choice(failure_types)
            with self._rlock:
                self._stats.injected_failures += 1
                key = failure_type.value
                self._stats.failures_by_type[key] = \
                    self._stats.failures_by_type.get(key, 0) + 1
                self._stats.failures_by_endpoint[endpoint_tag] = \
                    self._stats.failures_by_endpoint.get(endpoint_tag, 0) + 1

            msg = _build_failure_message(failure_type, endpoint_tag)
            logger.warning("[CHAOS] Panne injectée %s sur '%s' : %s",
                           failure_type.value, endpoint_tag, msg)
            raise ChaosException(failure_type, msg, endpoint_tag)

    # ── Lecture état ──────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        with self._rlock:
            return {
                "enabled": self._global_enabled,
                "global": {
                    "failure_rate": self._global_failure_rate,
                    "failure_types": [ft.value for ft in self._global_failure_types],
                    "latency_ms": self._global_latency_ms,
                },
                "endpoints": {
                    tag: {
                        "failure_rate": cfg.failure_rate,
                        "failure_types": [ft.value for ft in cfg.failure_types],
                        "latency_ms": cfg.latency_ms,
                        "latency_jitter_ms": cfg.latency_jitter_ms,
                        "enabled": cfg.enabled,
                    }
                    for tag, cfg in self._endpoint_configs.items()
                },
                "stats": self._stats.to_dict(),
            }

    def get_stats(self) -> dict:
        with self._rlock:
            return self._stats.to_dict()

    def is_enabled(self) -> bool:
        with self._rlock:
            return self._global_enabled


# ── Messages de panne ─────────────────────────────────────────────────────────

_FAILURE_MESSAGES = {
    FailureType.TIMEOUT: [
        "Timeout réseau simulé — aucune réponse de l'émetteur",
        "Connexion expirée après 30s (mode dégradé)",
        "L'hôte distant ne répond pas (chaos inject)",
    ],
    FailureType.NETWORK_ERROR: [
        "Erreur réseau simulée — connexion refusée",
        "Hôte inaccessible (mode dégradé activé)",
        "Socket fermé de manière inattendue (chaos inject)",
    ],
    FailureType.INTERNAL_ERROR: [
        "Erreur interne simulée (mode dégradé)",
        "Exception non gérée injectée par chaos mode",
        "Défaillance du service d'autorisation (simulé)",
    ],
    FailureType.PARTIAL_FAILURE: [
        "Réponse partielle — certains champs manquants (simulé)",
        "Traitement incomplet — mode dégradé actif",
        "Résultat incertain — réessayer (chaos mode)",
    ],
    FailureType.SLOW_RESPONSE: [
        "Réponse lente simulée",
        "Service dégradé — temps de réponse élevé",
    ],
}


def _build_failure_message(failure_type: FailureType, endpoint: str) -> str:
    msgs = _FAILURE_MESSAGES.get(failure_type, ["Panne simulée"])
    return random.choice(msgs)


# ── Accès rapide au singleton ─────────────────────────────────────────────────

def get_chaos_manager() -> DegradedModeManager:
    return DegradedModeManager.get_instance()
