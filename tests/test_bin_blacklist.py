"""
Tests — E7 Blackliste BIN/PAN
Couvre : add_bin, remove_bin, add_pan, remove_pan, is_blacklisted,
         intégration authorize(), endpoints REST.
"""
import pytest
from emv.bin_blacklist import BINBlacklist


# ── Fixture isolée ────────────────────────────────────────────────────────────

@pytest.fixture
def bl():
    """Blackliste vierge pour chaque test."""
    return BINBlacklist.__new__(BINBlacklist).__init__() or _fresh_bl()


def _fresh_bl():
    b = BINBlacklist.__new__(BINBlacklist)
    b._bins = {}
    b._pans = {}
    return b


# ── add_bin ───────────────────────────────────────────────────────────────────

class TestAddBin:
    def test_add_bin_returns_entry(self):
        bl = _fresh_bl()
        e = bl.add_bin("411111", reason="Test")
        assert e["prefix"] == "411111"
        assert e["reason"] == "Test"
        assert "added_at" in e

    def test_add_bin_default_reason(self):
        bl = _fresh_bl()
        e = bl.add_bin("555555")
        assert "manuellement" in e["reason"].lower()

    def test_add_bin_stored(self):
        bl = _fresh_bl()
        bl.add_bin("123456")
        assert "123456" in bl._bins

    def test_add_bin_invalid_raises(self):
        bl = _fresh_bl()
        with pytest.raises(ValueError):
            bl.add_bin("ABCDEF")

    def test_add_bin_overwrite(self):
        bl = _fresh_bl()
        bl.add_bin("411111", reason="First")
        bl.add_bin("411111", reason="Second")
        assert bl._bins["411111"]["reason"] == "Second"


# ── remove_bin ────────────────────────────────────────────────────────────────

class TestRemoveBin:
    def test_remove_existing(self):
        bl = _fresh_bl()
        bl.add_bin("411111")
        removed = bl.remove_bin("411111")
        assert removed is True
        assert "411111" not in bl._bins

    def test_remove_nonexistent(self):
        bl = _fresh_bl()
        removed = bl.remove_bin("999999")
        assert removed is False

    def test_remove_lowercase_prefix(self):
        bl = _fresh_bl()
        bl.add_bin("411111")
        # Should normalize case
        removed = bl.remove_bin("411111")
        assert removed is True


# ── add_pan ───────────────────────────────────────────────────────────────────

class TestAddPan:
    def test_add_pan_masked(self):
        bl = _fresh_bl()
        e = bl.add_pan("4111111111111111")
        assert e["pan_masked"] == "************1111"

    def test_add_pan_with_spaces(self):
        bl = _fresh_bl()
        e = bl.add_pan("4111 1111 1111 1111")
        assert e["pan_masked"].endswith("1111")

    def test_add_pan_invalid_raises(self):
        bl = _fresh_bl()
        with pytest.raises(ValueError):
            bl.add_pan("123")   # trop court

    def test_add_pan_reason(self):
        bl = _fresh_bl()
        e = bl.add_pan("4111111111111111", reason="Fraude confirmée")
        assert e["reason"] == "Fraude confirmée"


# ── remove_pan ────────────────────────────────────────────────────────────────

class TestRemovePan:
    def test_remove_existing_pan(self):
        bl = _fresh_bl()
        bl.add_pan("4111111111111111")
        assert bl.remove_pan("4111111111111111") is True
        assert "4111111111111111" not in bl._pans

    def test_remove_nonexistent_pan(self):
        bl = _fresh_bl()
        assert bl.remove_pan("9999999999999999") is False


# ── is_blacklisted ────────────────────────────────────────────────────────────

class TestIsBlacklisted:
    def test_not_blacklisted(self):
        bl = _fresh_bl()
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is False
        assert t is None

    def test_blacklisted_by_pan(self):
        bl = _fresh_bl()
        bl.add_pan("4111111111111111", reason="Test PAN")
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is True
        assert t == "PAN"
        assert r == "Test PAN"

    def test_blacklisted_by_bin_prefix(self):
        bl = _fresh_bl()
        bl.add_bin("411111", reason="Test BIN")
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is True
        assert t == "BIN"
        assert r == "Test BIN"

    def test_pan_takes_precedence_over_bin(self):
        bl = _fresh_bl()
        bl.add_bin("411111", reason="BIN reason")
        bl.add_pan("4111111111111111", reason="PAN reason")
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is True
        assert t == "PAN"
        assert r == "PAN reason"

    def test_non_matching_bin(self):
        bl = _fresh_bl()
        bl.add_bin("555555")
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is False

    def test_longest_prefix_matched(self):
        bl = _fresh_bl()
        bl.add_bin("4", reason="Short")
        bl.add_bin("411111", reason="Long")
        blocked, t, r = bl.is_blacklisted("4111111111111111")
        assert blocked is True
        assert r == "Long"   # longest prefix wins

    def test_spaces_ignored_in_pan(self):
        bl = _fresh_bl()
        bl.add_pan("4111111111111111")
        blocked, t, r = bl.is_blacklisted("4111 1111 1111 1111")
        assert blocked is True


