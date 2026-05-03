"""
Tests unitaires — models/transaction.py
Couvre : Transaction (_generate_rrn, approve, decline, error, to_dict),
         TransactionLog (add, get, get_by_pan, get_all, get_stats)
"""

import pytest
import uuid
from models.transaction import Transaction, TransactionLog, TransactionStatus


def make_txn(pan="4111111111111111", amount=5000, status=None):
    txn = Transaction(
        pan=pan, amount=amount, currency="978",
        transaction_type="00",
        terminal_id="TERM0001",
        merchant_id="MERCH001",
        merchant_name="TEST SHOP",
        pos_entry_mode="051",
    )
    if status == "approved":
        txn.approve("123456")
    elif status == "declined":
        txn.decline("51", "Insufficient funds")
    elif status == "error":
        txn.error("System error")
    return txn


def make_log_with_txns(*txns):
    log = TransactionLog()
    for t in txns:
        log.add(t)
    return log


class TestTransactionInit:
    def test_id_is_uuid(self):
        txn = make_txn()
        uuid.UUID(txn.id)

    def test_status_pending(self):
        txn = make_txn()
        assert txn.status == TransactionStatus.PENDING

    def test_pan_stored(self):
        txn = make_txn(pan="4111111111111111")
        assert txn.pan == "4111111111111111"

    def test_amount_stored(self):
        txn = make_txn(amount=9999)
        assert txn.amount == 9999

    def test_rrn_not_empty(self):
        txn = make_txn()
        assert txn.rrn
        assert len(txn.rrn) >= 8

    def test_created_at_not_empty(self):
        txn = make_txn()
        assert txn.created_at

    def test_processed_at_none(self):
        txn = make_txn()
        assert txn.processed_at is None

    def test_response_code_none(self):
        txn = make_txn()
        assert txn.response_code is None

    def test_cb_fields_default_false(self):
        txn = make_txn()
        assert txn.cb_is_contactless is False

    def test_two_txns_have_different_ids(self):
        t1, t2 = make_txn(), make_txn()
        assert t1.id != t2.id

    def test_two_txns_have_different_rrns(self):
        t1, t2 = make_txn(), make_txn()
        assert t1.rrn != t2.rrn


class TestTransactionApprove:
    def test_status_approved(self):
        txn = make_txn()
        txn.approve("123456")
        assert txn.status == TransactionStatus.APPROVED

    def test_response_code_00(self):
        txn = make_txn()
        txn.approve("123456")
        assert txn.response_code == "00"

    def test_auth_code_stored(self):
        txn = make_txn()
        txn.approve("ABCDEF")
        assert txn.auth_code == "ABCDEF"

    def test_processed_at_set(self):
        txn = make_txn()
        txn.approve("123456")
        assert txn.processed_at is not None

    def test_arpc_stored(self):
        txn = make_txn()
        txn.approve("123456", arpc="AABBCCDD11223344")
        assert txn.arpc == "AABBCCDD11223344"

    def test_issuer_auth_data_stored(self):
        txn = make_txn()
        txn.approve("123456", issuer_auth_data="AABBCCDD11223344AABB")
        assert txn.issuer_auth_data == "AABBCCDD11223344AABB"

    def test_decline_reason_not_set(self):
        txn = make_txn()
        txn.approve("123456")
        assert txn.decline_reason is None


class TestTransactionDecline:
    def test_status_declined(self):
        txn = make_txn()
        txn.decline("51")
        assert txn.status == TransactionStatus.DECLINED

    def test_response_code_set(self):
        txn = make_txn()
        txn.decline("51")
        assert txn.response_code == "51"

    def test_reason_stored(self):
        txn = make_txn()
        txn.decline("51", "Insufficient funds")
        assert txn.decline_reason == "Insufficient funds"

    def test_processed_at_set(self):
        txn = make_txn()
        txn.decline("51")
        assert txn.processed_at is not None

    def test_reason_optional(self):
        txn = make_txn()
        txn.decline("14")
        assert txn.decline_reason is None

    @pytest.mark.parametrize("code", ["00", "05", "14", "51", "54", "62", "91"])
    def test_various_response_codes(self, code):
        txn = make_txn()
        txn.decline(code)
        assert txn.response_code == code


