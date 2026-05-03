"""
Tests — E6 Disputes / Chargebacks
Couvre : create_chargeback, reverse_chargeback, resolve_chargeback,
         get_chargeback, get_all_chargebacks, endpoints REST.
"""
import pytest
from emv.chargeback import (
    create_chargeback, reverse_chargeback, resolve_chargeback,
    get_chargeback, get_all_chargebacks, count_chargebacks,
    get_chargebacks_by_txn, CHARGEBACK_REASON_CODES,
    _chargeback_store, _cb_txn_index,
)
from models.transaction import Transaction, transaction_log, TransactionStatus


def _clean():
    _chargeback_store.clear()
    _cb_txn_index.clear()


def _make_approved_txn(pan="4111111111111111", amount=5000):
    """Crée et enregistre une transaction approuvée."""
    txn = Transaction(pan=pan, amount=amount, currency="978",
                      transaction_type="00")
    txn.approve("123456")
    transaction_log.add(txn)
    return txn


# ── create_chargeback ─────────────────────────────────────────────────────────

class TestCreateChargeback:
    def setup_method(self):
        _clean()

    def test_success(self):
        txn = _make_approved_txn()
        r = create_chargeback(txn.id, "CB01")
        assert r.success is True
        assert r.chargeback is not None

    def test_chargeback_fields(self):
        txn = _make_approved_txn(amount=10000)
        r = create_chargeback(txn.id, "CB01", notes="Test")
        cb = r.chargeback
        assert cb.status == "OPEN"
        assert cb.mti == "0620"
        assert cb.transaction_id == txn.id
        assert cb.reason_code == "CB01"
        assert cb.amount == 10000

    def test_partial_amount(self):
        txn = _make_approved_txn(amount=10000)
        r = create_chargeback(txn.id, "CB04", amount=3000)
        assert r.chargeback.amount == 3000

    def test_unknown_transaction(self):
        r = create_chargeback("nonexistent-id", "CB01")
        assert r.success is False
        assert r.error_code == "25"

    def test_unknown_reason_code(self):
        txn = _make_approved_txn()
        r = create_chargeback(txn.id, "CB99")
        assert r.success is False
        assert r.error_code == "30"

    def test_amount_exceeds_transaction(self):
        txn = _make_approved_txn(amount=5000)
        r = create_chargeback(txn.id, "CB01", amount=9999)
        assert r.success is False
        assert r.error_code == "13"

    def test_zero_amount(self):
        txn = _make_approved_txn(amount=5000)
        r = create_chargeback(txn.id, "CB01", amount=0)
        assert r.success is False

    def test_declined_txn_cannot_chargeback(self):
        txn = Transaction(pan="4111111111111111", amount=5000,
                          currency="978", transaction_type="00")
        txn.decline("51", "NSF")
        transaction_log.add(txn)
        r = create_chargeback(txn.id, "CB01")
        assert r.success is False
        assert r.error_code == "40"

    def test_rrn_starts_with_cb(self):
        txn = _make_approved_txn()
        r = create_chargeback(txn.id, "CB01")
        assert r.chargeback.rrn.startswith("CB")

    def test_logs_event_on_transaction(self):
        txn = _make_approved_txn()
        create_chargeback(txn.id, "CB01")
        stages = [e["stage"] for e in txn.events]
        assert "CHARGEBACK_OPENED" in stages

    def test_multiple_chargebacks_on_same_txn(self):
        txn = _make_approved_txn()
        create_chargeback(txn.id, "CB01")
        create_chargeback(txn.id, "CB02")
        cbs = get_chargebacks_by_txn(txn.id)
        assert len(cbs) == 2

    def test_all_reason_codes_valid(self):
        for code in CHARGEBACK_REASON_CODES:
            txn = _make_approved_txn()
            r = create_chargeback(txn.id, code)
            assert r.success is True, f"Failed for {code}"

    def test_initiated_by_field(self):
        txn = _make_approved_txn()
        r = create_chargeback(txn.id, "CB01", initiated_by="BANQUE")
        assert r.chargeback.initiated_by == "BANQUE"


# ── reverse_chargeback ────────────────────────────────────────────────────────

class TestReverseChargeback:
    def setup_method(self):
        _clean()

    def _make_open_cb(self):
        txn = _make_approved_txn()
        r = create_chargeback(txn.id, "CB01")
        return r.chargeback, txn

    def test_reverse_open(self):
        cb, _ = self._make_open_cb()
        r = reverse_chargeback(cb.id)
        assert r.success is True
        assert r.chargeback.status == "REVERSED"

    def test_mti_changes_to_0630(self):
        cb, _ = self._make_open_cb()
        reverse_chargeback(cb.id)
        assert cb.mti == "0630"

    def test_reversal_at_set(self):
        cb, _ = self._make_open_cb()
        reverse_chargeback(cb.id)
        assert cb.reversal_at is not None

    def test_nonexistent_chargeback(self):
        r = reverse_chargeback("bad-id")
        assert r.success is False
        assert r.error_code == "25"

    def test_already_reversed(self):
        cb, _ = self._make_open_cb()
        reverse_chargeback(cb.id)
        r = reverse_chargeback(cb.id)
        assert r.success is False
        assert r.error_code == "40"

    def test_logs_event_on_txn(self):
        cb, txn = self._make_open_cb()
        reverse_chargeback(cb.id)
        stages = [e["stage"] for e in txn.events]
        assert "CHARGEBACK_REVERSED" in stages

    def test_notes_appended(self):
        cb, _ = self._make_open_cb()
        reverse_chargeback(cb.id, notes="Accord commerçant")
        assert "Accord commerçant" in cb.notes


