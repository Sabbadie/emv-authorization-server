"""
Tests A2 — Mode dégradé simulé / Chaos Engineering.
Couvre : DegradedModeManager, FailureType, ChaosException,
inject_chaos, configuration par endpoint, stats, reset.
"""

import pytest
import threading
import time
from emv.degraded import (
    DegradedModeManager, FailureType, ChaosException,
    EndpointChaosConfig, ChaosStats, get_chaos_manager,
)


@pytest.fixture(autouse=True)
def fresh_manager():
    """Chaque test repart d'un manager réinitialisé."""
    mgr = DegradedModeManager.get_instance()
    mgr.reset()
    yield mgr
    mgr.reset()


class TestDegradedModeManagerBasics:
    def test_singleton(self):
        m1 = DegradedModeManager.get_instance()
        m2 = DegradedModeManager.get_instance()
        assert m1 is m2

    def test_disabled_by_default(self):
        mgr = DegradedModeManager.get_instance()
        assert mgr.is_enabled() is False

    def test_enable(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=0.5)
        assert mgr.is_enabled() is True

    def test_disable(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable()
        mgr.disable()
        assert mgr.is_enabled() is False

    def test_reset_clears_enabled(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable()
        mgr.reset()
        assert mgr.is_enabled() is False

    def test_get_status_structure(self):
        mgr = DegradedModeManager.get_instance()
        status = mgr.get_status()
        assert "enabled" in status
        assert "global" in status
        assert "endpoints" in status
        assert "stats" in status

    def test_get_stats_structure(self):
        mgr = DegradedModeManager.get_instance()
        stats = mgr.get_stats()
        assert "total_requests" in stats
        assert "injected_failures" in stats
        assert "injected_latencies" in stats


class TestInjectChaosDisabled:
    def test_no_exception_when_disabled(self):
        mgr = DegradedModeManager.get_instance()
        for _ in range(20):
            mgr.inject_chaos("authorize")

    def test_total_requests_incremented(self):
        mgr = DegradedModeManager.get_instance()
        for _ in range(5):
            mgr.inject_chaos("test")
        assert mgr.get_stats()["total_requests"] == 5

    def test_no_failures_when_disabled(self):
        mgr = DegradedModeManager.get_instance()
        for _ in range(10):
            mgr.inject_chaos("authorize")
        assert mgr.get_stats()["injected_failures"] == 0


class TestInjectChaosEnabled:
    def test_failure_rate_100_always_raises(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0)
        with pytest.raises(ChaosException):
            mgr.inject_chaos("authorize")

    def test_failure_rate_0_never_raises(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=0.0)
        for _ in range(20):
            mgr.inject_chaos("authorize")

    def test_chaos_exception_has_failure_type(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0, failure_types=["INTERNAL_ERROR"])
        try:
            mgr.inject_chaos("test")
        except ChaosException as e:
            assert e.failure_type == FailureType.INTERNAL_ERROR
            assert e.endpoint == "test"
            assert len(str(e)) > 0

    def test_timeout_failure_type(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0, failure_types=["TIMEOUT"])
        with pytest.raises(ChaosException) as exc_info:
            mgr.inject_chaos("x")
        assert exc_info.value.failure_type == FailureType.TIMEOUT

    def test_network_error_failure_type(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0, failure_types=["NETWORK_ERROR"])
        with pytest.raises(ChaosException) as exc_info:
            mgr.inject_chaos("x")
        assert exc_info.value.failure_type == FailureType.NETWORK_ERROR

    def test_partial_failure_type(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0, failure_types=["PARTIAL_FAILURE"])
        with pytest.raises(ChaosException) as exc_info:
            mgr.inject_chaos("x")
        assert exc_info.value.failure_type == FailureType.PARTIAL_FAILURE

    def test_failure_counted_in_stats(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0)
        try:
            mgr.inject_chaos("endpoint_a")
        except ChaosException:
            pass
        stats = mgr.get_stats()
        assert stats["injected_failures"] == 1
        assert "endpoint_a" in stats["failures_by_endpoint"]

    def test_failure_by_type_counted(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0, failure_types=["INTERNAL_ERROR"])
        try:
            mgr.inject_chaos("x")
        except ChaosException:
            pass
        stats = mgr.get_stats()
        assert stats["failures_by_type"].get("INTERNAL_ERROR", 0) >= 1


class TestEndpointChaosConfig:
    def test_configure_endpoint(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("authorize", failure_rate=1.0,
                                failure_types=["TIMEOUT"])
        status = mgr.get_status()
        assert "authorize" in status["endpoints"]
        assert status["endpoints"]["authorize"]["failure_rate"] == 1.0

    def test_endpoint_config_overrides_global(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=0.0)
        mgr.configure_endpoint("authorize", failure_rate=1.0,
                                failure_types=["INTERNAL_ERROR"])
        with pytest.raises(ChaosException):
            mgr.inject_chaos("authorize")

    def test_endpoint_config_does_not_affect_other_endpoints(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("authorize", failure_rate=1.0)
        for _ in range(10):
            mgr.inject_chaos("other_endpoint")

    def test_remove_endpoint(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("authorize", failure_rate=1.0)
        mgr.remove_endpoint("authorize")
        status = mgr.get_status()
        assert "authorize" not in status["endpoints"]

    def test_endpoint_with_latency(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("slow_ep", failure_rate=0.0, latency_ms=50)
        t0 = time.time()
        mgr.inject_chaos("slow_ep")
        elapsed = time.time() - t0
        assert elapsed >= 0.04

    def test_disabled_endpoint_not_triggered(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("ep", failure_rate=1.0, enabled=False)
        for _ in range(10):
            mgr.inject_chaos("ep")


class TestChaosLatency:
    def test_global_latency_applied(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=0.0, latency_ms=60)
        t0 = time.time()
        mgr.inject_chaos("any")
        elapsed = time.time() - t0
        assert elapsed >= 0.05

    def test_latency_counted_in_stats(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=0.0, latency_ms=10)
        mgr.inject_chaos("any")
        assert mgr.get_stats()["injected_latencies"] >= 1


class TestChaosReset:
    def test_reset_clears_endpoint_configs(self):
        mgr = DegradedModeManager.get_instance()
        mgr.configure_endpoint("ep", failure_rate=0.5)
        mgr.reset()
        assert "ep" not in mgr.get_status()["endpoints"]

    def test_reset_clears_stats(self):
        mgr = DegradedModeManager.get_instance()
        mgr.enable(failure_rate=1.0)
        try:
            mgr.inject_chaos("x")
        except ChaosException:
            pass
        mgr.reset()
        assert mgr.get_stats()["injected_failures"] == 0
        assert mgr.get_stats()["total_requests"] == 0


class TestChaosStats:
    def test_observed_failure_rate_computed(self):
        stats = ChaosStats(total_requests=10, injected_failures=5)
        d = stats.to_dict()
        assert d["failure_rate_observed"] == pytest.approx(0.5)

    def test_zero_requests_rate_is_zero(self):
        stats = ChaosStats()
        d = stats.to_dict()
        assert d["failure_rate_observed"] == 0.0

    def test_get_chaos_manager_returns_singleton(self):
        from emv.degraded import get_chaos_manager
        m1 = get_chaos_manager()
        m2 = get_chaos_manager()
        assert m1 is m2


class TestFailureTypeEnum:
    def test_all_types_defined(self):
        types = [ft.value for ft in FailureType]
        assert "TIMEOUT" in types
        assert "NETWORK_ERROR" in types
        assert "INTERNAL_ERROR" in types
        assert "PARTIAL_FAILURE" in types
        assert "SLOW_RESPONSE" in types

    def test_from_string(self):
        assert FailureType("TIMEOUT") == FailureType.TIMEOUT
