"""
Tests unitaires et d'intégration — emv/reversal.py + endpoints REST + TCP

Couvre :
  - find_original_transaction (par ID, par RRN)
  - validate_reversal (cas valides et invalides)
  - process_reversal (complet, partiel, avis, erreurs)
  - ReversalResult.to_dict()
  - Endpoints REST : POST /reverse, POST /reverse (RRN), POST /advice
  - Interface TCP : MTI 0400, MTI 0420
"""

import json
import socket
import struct
import time

import pytest

from emv.reversal import (
    find_original_transaction, validate_reversal,
    process_reversal, ReversalResult, ReversalError,
)
from emv.authorization import authorize
from models.card import card_db, CardStatus
from models.transaction import transaction_log, TransactionStatus, Transaction

PAN_ACTIVE  = "4111111111111111"
PAN_BLOCKED = "4000000000000028"

TEST_TCP_PORT = 19583


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_card():
    card = card_db.get_card(PAN_ACTIVE)
    if card:
        card.status = CardStatus.ACTIVE
        card.balance = 500000
        card.daily_spent = 0
        card.daily_limit = 200000
        card.contactless_cumul = 0
        card.consecutive_offline = 0


def _clear_txn_log(*pans):
    for pan in pans:
        ids = transaction_log._pan_index.pop(pan, [])
        for tid in ids:
            transaction_log._transactions.pop(tid, None)


def _make_approved_txn(amount=5000, pan=PAN_ACTIVE):
    """Crée et enregistre une transaction approuvée."""
    _clear_txn_log(pan)
    _reset_card()
    result = authorize(pan, amount, "978", "00", skip_crypto=True)
    assert result.approved, f"La transaction de test aurait dû être approuvée (RC={result.response_code})"
    return result.transaction


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data),
                       headers={"Content-Type": "application/json"})


def tcp_roundtrip(port, payload, host="127.0.0.1"):
    sock = socket.create_connection((host, port), timeout=5)
    try:
        body = json.dumps(payload).encode()
        sock.sendall(struct.pack(">I", len(body)) + body)
        hdr = b""
        while len(hdr) < 4:
            hdr += sock.recv(4 - len(hdr))
        n = struct.unpack(">I", hdr)[0]
        data = b""
        while len(data) < n:
            data += sock.recv(n - len(data))
        return json.loads(data)
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    from server import app, limiter
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def tcp_server():
    from emv.tcp_server import TCPAuthorizationServer
    srv = TCPAuthorizationServer(host="127.0.0.1", port=TEST_TCP_PORT)
    srv.start()
    time.sleep(0.2)
    yield srv
    srv.stop()


# ─────────────────────────────────────────────────────────────────────────────
# Tests : find_original_transaction
# ─────────────────────────────────────────────────────────────────────────────

class TestFindOriginalTransaction:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_find_by_id(self):
        txn = _make_approved_txn()
        found = find_original_transaction(transaction_id=txn.id)
        assert found is txn

    def test_find_by_rrn(self):
        txn = _make_approved_txn()
        found = find_original_transaction(rrn=txn.rrn)
        assert found is txn

    def test_id_takes_priority_over_rrn(self):
        txn = _make_approved_txn()
        found = find_original_transaction(transaction_id=txn.id, rrn="WRONG_RRN")
        assert found is txn

    def test_unknown_id_returns_none(self):
        assert find_original_transaction(transaction_id="nonexistent-id-xyz") is None

    def test_unknown_rrn_returns_none(self):
        assert find_original_transaction(rrn="RRN999999") is None

    def test_none_both_returns_none(self):
        assert find_original_transaction() is None


# ─────────────────────────────────────────────────────────────────────────────
# Tests : validate_reversal
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateReversal:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_valid_full_reversal(self):
        txn = _make_approved_txn(amount=5000)
        validate_reversal(txn, 5000)

    def test_valid_partial_reversal(self):
        txn = _make_approved_txn(amount=5000)
        validate_reversal(txn, 3000)

    def test_amount_1_is_valid(self):
        txn = _make_approved_txn(amount=5000)
        validate_reversal(txn, 1)

    def test_already_reversed_raises_56(self):
        txn = _make_approved_txn(amount=5000)
        txn.status = TransactionStatus.REVERSED
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 5000)
        assert exc_info.value.response_code == "56"

    def test_declined_raises_40(self):
        txn = _make_approved_txn(amount=5000)
        txn.status = TransactionStatus.DECLINED
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 5000)
        assert exc_info.value.response_code == "40"

    def test_error_status_raises_40(self):
        txn = _make_approved_txn(amount=5000)
        txn.status = TransactionStatus.ERROR
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 5000)
        assert exc_info.value.response_code == "40"

    def test_pending_raises_40(self):
        txn = _make_approved_txn(amount=5000)
        txn.status = TransactionStatus.PENDING
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 5000)
        assert exc_info.value.response_code == "40"

    def test_amount_exceeds_original_raises_61(self):
        txn = _make_approved_txn(amount=5000)
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 6000)
        assert exc_info.value.response_code == "61"

    def test_zero_amount_raises_13(self):
        txn = _make_approved_txn(amount=5000)
        with pytest.raises(ReversalError) as exc_info:
            validate_reversal(txn, 0)
        assert exc_info.value.response_code == "13"

    def test_negative_amount_raises(self):
        txn = _make_approved_txn(amount=5000)
        with pytest.raises(ReversalError):
            validate_reversal(txn, -100)