# ── get_all ───────────────────────────────────────────────────────────────────

class TestGetAll:
    def test_empty_returns_structure(self):
        bl = _fresh_bl()
        data = bl.get_all()
        assert "bins" in data
        assert "pans" in data
        assert data["total_bins"] == 0
        assert data["total_pans"] == 0

    def test_counts_accurate(self):
        bl = _fresh_bl()
        bl.add_bin("411111")
        bl.add_bin("555555")
        bl.add_pan("4000000000000001")
        data = bl.get_all()
        assert data["total_bins"] == 2
        assert data["total_pans"] == 1
        assert len(data["bins"]) == 2


# ── Intégration authorize() ───────────────────────────────────────────────────

class TestAuthorizeWithBlacklist:
    def setup_method(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        _bl.remove_bin("411111")
        _bl.remove_pan("4111111111111111")

    def teardown_method(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        _bl.remove_bin("411111")
        _bl.remove_pan("4111111111111111")

    def test_blacklisted_pan_declined(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        from emv.authorization import authorize
        _bl.add_pan("4111111111111111", reason="Test fraude")
        result = authorize("4111111111111111", 1000, "978", "00")
        assert result.approved is False
        assert result.response_code == "63"
        assert "blacklisté" in result.message.lower()

    def test_blacklisted_pan_logs_event(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        from emv.authorization import authorize
        _bl.add_pan("4111111111111111", reason="Test")
        result = authorize("4111111111111111", 1000, "978", "00")
        stages = [e["stage"] for e in result.transaction.events]
        assert "BIN_BLACKLIST_CHECK" in stages

    def test_non_blacklisted_pan_proceeds(self):
        from emv.authorization import authorize
        result = authorize("4111111111111111", 1000, "978", "00")
        assert result.response_code != "63"


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestBinBlacklistEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client
        # Clean up test entries
        from emv.bin_blacklist import bin_blacklist as _bl
        _bl.remove_bin("444444")
        _bl.remove_pan("4444444444444444")
        yield
        _bl.remove_bin("444444")
        _bl.remove_pan("4444444444444444")

    def test_get_blacklist(self):
        r = self.client.get("/api/v1/bin-blacklist")
        assert r.status_code == 200
        data = r.get_json()
        assert "bins" in data

    def test_add_bin_endpoint(self):
        r = self.client.post("/api/v1/bin-blacklist/bins",
                             json={"prefix": "444444", "reason": "Test"})
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True
        assert data["entry"]["prefix"] == "444444"

    def test_add_bin_missing_prefix(self):
        r = self.client.post("/api/v1/bin-blacklist/bins", json={})
        assert r.status_code == 400

    def test_remove_bin_endpoint(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        _bl.add_bin("444444", reason="Test")
        r = self.client.delete("/api/v1/bin-blacklist/bins/444444")
        assert r.status_code == 200

    def test_remove_bin_not_found(self):
        r = self.client.delete("/api/v1/bin-blacklist/bins/999888")
        assert r.status_code == 404

    def test_add_pan_endpoint(self):
        r = self.client.post("/api/v1/bin-blacklist/pans",
                             json={"pan": "4444444444444444", "reason": "Test"})
        assert r.status_code == 201

    def test_check_endpoint_not_blocked(self):
        r = self.client.post("/api/v1/bin-blacklist/check",
                             json={"pan": "4111111111111111"})
        assert r.status_code == 200
        data = r.get_json()
        assert "is_blacklisted" in data

    def test_check_endpoint_blocked(self):
        from emv.bin_blacklist import bin_blacklist as _bl
        _bl.add_pan("4444444444444444", reason="Test")
        r = self.client.post("/api/v1/bin-blacklist/check",
                             json={"pan": "4444444444444444"})
        data = r.get_json()
        assert data["is_blacklisted"] is True

    def test_check_missing_pan(self):
        r = self.client.post("/api/v1/bin-blacklist/check", json={})
        assert r.status_code == 400