# ── resolve_chargeback ────────────────────────────────────────────────────────

class TestResolveChargeback:
    def setup_method(self):
        _clean()

    def _make_open_cb(self):
        txn = _make_approved_txn()
        return create_chargeback(txn.id, "CB01").chargeback

    def test_accept(self):
        cb = self._make_open_cb()
        r = resolve_chargeback(cb.id, "ACCEPTED")
        assert r.success is True
        assert r.chargeback.status == "ACCEPTED"

    def test_reject(self):
        cb = self._make_open_cb()
        r = resolve_chargeback(cb.id, "REJECTED")
        assert r.chargeback.status == "REJECTED"

    def test_arbitration(self):
        cb = self._make_open_cb()
        r = resolve_chargeback(cb.id, "ARBITRATION")
        assert r.chargeback.status == "ARBITRATION"

    def test_invalid_resolution(self):
        cb = self._make_open_cb()
        r = resolve_chargeback(cb.id, "INVALID")
        assert r.success is False
        assert r.error_code == "30"

    def test_resolved_at_set(self):
        cb = self._make_open_cb()
        resolve_chargeback(cb.id, "ACCEPTED")
        assert cb.resolved_at is not None

    def test_nonexistent(self):
        r = resolve_chargeback("bad-id", "ACCEPTED")
        assert r.success is False


# ── to_dict ───────────────────────────────────────────────────────────────────

class TestChargebackToDict:
    def setup_method(self):
        _clean()

    def test_to_dict_fields(self):
        txn = _make_approved_txn(amount=8000)
        cb = create_chargeback(txn.id, "CB05").chargeback
        d = cb.to_dict()
        assert d["mti"] == "0620"
        assert d["status"] == "OPEN"
        assert d["amount_formatted"] == "80.00"
        assert "status_label" in d
        assert d["reason_label"] != "Motif inconnu"


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestChargebackEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        _clean()
        # Create a known approved transaction
        txn = _make_approved_txn()
        self.txn_id = txn.id

    def test_get_reason_codes(self):
        r = self.client.get("/api/v1/chargebacks/reasons")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["reasons"]) == len(CHARGEBACK_REASON_CODES)

    def test_open_chargeback_endpoint(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={"reason_code": "CB01"})
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True
        assert data["chargeback"]["status"] == "OPEN"

    def test_open_missing_reason(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={})
        assert r.status_code == 400

    def test_open_invalid_reason(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={"reason_code": "INVALID"})
        assert r.status_code == 400

    def test_open_unknown_txn(self):
        r = self.client.post("/api/v1/transactions/nonexistent/chargeback",
                             json={"reason_code": "CB01"})
        assert r.status_code == 400

    def test_list_chargebacks_empty(self):
        r = self.client.get("/api/v1/chargebacks")
        assert r.status_code == 200
        data = r.get_json()
        assert "chargebacks" in data

    def test_list_chargebacks_after_create(self):
        self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                         json={"reason_code": "CB01"})
        r = self.client.get("/api/v1/chargebacks")
        data = r.get_json()
        assert data["total"] >= 1

    def test_get_chargeback_detail(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={"reason_code": "CB02"})
        cb_id = r.get_json()["chargeback"]["id"]
        r2 = self.client.get(f"/api/v1/chargebacks/{cb_id}")
        assert r2.status_code == 200
        assert r2.get_json()["id"] == cb_id

    def test_get_chargeback_not_found(self):
        r = self.client.get("/api/v1/chargebacks/nonexistent")
        assert r.status_code == 404

    def test_reverse_endpoint(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={"reason_code": "CB03"})
        cb_id = r.get_json()["chargeback"]["id"]
        r2 = self.client.post(f"/api/v1/chargebacks/{cb_id}/reverse", json={})
        assert r2.status_code == 200
        assert r2.get_json()["chargeback"]["status"] == "REVERSED"

    def test_resolve_endpoint(self):
        r = self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                             json={"reason_code": "CB04"})
        cb_id = r.get_json()["chargeback"]["id"]
        r2 = self.client.post(f"/api/v1/chargebacks/{cb_id}/resolve",
                              json={"resolution": "ACCEPTED"})
        assert r2.status_code == 200
        assert r2.get_json()["chargeback"]["status"] == "ACCEPTED"

    def test_get_txn_chargebacks(self):
        self.client.post(f"/api/v1/transactions/{self.txn_id}/chargeback",
                         json={"reason_code": "CB05"})
        r = self.client.get(f"/api/v1/transactions/{self.txn_id}/chargebacks")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] >= 1