# ─────────────────────────────────────────────────────────────────────────────
# Tests : process_reversal — redressement complet
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessReversalFull:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_full_reversal_accepted(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id)
        assert result.accepted is True
        assert result.response_code == "00"

    def test_full_reversal_status_reversed(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id)
        assert txn.status == TransactionStatus.REVERSED

    def test_full_reversal_amount_matches(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id)
        assert result.reversal_amount == 5000

    def test_full_reversal_restores_balance(self):
        card = card_db.get_card(PAN_ACTIVE)
        card.balance = 500000
        txn = _make_approved_txn(amount=5000)
        balance_after_auth = card.balance
        process_reversal(transaction_id=txn.id)
        assert card.balance == balance_after_auth + 5000

    def test_full_reversal_restores_daily_spent(self):
        card = card_db.get_card(PAN_ACTIVE)
        txn = _make_approved_txn(amount=5000)
        daily_after_auth = card.daily_spent
        process_reversal(transaction_id=txn.id)
        assert card.daily_spent == max(0, daily_after_auth - 5000)

    def test_full_reversal_by_rrn(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(rrn=txn.rrn)
        assert result.accepted is True
        assert txn.status == TransactionStatus.REVERSED

    def test_full_reversal_sets_reversed_at(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id)
        assert txn.reversed_at is not None

    def test_reversal_not_partial(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id)
        assert txn.is_partial_reversal is False

    def test_double_reversal_rejected(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id)
        result2 = process_reversal(transaction_id=txn.id)
        assert result2.accepted is False
        assert result2.response_code == "56"

    def test_reversal_of_nonexistent_txn(self):
        result = process_reversal(transaction_id="nonexistent-id-9999")
        assert result.accepted is False
        assert result.response_code == "25"

    def test_reversal_with_terminal_id(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id, terminal_id="TERM_REV01")
        assert result.accepted is True
        assert txn.reversal_terminal_id == "TERM_REV01"

    def test_reversal_with_reversal_rrn(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id, reversal_rrn="REV_RRN_001")
        assert result.accepted is True
        assert txn.reversal_rrn == "REV_RRN_001"

    def test_result_has_original_transaction(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id)
        assert result.original_transaction is txn

    def test_reversal_of_declined_transaction(self):
        _clear_txn_log(PAN_BLOCKED)
        result_auth = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        assert result_auth.approved is False
        result_rev = process_reversal(transaction_id=result_auth.transaction.id)
        assert result_rev.accepted is False
        assert result_rev.response_code == "40"


# ─────────────────────────────────────────────────────────────────────────────
# Tests : process_reversal — redressement partiel
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessReversalPartial:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_partial_reversal_accepted(self):
        txn = _make_approved_txn(amount=10000)
        result = process_reversal(transaction_id=txn.id, reversal_amount=3000)
        assert result.accepted is True
        assert result.response_code == "00"

    def test_partial_reversal_amount(self):
        txn = _make_approved_txn(amount=10000)
        result = process_reversal(transaction_id=txn.id, reversal_amount=3000)
        assert result.reversal_amount == 3000

    def test_partial_reversal_is_partial_flag(self):
        txn = _make_approved_txn(amount=10000)
        process_reversal(transaction_id=txn.id, reversal_amount=3000)
        assert txn.is_partial_reversal is True

    def test_partial_reversal_restores_partial_balance(self):
        card = card_db.get_card(PAN_ACTIVE)
        txn = _make_approved_txn(amount=10000)
        bal_after_auth = card.balance
        process_reversal(transaction_id=txn.id, reversal_amount=3000)
        assert card.balance == bal_after_auth + 3000

    def test_partial_reversal_status_reversed(self):
        txn = _make_approved_txn(amount=10000)
        process_reversal(transaction_id=txn.id, reversal_amount=3000)
        assert txn.status == TransactionStatus.REVERSED

    def test_partial_reversal_exact_original_is_full(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id, reversal_amount=5000)
        assert result.accepted is True
        assert txn.is_partial_reversal is False

    def test_partial_reversal_exceeds_original(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id, reversal_amount=5001)
        assert result.accepted is False
        assert result.response_code == "61"


# ─────────────────────────────────────────────────────────────────────────────
# Tests : process_reversal — avis (MTI 0420)
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessReversalAdvice:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_advice_accepted(self):
        txn = _make_approved_txn(amount=5000)
        result = process_reversal(transaction_id=txn.id, is_advice=True)
        assert result.accepted is True
        assert result.is_advice is True

    def test_advice_marks_reversed(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id, is_advice=True)
        assert txn.status == TransactionStatus.REVERSED

    def test_advice_already_reversed_still_accepted(self):
        txn = _make_approved_txn(amount=5000)
        process_reversal(transaction_id=txn.id, is_advice=True)
        result2 = process_reversal(transaction_id=txn.id, is_advice=True)
        assert result2.accepted is True
        assert result2.response_code == "00"

    def test_advice_not_found_rejected(self):
        result = process_reversal(transaction_id="nonexistent", is_advice=True)
        assert result.accepted is False
        assert result.response_code == "25"


# ─────────────────────────────────────────────────────────────────────────────
# Tests : ReversalResult.to_dict()
# ─────────────────────────────────────────────────────────────────────────────

class TestReversalResultToDict:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_accepted_true_in_dict(self):
        txn = _make_approved_txn()
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert d["accepted"] is True

    def test_response_code_in_dict(self):
        txn = _make_approved_txn()
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert d["response_code"] == "00"

    def test_reversal_amount_in_dict(self):
        txn = _make_approved_txn(amount=5000)
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert d["reversal_amount"] == 5000

    def test_reversal_amount_formatted(self):
        txn = _make_approved_txn(amount=5000)
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert d["reversal_amount_formatted"] == "50.00"

    def test_original_transaction_in_dict(self):
        txn = _make_approved_txn()
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert "original_transaction" in d

    def test_message_in_dict(self):
        txn = _make_approved_txn()
        r = process_reversal(transaction_id=txn.id)
        d = r.to_dict()
        assert "message" in d
        assert d["message"] != ""

    def test_failed_result_dict(self):
        r = process_reversal(transaction_id="nonexistent")
        d = r.to_dict()
        assert d["accepted"] is False
        assert d["response_code"] == "25"


# ─────────────────────────────────────────────────────────────────────────────
# Tests : Endpoints REST
# ─────────────────────────────────────────────────────────────────────────────

class TestReversalREST:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE, PAN_BLOCKED)
        _reset_card()

    def test_reverse_by_id_returns_200(self, client):
        txn = _make_approved_txn()
        resp = post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        assert resp.status_code == 200

    def test_reverse_by_id_accepted(self, client):
        txn = _make_approved_txn()
        data = post_json(client, f"/api/v1/transactions/{txn.id}/reverse",
                         {}).get_json()
        assert data["accepted"] is True

    def test_reverse_by_id_response_code_00(self, client):
        txn = _make_approved_txn()
        data = post_json(client, f"/api/v1/transactions/{txn.id}/reverse",
                         {}).get_json()
        assert data["response_code"] == "00"

    def test_reverse_full_amount_in_response(self, client):
        txn = _make_approved_txn(amount=5000)
        data = post_json(client, f"/api/v1/transactions/{txn.id}/reverse",
                         {}).get_json()
        assert data["reversal_amount"] == 5000

    def test_partial_reverse_by_id(self, client):
        txn = _make_approved_txn(amount=10000)
        data = post_json(client, f"/api/v1/transactions/{txn.id}/reverse",
                         {"amount": 3000}).get_json()
        assert data["accepted"] is True
        assert data["reversal_amount"] == 3000

    def test_double_reverse_returns_422(self, client):
        txn = _make_approved_txn()
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        resp2 = post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        assert resp2.status_code == 422

    def test_reverse_nonexistent_returns_422(self, client):
        resp = post_json(client, "/api/v1/transactions/nonexistent-id/reverse", {})
        assert resp.status_code == 422

    def test_reverse_by_rrn_returns_200(self, client):
        txn = _make_approved_txn()
        resp = post_json(client, "/api/v1/transactions/reverse",
                         {"rrn": txn.rrn})
        assert resp.status_code == 200

    def test_reverse_by_rrn_accepted(self, client):
        txn = _make_approved_txn()
        data = post_json(client, "/api/v1/transactions/reverse",
                         {"rrn": txn.rrn}).get_json()
        assert data["accepted"] is True

    def test_reverse_by_rrn_missing_rrn_returns_400(self, client):
        resp = post_json(client, "/api/v1/transactions/reverse", {})
        assert resp.status_code == 400

    def test_reverse_by_rrn_wrong_rrn_returns_422(self, client):
        resp = post_json(client, "/api/v1/transactions/reverse",
                         {"rrn": "RRN_DOES_NOT_EXIST"})
        assert resp.status_code == 422

    def test_advice_endpoint_returns_200(self, client):
        txn = _make_approved_txn()
        resp = post_json(client, f"/api/v1/transactions/{txn.id}/reverse/advice", {})
        assert resp.status_code == 200

    def test_advice_always_200_even_when_already_reversed(self, client):
        txn = _make_approved_txn()
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        resp2 = post_json(client, f"/api/v1/transactions/{txn.id}/reverse/advice", {})
        assert resp2.status_code == 200

    def test_reversed_status_in_transaction_detail(self, client):
        txn = _make_approved_txn()
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        detail = client.get(f"/api/v1/transactions/{txn.id}").get_json()
        assert detail["status"] == "REVERSED"

    def test_reversed_at_field_present(self, client):
        txn = _make_approved_txn()
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        detail = client.get(f"/api/v1/transactions/{txn.id}").get_json()
        assert detail["reversed_at"] is not None

    def test_stats_count_reversed(self, client):
        txn = _make_approved_txn()
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        stats = client.get("/api/v1/stats").get_json()
        assert stats["transaction_stats"]["reversed"] >= 1

    def test_reverse_invalid_amount_returns_400(self, client):
        txn = _make_approved_txn()
        resp = post_json(client, f"/api/v1/transactions/{txn.id}/reverse",
                         {"amount": "not_a_number"})
        assert resp.status_code == 400

    def test_reverse_balance_restored_visible_in_stats(self, client):
        txn = _make_approved_txn(amount=5000)
        card_before = card_db.get_card(PAN_ACTIVE)
        bal_after_auth = card_before.balance
        post_json(client, f"/api/v1/transactions/{txn.id}/reverse", {})
        assert card_before.balance == bal_after_auth + 5000


