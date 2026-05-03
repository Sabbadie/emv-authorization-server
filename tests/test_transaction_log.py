"""
Tests : journal d'audit des transactions + endpoints manquants.

Couvre :
  - log_event() sur Transaction
  - Événements produits par authorize() à chaque étape
  - GET /api/v1/transactions/<id>/log
  - GET /api/v1/transactions/rrn/<rrn>
  - POST /api/v1/transactions/search (filtres multi-critères)
  - GET /api/v1/transactions?filters (filtres avancés)
  - GET /api/v1/cards/<pan>/history
  - PATCH /api/v1/cards/<pan>
  - GET /api/v1 (index)
  - TransactionLog.get_by_rrn(), get_all() avec filtres, count()
"""

import json
import pytest
from datetime import datetime, timezone

from emv.authorization import authorize
from models.card import card_db, CardStatus
from models.transaction import transaction_log, TransactionStatus, Transaction

PAN_ACTIVE  = "4111111111111111"
PAN_BLOCKED = "4000000000000028"
PAN_EXPIRED = "4000000000000010"
PAN_INSUF   = "4000000000000036"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset():
    card = card_db.get_card(PAN_ACTIVE)
    if card:
        card.status = CardStatus.ACTIVE
        card.balance = 500000
        card.daily_spent = 0
        card.daily_limit = 200000
        card.contactless_cumul = 0
        card.consecutive_offline = 0
    for pan in (PAN_ACTIVE, PAN_BLOCKED, PAN_EXPIRED, PAN_INSUF):
        ids = transaction_log._pan_index.pop(pan, [])
        for tid in ids:
            transaction_log._transactions.pop(tid, None)


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data),
                       headers={"Content-Type": "application/json"})


# ─────────────────────────────────────────────────────────────────────────────
# Fixture client
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    from server import app, limiter
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# Tests : Transaction.log_event()
# ─────────────────────────────────────────────────────────────────────────────

