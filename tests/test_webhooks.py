"""
Tests — A1 Webhooks sortants
Couvre : notify (URL absente, URL invalide), get_log, get_events,
         stats, clear_log, endpoints REST.
"""
import pytest
from emv.webhooks import (
    notify, get_log, get_events, stats, clear_log,
    WEBHOOK_EVENTS, _webhook_log,
)


@pytest.fixture(autouse=True)
def clean_log():
    clear_log()
    yield
    clear_log()


# ── notify — sans URL ─────────────────────────────────────────────────────────

class TestNotifyNoUrl:
    def test_returns_entry(self):
        entry = notify("authorization.approved", {"test": True})
        assert entry is not None
        assert "status" in entry

    def test_status_skipped_when_no_url(self):
        entry = notify("authorization.approved", {}, webhook_url=None)
        assert entry["status"] == "SKIPPED"

    def test_event_type_in_entry(self):
        entry = notify("authorization.declined", {})
        assert entry["event"] == "authorization.declined"

    def test_entry_logged(self):
        notify("reversal.applied", {"amount": 1000})
        log = get_log()
        assert len(log) == 1

    def test_sent_at_present(self):
        entry = notify("card.blocked", {})
        assert "sent_at" in entry
        assert entry["sent_at"].endswith("Z")

    def test_id_present(self):
        entry = notify("card.blocked", {})
        assert "id" in entry
        assert entry["id"].startswith("WH")


# ── notify — avec URL invalide ────────────────────────────────────────────────

class TestNotifyInvalidUrl:
    def test_fire_and_forget_no_exception(self):
        # Should not raise even with invalid URL — async
        entry = notify("authorization.approved", {},
                       webhook_url="http://localhost:99999/nonexistent")
        # Entry is returned immediately (before delivery)
        assert entry is not None

    def test_initial_status_pending(self):
        entry = notify("authorization.approved", {},
                       webhook_url="http://localhost:99999/x")
        assert entry["status"] in ("PENDING", "FAILED")


# ── get_log ───────────────────────────────────────────────────────────────────

class TestGetLog:
    def test_empty_log(self):
        assert get_log() == []

    def test_single_entry(self):
        notify("reversal.applied", {})
        log = get_log()
        assert len(log) == 1

    def test_multiple_entries(self):
        notify("authorization.approved", {})
        notify("authorization.declined", {})
        notify("card.blocked", {})
        log = get_log()
        assert len(log) == 3

    def test_limit_respected(self):
        for _ in range(10):
            notify("authorization.approved", {})
        log = get_log(limit=5)
        assert len(log) == 5

    def test_most_recent_first(self):
        notify("authorization.approved", {"n": 1})
        notify("authorization.declined", {"n": 2})
        log = get_log()
        # Most recent = last appended = first in reversed list
        assert log[0]["event"] == "authorization.declined"

    def test_max_log_size(self):
        """Le log ne dépasse pas 200 entrées."""
        for _ in range(250):
            notify("authorization.approved", {})
        assert len(_webhook_log) <= 200


# ── get_events ────────────────────────────────────────────────────────────────

class TestGetEvents:
    def test_returns_list(self):
        events = get_events()
        assert isinstance(events, list)
        assert len(events) > 0

    def test_each_event_has_keys(self):
        for e in get_events():
            assert "event" in e
            assert "label" in e

    def test_all_webhook_events_present(self):
        event_keys = {e["event"] for e in get_events()}
        for key in WEBHOOK_EVENTS:
            assert key in event_keys

    def test_labels_non_empty(self):
        for e in get_events():
            assert len(e["label"]) > 0


# ── stats ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_keys(self):
        s = stats()
        assert "total" in s
        assert "delivered" in s
        assert "failed" in s
        assert "skipped" in s

    def test_empty_stats(self):
        s = stats()
        assert s["total"] == 0

    def test_skipped_count(self):
        notify("authorization.approved", {}, webhook_url=None)
        notify("authorization.declined", {}, webhook_url=None)
        s = stats()
        assert s["skipped"] == 2
        assert s["total"] == 2


# ── clear_log ─────────────────────────────────────────────────────────────────

class TestClearLog:
    def test_clears_all(self):
        notify("authorization.approved", {})
        notify("authorization.declined", {})
        clear_log()
        assert get_log() == []

    def test_clears_empty_safe(self):
        clear_log()  # should not raise
        assert get_log() == []


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestWebhookEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        clear_log()

    def test_get_log_empty(self):
        r = self.client.get("/api/v1/webhooks/log")
        assert r.status_code == 200
        data = r.get_json()
        assert "log" in data
        assert "stats" in data

    def test_get_events(self):
        r = self.client.get("/api/v1/webhooks/events")
        assert r.status_code == 200
        data = r.get_json()
        assert "events" in data
        assert len(data["events"]) > 0

    def test_get_stats(self):
        r = self.client.get("/api/v1/webhooks/stats")
        assert r.status_code == 200
        data = r.get_json()
        assert "total" in data

    def test_test_webhook_no_url(self):
        r = self.client.post("/api/v1/webhooks/test",
                             json={"event": "authorization.approved"})
        assert r.status_code == 200
        data = r.get_json()
        assert "entry" in data
        assert "message" in data

    def test_test_webhook_custom_event(self):
        r = self.client.post("/api/v1/webhooks/test",
                             json={"event": "card.blocked",
                                   "payload": {"pan": "****1111"}})
        assert r.status_code == 200

    def test_test_webhook_custom_url(self):
        r = self.client.post("/api/v1/webhooks/test",
                             json={"webhook_url": "http://localhost:9/test"})
        assert r.status_code == 200
        data = r.get_json()
        assert "localhost" in data["url"]

    def test_delete_log(self):
        notify("authorization.approved", {})
        r = self.client.delete("/api/v1/webhooks/log")
        assert r.status_code == 200
        log_r = self.client.get("/api/v1/webhooks/log")
        assert log_r.get_json()["stats"]["total"] == 0

    def test_log_after_test_post(self):
        self.client.post("/api/v1/webhooks/test", json={})
        r = self.client.get("/api/v1/webhooks/log")
        data = r.get_json()
        assert data["stats"]["total"] >= 1