# ─────────────────────────────────────────────────────────────────────────────
# Tests : Interface TCP — MTI 0400 / 0420
# ─────────────────────────────────────────────────────────────────────────────

class TestReversalTCP:
    def setup_method(self):
        _clear_txn_log(PAN_ACTIVE)
        _reset_card()

    def test_0400_reversal_accepted(self, tcp_server):
        txn = _make_approved_txn(amount=5000)
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {
                "37": txn.rrn,
                "41": "TERM_REV1",
                "49": "978",
            }
        })
        assert resp["mti"] == "0410"
        assert resp["accepted"] is True
        assert resp["response_code"] == "00"

    def test_0400_reversal_restores_balance(self, tcp_server):
        card = card_db.get_card(PAN_ACTIVE)
        txn = _make_approved_txn(amount=5000)
        bal_after = card.balance
        tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        assert card.balance == bal_after + 5000

    def test_0400_partial_reversal(self, tcp_server):
        txn = _make_approved_txn(amount=10000)
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {
                "37": txn.rrn,
                "95": "000000003000" + "0" * 30,
                "49": "978",
            }
        })
        assert resp["mti"] == "0410"
        assert resp["accepted"] is True
        assert resp["reversal_amount"] == 3000

    def test_0400_not_found_returns_25(self, tcp_server):
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {
                "37": "RRN_NOT_EXISTING",
                "49": "978",
            }
        })
        assert resp["mti"] == "0410"
        assert resp["accepted"] is False
        assert resp["response_code"] == "25"

    def test_0400_double_reversal_rejected(self, tcp_server):
        txn = _make_approved_txn(amount=5000)
        tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        resp2 = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        assert resp2["accepted"] is False
        assert resp2["response_code"] == "56"

    def test_0420_advice_accepted(self, tcp_server):
        txn = _make_approved_txn(amount=5000)
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0420",
            "fields": {
                "37": txn.rrn,
                "49": "978",
            }
        })
        assert resp["mti"] == "0430"
        assert resp["accepted"] is True
        assert resp["is_advice"] is True

    def test_0420_idempotent_after_0400(self, tcp_server):
        txn = _make_approved_txn(amount=5000)
        tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0420",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        assert resp["mti"] == "0430"
        assert resp["accepted"] is True

    def test_0400_response_has_pan_masked(self, tcp_server):
        txn = _make_approved_txn(amount=5000)
        resp = tcp_roundtrip(TEST_TCP_PORT, {
            "mti": "0400",
            "fields": {"37": txn.rrn, "49": "978"}
        })
        if resp.get("accepted"):
            assert "*" in resp.get("pan_masked", "")
