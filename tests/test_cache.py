"""
Tests P4 — Cache Redis + fallback in-memory.
Couvre : InMemoryBackend, CacheManager (in-memory mode), TTL, flush, stats.
Redis non requis — les tests utilisent uniquement le backend in-memory.
"""

import time
import pytest
from cache import (
    InMemoryBackend, CacheManager, get_cache, _CacheEntry,
)


@pytest.fixture(autouse=True)
def reset_cache():
    CacheManager.reset_instance()
    yield
    CacheManager.reset_instance()


# ── _CacheEntry ───────────────────────────────────────────────────────────────

class TestCacheEntry:
    def test_not_expired_fresh(self):
        e = _CacheEntry(b"val", ttl=60)
        assert e.is_expired() is False

    def test_expired(self):
        e = _CacheEntry(b"val", ttl=60)
        e.expires_at = time.monotonic() - 1
        assert e.is_expired() is True

    def test_no_ttl_never_expires(self):
        e = _CacheEntry(b"val", ttl=0)
        e.expires_at = None
        assert e.is_expired() is False


# ── InMemoryBackend ───────────────────────────────────────────────────────────

class TestInMemoryBackend:
    def test_set_and_get(self):
        b = InMemoryBackend()
        b.set("k", b"hello", ttl=60)
        assert b.get("k") == b"hello"

    def test_get_missing_returns_none(self):
        b = InMemoryBackend()
        assert b.get("missing") is None

    def test_ttl_expires(self):
        b = InMemoryBackend()
        b.set("k", b"val", ttl=60)
        b._store["k"].expires_at = time.monotonic() - 1
        assert b.get("k") is None

    def test_exists_true(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=60)
        assert b.exists("k") is True

    def test_exists_false(self):
        b = InMemoryBackend()
        assert b.exists("missing") is False

    def test_exists_expired(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=60)
        b._store["k"].expires_at = time.monotonic() - 1
        assert b.exists("k") is False

    def test_delete(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=60)
        b.delete("k")
        assert b.get("k") is None

    def test_delete_nonexistent_returns_false(self):
        b = InMemoryBackend()
        assert b.delete("missing") is False

    def test_flush_all(self):
        b = InMemoryBackend()
        b.set("k1", b"v1", ttl=60)
        b.set("k2", b"v2", ttl=60)
        count = b.flush()
        assert count == 2
        assert b.get("k1") is None

    def test_flush_prefix(self):
        b = InMemoryBackend()
        b.set("emv:stats", b"v1", ttl=60)
        b.set("emv:3ds:abc", b"v2", ttl=60)
        b.set("other:key", b"v3", ttl=60)
        count = b.flush("emv:")
        assert count == 2
        assert b.get("other:key") == b"v3"

    def test_ttl_returns_remaining(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=60)
        remaining = b.ttl("k")
        assert 55 <= remaining <= 60

    def test_ttl_missing_returns_minus2(self):
        b = InMemoryBackend()
        assert b.ttl("missing") == -2

    def test_ttl_no_expiry_returns_minus1(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=0)
        b._store["k"].expires_at = None
        assert b.ttl("k") == -1

    def test_keys_pattern(self):
        b = InMemoryBackend()
        b.set("emv:stats", b"v", ttl=60)
        b.set("emv:3ds", b"v", ttl=60)
        b.set("other", b"v", ttl=60)
        keys = b.keys("emv:*")
        assert "emv:stats" in keys
        assert "other" not in keys

    def test_info_structure(self):
        b = InMemoryBackend()
        b.set("k", b"v", ttl=60)
        b.get("k")
        b.get("missing")
        info = b.info()
        assert info["backend"] == "in_memory"
        assert info["hits"] == 1
        assert info["misses"] == 1
        assert "hit_rate" in info

    def test_set_returns_true(self):
        b = InMemoryBackend()
        assert b.set("k", b"v", ttl=60) is True


