"""
P4 — Cache distribué : Redis + fallback in-memory.
Si REDIS_URL est défini, utilise Redis. Sinon, bascule automatiquement sur
un cache en mémoire avec TTL intégré. L'API est identique dans les deux cas.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")
_DEFAULT_TTL = 300  # 5 minutes


# ── Backend Redis ─────────────────────────────────────────────────────────────

class RedisBackend:
    def __init__(self, url: str):
        import redis
        self._client = redis.from_url(url, decode_responses=False, socket_timeout=2)
        self._client.ping()
        logger.info("[CACHE] Backend Redis connecté : %s", url.split("@")[-1])

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning("[CACHE] Redis get error: %s", e)
            return None

    def set(self, key: str, value: bytes, ttl: int = _DEFAULT_TTL) -> bool:
        try:
            return bool(self._client.setex(key, ttl, value))
        except Exception as e:
            logger.warning("[CACHE] Redis set error: %s", e)
            return False

    def delete(self, key: str) -> bool:
        try:
            return bool(self._client.delete(key))
        except Exception:
            return False

    def exists(self, key: str) -> bool:
        try:
            return bool(self._client.exists(key))
        except Exception:
            return False

    def flush(self, prefix: str = "") -> int:
        try:
            if prefix:
                keys = self._client.keys("{}*".format(prefix))
                if keys:
                    return self._client.delete(*keys)
                return 0
            return self._client.flushdb()
        except Exception as e:
            logger.warning("[CACHE] Redis flush error: %s", e)
            return 0

    def ttl(self, key: str) -> int:
        try:
            return self._client.ttl(key)
        except Exception:
            return -1

    def keys(self, pattern: str = "*") -> List[str]:
        try:
            return [k.decode() if isinstance(k, bytes) else k
                    for k in self._client.keys(pattern)]
        except Exception:
            return []

    def info(self) -> dict:
        try:
            info = self._client.info()
            return {
                "backend": "redis",
                "version": info.get("redis_version", "?"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "?"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
            }
        except Exception:
            return {"backend": "redis", "error": "connection_failed"}


# ── Backend in-memory ─────────────────────────────────────────────────────────

class _CacheEntry:
    __slots__ = ("value", "expires_at")
    def __init__(self, value: bytes, ttl: int):
        self.value = value
        self.expires_at = time.monotonic() + ttl if ttl > 0 else None

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.monotonic() > self.expires_at


class InMemoryBackend:
    def __init__(self):
        self._store: Dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._sets = 0
        logger.info("[CACHE] Backend in-memory activé (Redis non configuré)")

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None or entry.is_expired():
                if entry:
                    del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    def set(self, key: str, value: bytes, ttl: int = _DEFAULT_TTL) -> bool:
        with self._lock:
            self._store[key] = _CacheEntry(value, ttl)
            self._sets += 1
            return True

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        with self._lock:
            entry = self._store.get(key)
            if entry and entry.is_expired():
                del self._store[key]
                return False
            return entry is not None

    def flush(self, prefix: str = "") -> int:
        with self._lock:
            if prefix:
                keys = [k for k in self._store if k.startswith(prefix)]
                for k in keys:
                    del self._store[k]
                return len(keys)
            count = len(self._store)
            self._store.clear()
            return count

    def ttl(self, key: str) -> int:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return -2
            if entry.expires_at is None:
                return -1
            remaining = entry.expires_at - time.monotonic()
            return max(0, int(remaining))

    def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        with self._lock:
            self._evict_expired()
            return [k for k in self._store if fnmatch.fnmatch(k, pattern)]

    def _evict_expired(self):
        expired = [k for k, v in self._store.items() if v.is_expired()]
        for k in expired:
            del self._store[k]

    def info(self) -> dict:
        with self._lock:
            self._evict_expired()
            total = self._hits + self._misses
            return {
                "backend": "in_memory",
                "keys": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "sets": self._sets,
                "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
            }


# ── CacheManager ──────────────────────────────────────────────────────────────

class CacheManager:
    """
    Gestionnaire de cache — singleton thread-safe.
    Utilise Redis si REDIS_URL est configuré, sinon in-memory avec TTL.
    API identique dans les deux cas.
    """

    _instance: Optional["CacheManager"] = None
    _lock = threading.Lock()

    def __init__(self, redis_url: str = ""):
        self._redis_url = redis_url or REDIS_URL
        self._backend = self._init_backend()
        self._namespace = "emv:"

    @classmethod
    def get_instance(cls) -> "CacheManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            cls._instance = None

    def _init_backend(self):
        if self._redis_url:
            try:
                return RedisBackend(self._redis_url)
            except Exception as e:
                logger.warning("[CACHE] Redis indisponible (%s) — fallback in-memory", e)
        return InMemoryBackend()

    @property
    def backend_type(self) -> str:
        return "redis" if isinstance(self._backend, RedisBackend) else "in_memory"

    def _k(self, key: str) -> str:
        return "{}{}".format(self._namespace, key)

    # ── API cache ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        import pickle
        raw = self._backend.get(self._k(key))
        if raw is None:
            return None
        try:
            return pickle.loads(raw)
        except Exception:
            return raw

    def set(self, key: str, value: Any, ttl: int = _DEFAULT_TTL) -> bool:
        import pickle
        try:
            raw = pickle.dumps(value)
        except Exception:
            raw = str(value).encode()
        return self._backend.set(self._k(key), raw, ttl)

    def get_str(self, key: str) -> Optional[str]:
        raw = self._backend.get(self._k(key))
        if raw is None:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def set_str(self, key: str, value: str, ttl: int = _DEFAULT_TTL) -> bool:
        return self._backend.set(self._k(key), value.encode("utf-8"), ttl)

    def delete(self, key: str) -> bool:
        return self._backend.delete(self._k(key))

    def exists(self, key: str) -> bool:
        return self._backend.exists(self._k(key))

    def ttl(self, key: str) -> int:
        return self._backend.ttl(self._k(key))

    def flush(self, prefix: str = "") -> int:
        full_prefix = self._namespace + prefix
        return self._backend.flush(full_prefix)

    def keys(self, pattern: str = "*") -> List[str]:
        ns = self._namespace
        raw_keys = self._backend.keys("{}{}".format(ns, pattern))
        return [k[len(ns):] if k.startswith(ns) else k for k in raw_keys]

    # ── Helpers métier ────────────────────────────────────────────────────────

    def cache_stats(self, stats_dict: dict, ttl: int = 5) -> bool:
        """Cache les statistiques globales (TTL court)."""
        return self.set("global:stats", stats_dict, ttl=ttl)

    def get_cached_stats(self) -> Optional[dict]:
        return self.get("global:stats")

    def cache_threeds_session(self, session_id: str, session_data: dict,
                               ttl: int = 600) -> bool:
        """Cache une session 3DS2 (TTL 10min)."""
        return self.set("3ds:{}".format(session_id), session_data, ttl=ttl)

    def get_threeds_session(self, session_id: str) -> Optional[dict]:
        return self.get("3ds:{}".format(session_id))

    def invalidate_threeds_session(self, session_id: str) -> bool:
        return self.delete("3ds:{}".format(session_id))

    def cache_token_lookup(self, token: str, pan_hash: str,
                            ttl: int = 3600) -> bool:
        """Cache un lookup token→PAN_hash (TTL 1h)."""
        return self.set_str("token:{}".format(token), pan_hash, ttl=ttl)

    def get_token_lookup(self, token: str) -> Optional[str]:
        return self.get_str("token:{}".format(token))

    # ── Statut ────────────────────────────────────────────────────────────────

    def get_info(self) -> dict:
        info = self._backend.info()
        info["namespace"] = self._namespace
        info["redis_url_configured"] = bool(self._redis_url)
        return info


# ── Accès rapide ──────────────────────────────────────────────────────────────

def get_cache() -> CacheManager:
    return CacheManager.get_instance()
