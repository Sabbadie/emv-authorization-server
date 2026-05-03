"""
Tests — E4 Préautorisation + capture différée
Couvre : create_preauth, capture (total/partiel), cancel_preauth,
         get_preauth, get_all_preauths, endpoints REST.
"""
import pytest
from emv.preauth import (
    create_preauth, capture, cancel_preauth,
    get_preauth, get_all_preauths, count_preauths,
    _preauth_store, _preauth_index,
)

PAN = "4111111111111111"


def _clean():
    _preauth_store.clear()
    _preauth_index.clear()


# ── create_preauth ────────────────────────────────────────────────────────────

class TestCreatePreauth:
    def setup_method(self):
        _clean()

    def test_success(self):
        r = create_preauth(PAN, 10000, "978")
        assert r.success is True
        assert r.preauth is not None

    def test_returned_dict_has_fields(self):
        r = create_preauth(PAN, 10000, "978", terminal_id="TERM01")
        d = r.preauth.to_dict()
        assert d["status"] == "PENDING"
        assert d["authorized_amount"] == 10000
        assert "****" in d["pan"]
        assert d["authorized_formatted"] == "100.00"
        assert d["remaining_amount"] == 10000

    def test_invalid_amount(self):
        r = create_preauth(PAN, 0, "978")
        assert r.success is False
        assert r.error_code == "13"

    def test_negative_amount(self):
        r = create_preauth(PAN, -100, "978")
        assert r.success is False

    def test_mti_is_0100(self):
        r = create_preauth(PAN, 5000, "978")
        assert r.preauth.mti == "0100"

    def test_rrn_starts_with_pa(self):
        r = create_preauth(PAN, 5000, "978")
        assert r.preauth.rrn.startswith("PA")

    def test_pan_with_spaces(self):
        r = create_preauth("4111 1111 1111 1111", 5000, "978")
        assert r.success is True

    def test_multiple_preauths_different_ids(self):
        r1 = create_preauth(PAN, 5000, "978")
        r2 = create_preauth(PAN, 5000, "978")
        assert r1.preauth.id != r2.preauth.id

    def test_with_all_optional_fields(self):
        r = create_preauth(PAN, 10000, "978",
                           terminal_id="TERM01",
                           merchant_id="MERCH001",
                           merchant_name="Hôtel Paris",
                           original_txn_id="some-uuid",
                           expiry_hours=72,
                           notes="Chambre 101")
        d = r.preauth.to_dict()
        assert d["terminal_id"] == "TERM01"
        assert d["expiry_hours"] == 72
        assert d["notes"] == "Chambre 101"

    def test_stored_in_store(self):
        r = create_preauth(PAN, 5000, "978")
        assert r.preauth.id in _preauth_store


# ── capture ───────────────────────────────────────────────────────────────────

class TestCapture:
    def setup_method(self):
        _clean()

    def _make(self, amount=10000):
        return create_preauth(PAN, amount, "978").preauth

    def test_full_capture(self):
        pa = self._make(10000)
        r = capture(pa.id)
        assert r.success is True
        assert r.preauth.status == "CAPTURED"
        assert r.preauth.captured_amount == 10000

    def test_partial_capture(self):
        pa = self._make(10000)
        r = capture(pa.id, capture_amount=7000)
        assert r.success is True
        assert r.preauth.status == "PARTIAL"
        assert r.preauth.captured_amount == 7000
        assert r.preauth.remaining_amount == 3000

    def test_capture_amount_in_result(self):
        pa = self._make(10000)
        r = capture(pa.id, capture_amount=5000)
        assert r.captured_amount == 5000
        assert r.preauth.captured_formatted == "50.00"

    def test_capture_exceeds_authorized(self):
        pa = self._make(10000)
        r = capture(pa.id, capture_amount=15000)
        assert r.success is False
        assert r.error_code == "61"

    def test_capture_zero_amount(self):
        pa = self._make(10000)
        r = capture(pa.id, capture_amount=0)
        assert r.success is False
        assert r.error_code == "13"

    def test_capture_nonexistent_id(self):
        r = capture("nonexistent-id")
        assert r.success is False
        assert r.error_code == "25"

    def test_capture_after_capture_fails(self):
        pa = self._make(10000)
        capture(pa.id)
        r = capture(pa.id)
        assert r.success is False
        assert r.error_code == "40"

    def test_capture_after_cancel_fails(self):
        pa = self._make(10000)
        cancel_preauth(pa.id)
        r = capture(pa.id)
        assert r.success is False

    def test_mti_after_capture_is_0200(self):
        pa = self._make(10000)
        capture(pa.id)
        assert pa.mti == "0200"

    def test_capture_rrn_set(self):
        pa = self._make(10000)
        capture(pa.id)
        assert pa.capture_rrn is not None

    def test_captured_at_set(self):
        pa = self._make(10000)
        capture(pa.id)
        assert pa.captured_at is not None