class TestLogEvent:
    def test_log_event_adds_entry(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        txn.log_event("TEST_STAGE", "message test")
        assert len(txn.events) == 1

    def test_log_event_has_required_fields(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        txn.log_event("TEST_STAGE", "message test", level="WARN", data={"k": "v"})
        e = txn.events[0]
        assert e["stage"]   == "TEST_STAGE"
        assert e["message"] == "message test"
        assert e["level"]   == "WARN"
        assert e["data"]    == {"k": "v"}
        assert "at" in e

    def test_log_event_default_level_is_info(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        txn.log_event("S", "m")
        assert txn.events[0]["level"] == "INFO"

    def test_multiple_events_ordered(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        txn.log_event("STAGE_A", "first")
        txn.log_event("STAGE_B", "second")
        assert txn.events[0]["stage"] == "STAGE_A"
        assert txn.events[1]["stage"] == "STAGE_B"

    def test_events_empty_by_default(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        assert txn.events == []

    def test_log_event_data_defaults_to_empty_dict(self):
        txn = Transaction("4111111111111111", 1000, "978", "00")
        txn.log_event("S", "m")
        assert txn.events[0]["data"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Tests : authorize() produit les événements attendus
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthorizationEvents:
    def setup_method(self):
        _reset()

    def _stages(self, txn):
        return [e["stage"] for e in txn.events]

    def test_approved_transaction_has_created_event(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "TRANSACTION_CREATED" in self._stages(res.transaction)

    def test_approved_transaction_has_amount_evaluation(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "AMOUNT_EVALUATION" in self._stages(res.transaction)

    def test_approved_transaction_has_giecb_evaluation(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "GIECB_EVALUATION" in self._stages(res.transaction)

    def test_approved_transaction_has_card_lookup(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "CARD_LOOKUP" in self._stages(res.transaction)

    def test_approved_transaction_has_balance_check(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "BALANCE_CHECK" in self._stages(res.transaction)

    def test_approved_transaction_has_authorization_decision(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "AUTHORIZATION_DECISION" in self._stages(res.transaction)

    def test_approved_decision_level_is_info(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        dec = next(e for e in res.transaction.events
                   if e["stage"] == "AUTHORIZATION_DECISION")
        assert dec["level"] == "INFO"

    def test_declined_blocked_card_has_decision_event(self):
        res = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        assert not res.approved
        assert "AUTHORIZATION_DECISION" in self._stages(res.transaction)

    def test_declined_decision_level_is_error(self):
        res = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        dec = next(e for e in res.transaction.events
                   if e["stage"] == "AUTHORIZATION_DECISION")
        assert dec["level"] == "ERROR"

    def test_transaction_created_data_has_amount(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        created = next(e for e in res.transaction.events
                       if e["stage"] == "TRANSACTION_CREATED")
        assert created["data"]["amount"] == 5000

    def test_transaction_created_data_has_pan_masked(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        created = next(e for e in res.transaction.events
                       if e["stage"] == "TRANSACTION_CREATED")
        assert "*" in created["data"]["pan_masked"]
        assert PAN_ACTIVE not in created["data"]["pan_masked"]

    def test_amount_evaluation_data_has_tier(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        ev = next(e for e in res.transaction.events
                  if e["stage"] == "AMOUNT_EVALUATION")
        assert "tier" in ev["data"]
        assert "auth_path" in ev["data"]

    def test_giecb_evaluation_data_has_scheme(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        ev = next(e for e in res.transaction.events
                  if e["stage"] == "GIECB_EVALUATION")
        assert "scheme" in ev["data"]

    def test_emv_parsing_event_when_no_field55(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert "EMV_PARSING" in self._stages(res.transaction)

    def test_balance_check_data_has_balance(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        ev = next(e for e in res.transaction.events
                  if e["stage"] == "BALANCE_CHECK")
        assert "balance" in ev["data"]
        assert "daily_spent" in ev["data"]

    def test_declined_insufficient_funds_event_data(self):
        res = authorize(PAN_INSUF, 5000, "978", "00", skip_crypto=True)
        assert not res.approved
        dec = next((e for e in res.transaction.events
                    if e["stage"] == "AUTHORIZATION_DECISION"), None)
        assert dec is not None
        assert dec["data"]["response_code"] in ("51", "61")

    def test_events_count_reasonable(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert len(res.transaction.events) >= 5


# ─────────────────────────────────────────────────────────────────────────────
# Tests : TransactionLog — get_by_rrn(), get_all() filtres, count()
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionLogExtended:
    def setup_method(self):
        _reset()

    def test_get_by_rrn_returns_correct_txn(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        found = transaction_log.get_by_rrn(res.transaction.rrn)
        assert found is res.transaction

    def test_get_by_rrn_unknown_returns_none(self):
        assert transaction_log.get_by_rrn("RRN_UNKNOWN_XYZ") is None

    def test_get_all_filter_status_approved(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        results = transaction_log.get_all(limit=100, status="APPROVED")
        assert all(t.status == "APPROVED" for t in results)

    def test_get_all_filter_amount_min(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 50000, "978", "00", skip_crypto=True)
        results = transaction_log.get_all(limit=100, amount_min=10000)
        assert all(t.amount >= 10000 for t in results)

    def test_get_all_filter_amount_max(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 50000, "978", "00", skip_crypto=True)
        results = transaction_log.get_all(limit=100, amount_max=10000)
        assert all(t.amount <= 10000 for t in results)

    def test_get_all_filter_amount_range(self):
        authorize(PAN_ACTIVE, 1000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 20000, "978", "00", skip_crypto=True)
        results = transaction_log.get_all(limit=100,
                                          amount_min=2000, amount_max=10000)
        assert all(2000 <= t.amount <= 10000 for t in results)

    def test_get_all_filter_terminal_id(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", terminal_id="TERM_A",
                  skip_crypto=True)
        authorize(PAN_ACTIVE, 5000, "978", "00", terminal_id="TERM_B",
                  skip_crypto=True)
        results = transaction_log.get_all(limit=100, terminal_id="TERM_A")
        assert all((t.terminal_id or "").upper() == "TERM_A" for t in results)

    def test_get_all_filter_rrn(self):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        results = transaction_log.get_all(limit=100, rrn=res.transaction.rrn)
        assert len(results) == 1
        assert results[0].rrn == res.transaction.rrn

    def test_count_returns_integer(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        n = transaction_log.count()
        assert isinstance(n, int) and n >= 1

    def test_count_with_filter(self):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        n = transaction_log.count(status="APPROVED")
        n_blocked = transaction_log.count(status="DECLINED")
        assert n >= 1
        assert n_blocked >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests : GET /api/v1/transactions/<id>/log
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLogEndpoint:
    def setup_method(self):
        _reset()

    def test_log_returns_200(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        r = client.get(f"/api/v1/transactions/{res.transaction.id}/log")
        assert r.status_code == 200

    def test_log_has_transaction_id(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["transaction_id"] == res.transaction.id

    def test_log_has_rrn(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["rrn"] == res.transaction.rrn

    def test_log_has_events_list(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert isinstance(data["events"], list)
        assert len(data["events"]) >= 1

    def test_log_events_have_required_fields(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        for ev in data["events"]:
            assert "stage"   in ev
            assert "at"      in ev
            assert "level"   in ev
            assert "message" in ev
            assert "data"    in ev

    def test_log_has_summary(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert "summary" in data
        assert data["summary"]["status"] == "APPROVED"

    def test_log_summary_has_amount(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["summary"]["amount"] == 5000

    def test_log_has_event_count(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["event_count"] == len(data["events"])

    def test_log_404_for_unknown_id(self, client):
        r = client.get("/api/v1/transactions/nonexistent-id/log")
        assert r.status_code == 404

    def test_log_reversal_field_is_none_when_not_reversed(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["reversal"] is None

    def test_log_reversal_field_populated_after_reversal(self, client):
        from emv.reversal import process_reversal
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        process_reversal(transaction_id=res.transaction.id)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        assert data["reversal"] is not None
        assert data["reversal"]["reversed_at"] is not None

    def test_log_contains_reversal_event(self, client):
        from emv.reversal import process_reversal
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        process_reversal(transaction_id=res.transaction.id)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        stages = [e["stage"] for e in data["events"]]
        assert "REVERSAL_APPLIED" in stages

    def test_declined_txn_has_error_event(self, client):
        res = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/transactions/{res.transaction.id}/log").get_json()
        error_events = [e for e in data["events"] if e["level"] == "ERROR"]
        assert len(error_events) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests : GET /api/v1/transactions/rrn/<rrn>
# ─────────────────────────────────────────────────────────────────────────────

class TestGetByRRN:
    def setup_method(self):
        _reset()

    def test_found_by_rrn_returns_200(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        r = client.get(f"/api/v1/transactions/rrn/{res.transaction.rrn}")
        assert r.status_code == 200

    def test_found_by_rrn_has_correct_id(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(
            f"/api/v1/transactions/rrn/{res.transaction.rrn}").get_json()
        assert data["id"] == res.transaction.id

    def test_unknown_rrn_returns_404(self, client):
        r = client.get("/api/v1/transactions/rrn/RRNNEVEREXISTED")
        assert r.status_code == 404

    def test_response_has_tpa_response(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(
            f"/api/v1/transactions/rrn/{res.transaction.rrn}").get_json()
        assert "tpa_response" in data


# ─────────────────────────────────────────────────────────────────────────────
# Tests : GET /api/v1/transactions (filtres avancés)
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionFilters:
    def setup_method(self):
        _reset()

    def test_filter_by_status_approved(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        data = client.get("/api/v1/transactions?status=APPROVED").get_json()
        assert all(t["status"] == "APPROVED" for t in data["transactions"])

    def test_filter_by_status_declined(self, client):
        authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        data = client.get("/api/v1/transactions?status=DECLINED").get_json()
        assert all(t["status"] == "DECLINED" for t in data["transactions"])

    def test_filter_by_amount_min(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 50000, "978", "00", skip_crypto=True)
        data = client.get("/api/v1/transactions?amount_min=10000").get_json()
        assert all(t["amount"] >= 10000 for t in data["transactions"])

    def test_filter_by_amount_max(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 50000, "978", "00", skip_crypto=True)
        data = client.get("/api/v1/transactions?amount_max=10000").get_json()
        assert all(t["amount"] <= 10000 for t in data["transactions"])

    def test_filter_invalid_amount_returns_400(self, client):
        r = client.get("/api/v1/transactions?amount_min=not_a_number")
        assert r.status_code == 400

    def test_response_has_filters_applied(self, client):
        data = client.get("/api/v1/transactions?status=APPROVED").get_json()
        assert "filters_applied" in data

    def test_response_has_total_filtered(self, client):
        data = client.get("/api/v1/transactions").get_json()
        assert "total_filtered" in data


# ─────────────────────────────────────────────────────────────────────────────
# Tests : POST /api/v1/transactions/search
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchEndpoint:
    def setup_method(self):
        _reset()

    def test_search_returns_200(self, client):
        r = post_json(client, "/api/v1/transactions/search", {})
        assert r.status_code == 200

    def test_search_has_transactions_key(self, client):
        r = post_json(client, "/api/v1/transactions/search", {})
        assert "transactions" in r.get_json()

    def test_search_by_status(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        data = post_json(client, "/api/v1/transactions/search",
                         {"status": "APPROVED"}).get_json()
        assert all(t["status"] == "APPROVED" for t in data["transactions"])

    def test_search_by_amount_range(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        authorize(PAN_ACTIVE, 50000, "978", "00", skip_crypto=True)
        data = post_json(client, "/api/v1/transactions/search",
                         {"amount_min": 10000, "amount_max": 100000}).get_json()
        assert all(10000 <= t["amount"] <= 100000 for t in data["transactions"])

    def test_search_with_rrn(self, client):
        res = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = post_json(client, "/api/v1/transactions/search",
                         {"rrn": res.transaction.rrn}).get_json()
        assert len(data["transactions"]) == 1
        assert data["transactions"][0]["id"] == res.transaction.id

    def test_search_empty_criteria_returns_all(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = post_json(client, "/api/v1/transactions/search",
                         {"limit": 100}).get_json()
        assert data["count"] >= 1

    def test_search_has_total_matching(self, client):
        data = post_json(client, "/api/v1/transactions/search", {}).get_json()
        assert "total_matching" in data

    def test_search_has_criteria_echo(self, client):
        data = post_json(client, "/api/v1/transactions/search",
                         {"status": "APPROVED"}).get_json()
        assert "criteria" in data

    def test_search_invalid_amount_returns_400(self, client):
        r = post_json(client, "/api/v1/transactions/search",
                      {"amount_min": "bad"})
        assert r.status_code == 400

    def test_search_pagination(self, client):
        for _ in range(5):
            authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = post_json(client, "/api/v1/transactions/search",
                         {"limit": 2, "offset": 0}).get_json()
        assert data["count"] <= 2


# ─────────────────────────────────────────────────────────────────────────────
# Tests : GET /api/v1/cards/<pan>/history
# ─────────────────────────────────────────────────────────────────────────────

class TestCardHistory:
    def setup_method(self):
        _reset()

    def test_history_returns_200(self, client):
        r = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history")
        assert r.status_code == 200

    def test_history_404_for_unknown_pan(self, client):
        r = client.get("/api/v1/cards/9999999999999999/history")
        assert r.status_code == 404

    def test_history_has_cardholder_name(self, client):
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert "cardholder_name" in data

    def test_history_has_block_history(self, client):
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert "block_history" in data
        assert isinstance(data["block_history"], list)

    def test_history_has_transaction_stats(self, client):
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert "transaction_stats" in data
        stats = data["transaction_stats"]
        for key in ("total", "approved", "declined", "reversed"):
            assert key in stats

    def test_history_after_transactions(self, client):
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert data["transaction_stats"]["total"] >= 1

    def test_history_has_recent_transactions(self, client):
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert "recent_transactions" in data
        assert isinstance(data["recent_transactions"], list)

    def test_history_block_event_appears(self, client):
        import json as _json
        client.post(f"/api/v1/cards/{PAN_ACTIVE}/block",
                    data=_json.dumps({"reason": "Test"}),
                    headers={"Content-Type": "application/json"})
        data = client.get(f"/api/v1/cards/{PAN_ACTIVE}/history").get_json()
        assert any(h["action"] == "BLOCKED" for h in data["block_history"])
        card_db.unblock_card(PAN_ACTIVE)


# ─────────────────────────────────────────────────────────────────────────────
# Tests : PATCH /api/v1/cards/<pan>
# ─────────────────────────────────────────────────────────────────────────────

class TestCardPatch:
    def setup_method(self):
        _reset()

    def test_patch_balance_returns_200(self, client):
        r = post_json.__func__ if False else client.patch(
            f"/api/v1/cards/{PAN_ACTIVE}",
            data=json.dumps({"balance": 999000}),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200

    def test_patch_balance_updated(self, client):
        client.patch(f"/api/v1/cards/{PAN_ACTIVE}",
                     data=json.dumps({"balance": 888000}),
                     headers={"Content-Type": "application/json"})
        card = card_db.get_card(PAN_ACTIVE)
        assert card.balance == 888000

    def test_patch_daily_limit(self, client):
        client.patch(f"/api/v1/cards/{PAN_ACTIVE}",
                     data=json.dumps({"daily_limit": 300000}),
                     headers={"Content-Type": "application/json"})
        card = card_db.get_card(PAN_ACTIVE)
        assert card.daily_limit == 300000

    def test_patch_cardholder_name_uppercased(self, client):
        client.patch(f"/api/v1/cards/{PAN_ACTIVE}",
                     data=json.dumps({"cardholder_name": "nouveau titulaire"}),
                     headers={"Content-Type": "application/json"})
        card = card_db.get_card(PAN_ACTIVE)
        assert card.cardholder_name == "NOUVEAU TITULAIRE"

    def test_patch_response_has_updated_fields(self, client):
        r = client.patch(f"/api/v1/cards/{PAN_ACTIVE}",
                         data=json.dumps({"balance": 100000, "daily_limit": 50000}),
                         headers={"Content-Type": "application/json"})
        data = r.get_json()
        assert "updated_fields" in data
        assert "balance" in data["updated_fields"]

    def test_patch_unknown_pan_returns_404(self, client):
        r = client.patch("/api/v1/cards/9999999999999999",
                         data=json.dumps({"balance": 100}),
                         headers={"Content-Type": "application/json"})
        assert r.status_code == 404

    def test_patch_invalid_balance_returns_400(self, client):
        r = client.patch(f"/api/v1/cards/{PAN_ACTIVE}",
                         data=json.dumps({"balance": "not_a_number"}),
                         headers={"Content-Type": "application/json"})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Tests : GET /api/v1 (index des routes)
# ─────────────────────────────────────────────────────────────────────────────

class TestAPIIndex:
    def test_index_returns_200(self, client):
        r = client.get("/api/v1")
        assert r.status_code == 200

    def test_index_has_endpoints(self, client):
        data = client.get("/api/v1").get_json()
        assert "endpoints" in data
        assert len(data["endpoints"]) > 0

    def test_index_has_version(self, client):
        data = client.get("/api/v1").get_json()
        assert "version" in data

    def test_index_has_total(self, client):
        data = client.get("/api/v1").get_json()
        assert "total" in data
        assert data["total"] == len(data["endpoints"])

    def test_index_contains_authorize_route(self, client):
        data = client.get("/api/v1").get_json()
        paths = [e["path"] for e in data["endpoints"]]
        assert "/api/v1/authorize" in paths

    def test_index_contains_transactions_log_route(self, client):
        data = client.get("/api/v1").get_json()
        paths = [e["path"] for e in data["endpoints"]]
        assert "/api/v1/transactions/<transaction_id>/log" in paths