class TestTransactionError:
    def test_status_error(self):
        txn = make_txn()
        txn.error("System failure")
        assert txn.status == TransactionStatus.ERROR

    def test_response_code_96(self):
        txn = make_txn()
        txn.error("System failure")
        assert txn.response_code == "96"

    def test_reason_stored(self):
        txn = make_txn()
        txn.error("Parse error")
        assert txn.decline_reason == "Parse error"

    def test_processed_at_set(self):
        txn = make_txn()
        txn.error("X")
        assert txn.processed_at is not None


class TestTransactionToDict:
    def test_masked_pan(self):
        txn = make_txn(pan="4111111111111111")
        d = txn.to_dict(masked=True)
        assert d["pan"].endswith("1111")
        assert "*" in d["pan"]

    def test_unmasked_pan(self):
        txn = make_txn(pan="4111111111111111")
        d = txn.to_dict(masked=False)
        assert d["pan"] == "4111111111111111"

    def test_amount_formatted(self):
        txn = make_txn(amount=5000)
        assert txn.to_dict()["amount_formatted"] == "50.00"

    def test_amount_formatted_zero_cents(self):
        txn = make_txn(amount=10000)
        assert txn.to_dict()["amount_formatted"] == "100.00"

    def test_amount_formatted_odd_cents(self):
        txn = make_txn(amount=1)
        assert txn.to_dict()["amount_formatted"] == "0.01"

    def test_contains_required_keys(self):
        txn = make_txn()
        d = txn.to_dict()
        required = [
            "id", "rrn", "pan", "amount", "amount_formatted",
            "currency", "transaction_type", "terminal_id",
            "merchant_id", "merchant_name", "status",
            "response_code", "created_at", "processed_at",
            "amount_tier", "risk_level", "auth_path",
            "cb_scheme", "cb_brand", "cb_is_contactless",
        ]
        for key in required:
            assert key in d, f"Clé manquante : {key}"

    def test_status_reflected(self):
        txn = make_txn(status="approved")
        assert txn.to_dict()["status"] == "APPROVED"

    def test_response_code_reflected(self):
        txn = make_txn(status="declined")
        assert txn.to_dict()["response_code"] == "51"


