"""
Tests unitaires — Dashboard D5 : système d'alertes (T008).
Couvre get_active_alerts, get_alert_summary et l'endpoint /api/v1/alerts.
"""
import pytest
from unittest.mock import MagicMock, patch
from emv.alerts import (
    get_active_alerts, get_alert_summary,
    CONTACTLESS_MAX, CONTACTLESS_WARNING_PCT, CONTACTLESS_CRITICAL_PCT,
    FAILURE_BURST_THRESHOLD, FAILURE_BURST_WINDOW,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_card(pan="4970000000001234", status="ACTIVE",
               contactless_cumul=0, daily_count=0, daily_amount=0,
               daily_contactless_count=0):
    c = MagicMock()
    c.pan = pan
    c.status = status
    c.contactless_cumul = contactless_cumul
    c.daily_count = daily_count
    c.daily_amount = daily_amount
    c.daily_contactless_count = daily_contactless_count
    return c


def _make_card_db(cards=None):
    db = MagicMock()
    db.all_cards.return_value = cards or []
    return db


def _make_txn(approved=True):
    t = MagicMock()
    t.approved = approved
    t.status = "APPROVED" if approved else "DECLINED"
    return t


def _make_transaction_log(transactions=None):
    tl = MagicMock()
    tl.get_all.return_value = transactions or []
    return tl


# ═══════════════════════════════════════════════════════════════════════════════
# Alertes sans contact
# ═══════════════════════════════════════════════════════════════════════════════

class TestContactlessAlerts:

    def _call(self, cumul):
        card = _make_card(contactless_cumul=cumul)
        return get_active_alerts(
            card_db=_make_card_db([card]),
            transaction_log=_make_transaction_log(),
            chargebacks=[],
            preauths=[],
            bin_blacklist_obj=None,
        )

    def test_no_alert_below_warning(self):
        alerts = self._call(int(CONTACTLESS_MAX * 0.50))
        types  = [a["type"] for a in alerts]
        assert "CONTACTLESS_CUMUL_HIGH" not in types

    def test_warning_at_70pct(self):
        alerts = self._call(int(CONTACTLESS_MAX * CONTACTLESS_WARNING_PCT + 1))
        types  = [a["type"] for a in alerts]
        assert "CONTACTLESS_CUMUL_HIGH" in types
        sev = next(a["severity"] for a in alerts if a["type"] == "CONTACTLESS_CUMUL_HIGH")
        assert sev == "WARNING"

    def test_critical_at_90pct(self):
        alerts = self._call(int(CONTACTLESS_MAX * CONTACTLESS_CRITICAL_PCT + 1))
        types  = [a["type"] for a in alerts]
        assert "CONTACTLESS_CUMUL_HIGH" in types
        sev = next(a["severity"] for a in alerts if a["type"] == "CONTACTLESS_CUMUL_HIGH")
        assert sev == "CRITICAL"

    def test_blocked_card_ignored(self):
        card = _make_card(contactless_cumul=int(CONTACTLESS_MAX * 0.95), status="BLOCKED")
        alerts = get_active_alerts(
            card_db=_make_card_db([card]),
            transaction_log=_make_transaction_log(),
            chargebacks=[], preauths=[], bin_blacklist_obj=None,
        )
        types = [a["type"] for a in alerts]
        assert "CONTACTLESS_CUMUL_HIGH" not in types


# ═══════════════════════════════════════════════════════════════════════════════
# Alertes taux d'échec burst
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailureBurstAlerts:

    def _call_with_transactions(self, n_failed, n_approved):
        txns = (
            [_make_txn(approved=False)] * n_failed
            + [_make_txn(approved=True)]  * n_approved
        )
        return get_active_alerts(
            card_db=_make_card_db([]),
            transaction_log=_make_transaction_log(txns),
            chargebacks=[], preauths=[], bin_blacklist_obj=None,
        )

    def test_no_burst_below_threshold(self):
        # 40 % refus → pas d'alerte
        alerts = self._call_with_transactions(4, 6)
        types  = [a["type"] for a in alerts]
        assert "TRANSACTION_FAILURE_BURST" not in types

    def test_burst_above_threshold(self):
        # 60 % refus → alerte
        alerts = self._call_with_transactions(6, 4)
        types  = [a["type"] for a in alerts]
        assert "TRANSACTION_FAILURE_BURST" in types

    def test_no_transactions_no_alert(self):
        alerts = self._call_with_transactions(0, 0)
        types  = [a["type"] for a in alerts]
        assert "TRANSACTION_FAILURE_BURST" not in types


# ═══════════════════════════════════════════════════════════════════════════════
# Alertes chargebacks
# ═══════════════════════════════════════════════════════════════════════════════

class TestChargebackAlerts:

    def _make_cb(self, status="OPEN"):
        cb = MagicMock()
        cb.status = status
        return cb

    def test_no_alert_few_chargebacks(self):
        cbs = [self._make_cb("OPEN")] * 2
        alerts = get_active_alerts(
            card_db=_make_card_db([]),
            transaction_log=_make_transaction_log(),
            chargebacks=cbs, preauths=[], bin_blacklist_obj=None,
        )
        types = [a["type"] for a in alerts]
        assert "CHARGEBACK_SURGE" not in types

    def test_alert_on_chargeback_surge(self):
        cbs = [self._make_cb("OPEN")] * 5
        alerts = get_active_alerts(
            card_db=_make_card_db([]),
            transaction_log=_make_transaction_log(),
            chargebacks=cbs, preauths=[], bin_blacklist_obj=None,
        )
        types = [a["type"] for a in alerts]
        assert "CHARGEBACK_SURGE" in types

    def test_closed_chargebacks_not_counted(self):
        cbs = [self._make_cb("CLOSED")] * 10
        alerts = get_active_alerts(
            card_db=_make_card_db([]),
            transaction_log=_make_transaction_log(),
            chargebacks=cbs, preauths=[], bin_blacklist_obj=None,
        )
        types = [a["type"] for a in alerts]
        assert "CHARGEBACK_SURGE" not in types


# ═══════════════════════════════════════════════════════════════════════════════
# get_alert_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertSummary:

    def test_empty_alerts(self):
        s = get_alert_summary([])
        assert s["total"] == 0
        assert s["critical"] == 0
        assert s["warning"] == 0

    def test_counts_by_severity(self):
        alerts = [
            {"severity": "CRITICAL", "type": "X", "message": ""},
            {"severity": "CRITICAL", "type": "X", "message": ""},
            {"severity": "WARNING",  "type": "Y", "message": ""},
            {"severity": "INFO",     "type": "Z", "message": ""},
        ]
        s = get_alert_summary(alerts)
        assert s["total"]    == 4
        assert s["critical"] == 2
        assert s["warning"]  == 1
        assert s["info"]     == 1

    def test_highest_severity_critical(self):
        alerts = [
            {"severity": "WARNING",  "type": "A", "message": ""},
            {"severity": "CRITICAL", "type": "B", "message": ""},
        ]
        s = get_alert_summary(alerts)
        assert s["highest_severity"] == "CRITICAL"

    def test_highest_severity_none_when_empty(self):
        s = get_alert_summary([])
        assert s["highest_severity"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoint GET /api/v1/alerts (intégration Flask)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertsEndpoint:

    @pytest.fixture
    def client(self):
        from server import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/v1/alerts")
        assert r.status_code == 200

    def test_response_has_alerts_key(self, client):
        data = client.get("/api/v1/alerts").get_json()
        assert "alerts" in data

    def test_response_has_summary(self, client):
        data = client.get("/api/v1/alerts").get_json()
        assert "summary" in data
        s = data["summary"]
        assert "total" in s
        assert "critical" in s
        assert "warning" in s

    def test_response_has_generated_at(self, client):
        data = client.get("/api/v1/alerts").get_json()
        assert "generated_at" in data

    def test_response_has_count(self, client):
        data = client.get("/api/v1/alerts").get_json()
        assert "count" in data
        assert data["count"] == len(data["alerts"])