# ── CacheManager ──────────────────────────────────────────────────────────────

class TestCacheManagerInMemory:
    def test_get_instance_singleton(self):
        c1 = CacheManager.get_instance()
        c2 = CacheManager.get_instance()
        assert c1 is c2

    def test_backend_type_in_memory(self):
        cm = CacheManager(redis_url="")
        assert cm.backend_type == "in_memory"

    def test_set_and_get_object(self):
        cm = CacheManager(redis_url="")
        cm.set("key1", {"data": 42}, ttl=60)
        result = cm.get("key1")
        assert result == {"data": 42}

    def test_get_missing_returns_none(self):
        cm = CacheManager(redis_url="")
        assert cm.get("missing_key") is None

    def test_set_str_and_get_str(self):
        cm = CacheManager(redis_url="")
        cm.set_str("greeting", "bonjour", ttl=60)
        assert cm.get_str("greeting") == "bonjour"

    def test_delete(self):
        cm = CacheManager(redis_url="")
        cm.set("k", "v", ttl=60)
        cm.delete("k")
        assert cm.get("k") is None

    def test_exists(self):
        cm = CacheManager(redis_url="")
        cm.set("k", "v", ttl=60)
        assert cm.exists("k") is True
        assert cm.exists("nonexistent") is False

    def test_flush(self):
        cm = CacheManager(redis_url="")
        cm.set("k1", "v1", ttl=60)
        cm.set("k2", "v2", ttl=60)
        count = cm.flush()
        assert count >= 2

    def test_ttl(self):
        cm = CacheManager(redis_url="")
        cm.set("k", "v", ttl=30)
        remaining = cm.ttl("k")
        assert 25 <= remaining <= 30

    def test_keys(self):
        cm = CacheManager(redis_url="")
        cm.set("a", 1, ttl=60)
        cm.set("b", 2, ttl=60)
        keys = cm.keys()
        assert "a" in keys
        assert "b" in keys

    def test_namespace_applied(self):
        cm = CacheManager(redis_url="")
        cm.set("mykey", "val", ttl=60)
        raw_key = cm._namespace + "mykey"
        assert cm._backend.exists(raw_key) is True

    def test_cache_stats_and_get(self):
        cm = CacheManager(redis_url="")
        stats = {"total": 100, "approved": 90}
        cm.cache_stats(stats, ttl=5)
        result = cm.get_cached_stats()
        assert result == stats

    def test_cache_threeds_session(self):
        cm = CacheManager(redis_url="")
        session = {"status": "CHALLENGE", "pan_hash": "abc123"}
        cm.cache_threeds_session("3DS-001", session, ttl=600)
        result = cm.get_threeds_session("3DS-001")
        assert result == session

    def test_invalidate_threeds_session(self):
        cm = CacheManager(redis_url="")
        cm.cache_threeds_session("3DS-002", {"status": "OK"})
        cm.invalidate_threeds_session("3DS-002")
        assert cm.get_threeds_session("3DS-002") is None

    def test_cache_token_lookup(self):
        cm = CacheManager(redis_url="")
        cm.cache_token_lookup("4999123456789012", "sha256hash", ttl=3600)
        result = cm.get_token_lookup("4999123456789012")
        assert result == "sha256hash"

    def test_get_info(self):
        cm = CacheManager(redis_url="")
        info = cm.get_info()
        assert "backend" in info
        assert info["backend"] in ("in_memory", "redis")
        assert "namespace" in info

    def test_redis_fallback_on_bad_url(self):
        cm = CacheManager(redis_url="redis://nonexistent-host:9999/0")
        assert cm.backend_type == "in_memory"

    def test_get_cache_shortcut(self):
        c = get_cache()
        assert isinstance(c, CacheManager)

    def test_reset_instance(self):
        c1 = CacheManager.get_instance()
        CacheManager.reset_instance()
        c2 = CacheManager.get_instance()
        assert c1 is not c2