class TestTransactionLog:
    def test_add_and_get_by_id(self):
        log = TransactionLog()
        txn = make_txn()
        log.add(txn)
        assert log.get(txn.id) is txn

    def test_get_missing_returns_none(self):
        log = TransactionLog()
        assert log.get("nonexistent-id") is None

    def test_get_by_pan(self):
        log = TransactionLog()
        pan = "4111111111111111"
        t1, t2 = make_txn(pan=pan), make_txn(pan=pan)
        log.add(t1)
        log.add(t2)
        results = log.get_by_pan(pan)
        ids = {t.id for t in results}
        assert t1.id in ids
        assert t2.id in ids

    def test_get_by_pan_different_pan_excluded(self):
        log = TransactionLog()
        log.add(make_txn(pan="4111111111111111"))
        log.add(make_txn(pan="5500000000000004"))
        results = log.get_by_pan("4111111111111111")
        assert all(t.pan == "4111111111111111" for t in results)

    def test_get_by_pan_limit_respected(self):
        log = TransactionLog()
        for _ in range(10):
            log.add(make_txn(pan="4111111111111111"))
        results = log.get_by_pan("4111111111111111", limit=3)
        assert len(results) <= 3

    def test_get_by_pan_unknown_pan(self):
        log = TransactionLog()
        results = log.get_by_pan("0000000000000000")
        assert results == []

    def test_get_all_returns_all(self):
        log = TransactionLog()
        for _ in range(5):
            log.add(make_txn())
        results = log.get_all(limit=100, offset=0)
        assert len(results) == 5

    def test_get_all_filter_status_approved(self):
        log = TransactionLog()
        log.add(make_txn(status="approved"))
        log.add(make_txn(status="declined"))
        log.add(make_txn(status="approved"))
        results = log.get_all(status="APPROVED")
        assert all(t.status == "APPROVED" for t in results)
        assert len(results) == 2

    def test_get_all_filter_status_declined(self):
        log = TransactionLog()
        log.add(make_txn(status="approved"))
        log.add(make_txn(status="declined"))
        results = log.get_all(status="DECLINED")
        assert all(t.status == "DECLINED" for t in results)

    def test_get_all_filter_tier(self):
        log = TransactionLog()
        t1 = make_txn()
        t1.amount_tier = "STANDARD"
        t2 = make_txn()
        t2.amount_tier = "MICRO"
        log.add(t1)
        log.add(t2)
        results = log.get_all(tier="STANDARD")
        assert all(t.amount_tier == "STANDARD" for t in results)

    def test_get_all_sorted_newest_first(self):
        log = TransactionLog()
        t1, t2, t3 = make_txn(), make_txn(), make_txn()
        log.add(t1)
        log.add(t2)
        log.add(t3)
        results = log.get_all()
        dates = [t.created_at for t in results]
        assert dates == sorted(dates, reverse=True)

    def test_get_all_pagination_offset(self):
        log = TransactionLog()
        for _ in range(10):
            log.add(make_txn())
        page1 = log.get_all(limit=5, offset=0)
        page2 = log.get_all(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {t.id for t in page1}
        ids2 = {t.id for t in page2}
        assert ids1.isdisjoint(ids2)

    def test_get_all_limit_respected(self):
        log = TransactionLog()
        for _ in range(20):
            log.add(make_txn())
        results = log.get_all(limit=7, offset=0)
        assert len(results) == 7


class TestTransactionLogStats:
    def test_empty_log_zeros(self):
        log = TransactionLog()
        stats = log.get_stats()
        assert stats["total"] == 0
        assert stats["approved"] == 0
        assert stats["declined"] == 0
        assert stats["errors"] == 0

    def test_approval_rate_empty(self):
        log = TransactionLog()
        assert log.get_stats()["approval_rate"] == "0.0%"

    def test_counts_correct(self):
        log = TransactionLog()
        log.add(make_txn(status="approved"))
        log.add(make_txn(status="approved"))
        log.add(make_txn(status="declined"))
        log.add(make_txn(status="error"))
        s = log.get_stats()
        assert s["total"] == 4
        assert s["approved"] == 2
        assert s["declined"] == 1
        assert s["errors"] == 1

    def test_approval_rate_calculation(self):
        log = TransactionLog()
        for _ in range(3):
            log.add(make_txn(status="approved"))
        for _ in range(1):
            log.add(make_txn(status="declined"))
        stats = log.get_stats()
        assert stats["approval_rate"] == "75.0%"

    def test_total_approved_amount(self):
        log = TransactionLog()
        t1 = make_txn(amount=5000, status="approved")
        t2 = make_txn(amount=3000, status="approved")
        t3 = make_txn(amount=2000, status="declined")
        log.add(t1)
        log.add(t2)
        log.add(t3)
        stats = log.get_stats()
        assert stats["total_approved_amount"] == 8000

    def test_by_tier_groups(self):
        log = TransactionLog()
        t1, t2, t3 = make_txn(), make_txn(), make_txn()
        t1.amount_tier = "STANDARD"
        t2.amount_tier = "STANDARD"
        t3.amount_tier = "MICRO"
        log.add(t1)
        log.add(t2)
        log.add(t3)
        stats = log.get_stats()
        assert stats["by_tier"]["STANDARD"] == 2
        assert stats["by_tier"]["MICRO"] == 1

    def test_by_auth_path(self):
        log = TransactionLog()
        for path in ["ONLINE", "ONLINE", "OFFLINE"]:
            t = make_txn()
            t.auth_path = path
            log.add(t)
        stats = log.get_stats()
        assert stats["by_auth_path"]["ONLINE"] == 2
        assert stats["by_auth_path"]["OFFLINE"] == 1

    def test_by_cb_scheme(self):
        log = TransactionLog()
        for scheme in ["VISA", "MC", "VISA"]:
            t = make_txn()
            t.cb_scheme = scheme
            log.add(t)
        stats = log.get_stats()
        assert stats["by_cb_scheme"]["VISA"] == 2
        assert stats["by_cb_scheme"]["MC"] == 1

    def test_stats_keys_present(self):
        log = TransactionLog()
        stats = log.get_stats()
        required = ["total", "approved", "declined", "errors", "approval_rate",
                    "total_approved_amount", "by_tier", "by_auth_path",
                    "by_risk_level", "by_cb_scheme"]
        for k in required:
            assert k in stats, f"Clé manquante : {k}"

    def test_total_amount_formatted(self):
        log = TransactionLog()
        t = make_txn(amount=10000, status="approved")
        log.add(t)
        stats = log.get_stats()
        assert stats["total_approved_amount_formatted"] == "100.00"