# ── cancel_preauth ────────────────────────────────────────────────────────────

class TestCancelPreauth:
    def setup_method(self):
        _clean()

    def _make(self):
        return create_preauth(PAN, 5000, "978").preauth

    def test_cancel_pending(self):
        pa = self._make()
        r = cancel_preauth(pa.id)
        assert r.success is True
        assert r.preauth.status == "CANCELLED"

    def test_cancel_nonexistent(self):
        r = cancel_preauth("bad-id")
        assert r.success is False
        assert r.error_code == "25"

    def test_cancel_already_captured(self):
        pa = self._make()
        capture(pa.id)
        r = cancel_preauth(pa.id)
        assert r.success is False
        assert r.error_code == "40"

    def test_cancel_reason_appended(self):
        pa = self._make()
        cancel_preauth(pa.id, reason="Client no-show")
        assert "Client no-show" in pa.notes

    def test_mti_after_cancel_is_0400(self):
        pa = self._make()
        cancel_preauth(pa.id)
        assert pa.mti == "0400"

    def test_cancelled_at_set(self):
        pa = self._make()
        cancel_preauth(pa.id)
        assert pa.cancelled_at is not None


# ── get_preauth / get_all_preauths ────────────────────────────────────────────

class TestGetPreauths:
    def setup_method(self):
        _clean()

    def test_get_existing(self):
        r = create_preauth(PAN, 5000, "978")
        pa = get_preauth(r.preauth.id)
        assert pa is not None
        assert pa.id == r.preauth.id

    def test_get_nonexistent(self):
        assert get_preauth("bad-id") is None

    def test_get_all_empty(self):
        assert get_all_preauths() == []

    def test_get_all_returns_all(self):
        create_preauth(PAN, 5000, "978")
        create_preauth(PAN, 8000, "978")
        all_pa = get_all_preauths()
        assert len(all_pa) == 2

    def test_get_all_filter_by_status(self):
        r1 = create_preauth(PAN, 5000, "978")
        r2 = create_preauth(PAN, 8000, "978")
        capture(r1.preauth.id)
        pending = get_all_preauths(status="PENDING")
        captured = get_all_preauths(status="CAPTURED")
        assert len(pending) == 1
        assert len(captured) == 1

    def test_count_preauths(self):
        create_preauth(PAN, 5000, "978")
        create_preauth(PAN, 5000, "978")
        assert count_preauths() == 2


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestPreauthEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        _clean()

    def test_create_preauth_endpoint(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 10000, "currency": "978"})
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True
        assert data["preauth"]["status"] == "PENDING"

    def test_create_missing_pan(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"amount": 10000})
        assert r.status_code == 400

    def test_create_zero_amount(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111", "amount": 0})
        assert r.status_code == 400

    def test_list_preauths(self):
        self.client.post("/api/v1/preauthorizations",
                         json={"pan": "4111111111111111",
                               "amount": 5000, "currency": "978"})
        r = self.client.get("/api/v1/preauthorizations")
        assert r.status_code == 200
        data = r.get_json()
        assert "preauthorizations" in data
        assert data["total"] >= 1

    def test_get_preauth_detail(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 5000, "currency": "978"})
        pa_id = r.get_json()["preauth"]["id"]
        r2 = self.client.get(f"/api/v1/preauthorizations/{pa_id}")
        assert r2.status_code == 200
        assert r2.get_json()["id"] == pa_id

    def test_get_preauth_not_found(self):
        r = self.client.get("/api/v1/preauthorizations/nonexistent")
        assert r.status_code == 404

    def test_capture_endpoint(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 10000, "currency": "978"})
        pa_id = r.get_json()["preauth"]["id"]
        r2 = self.client.post(f"/api/v1/preauthorizations/{pa_id}/capture", json={})
        assert r2.status_code == 200
        assert r2.get_json()["success"] is True

    def test_partial_capture_endpoint(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 10000, "currency": "978"})
        pa_id = r.get_json()["preauth"]["id"]
        r2 = self.client.post(f"/api/v1/preauthorizations/{pa_id}/capture",
                              json={"capture_amount": 7000})
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["preauth"]["status"] == "PARTIAL"

    def test_cancel_endpoint(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 10000, "currency": "978"})
        pa_id = r.get_json()["preauth"]["id"]
        r2 = self.client.post(f"/api/v1/preauthorizations/{pa_id}/cancel",
                              json={"reason": "Test"})
        assert r2.status_code == 200
        assert r2.get_json()["success"] is True

    def test_cancel_then_capture_fails(self):
        r = self.client.post("/api/v1/preauthorizations",
                             json={"pan": "4111111111111111",
                                   "amount": 10000, "currency": "978"})
        pa_id = r.get_json()["preauth"]["id"]
        self.client.post(f"/api/v1/preauthorizations/{pa_id}/cancel", json={})
        r2 = self.client.post(f"/api/v1/preauthorizations/{pa_id}/capture", json={})
        assert r2.status_code == 400
