"""
Tests — C5 Moteur de scoring risque enrichi
Couvre : score_transaction (tous facteurs), niveaux, décisions,
         recommandations, endpoints REST.
"""
import pytest
from emv.risk_scoring import (
    score_transaction,
    _score_amount, _score_velocity, _score_mcc,
    _score_contactless, _score_time,
    HIGH_RISK_MCC, LOW_RISK_MCC,
)

PAN = "4111111111111111"


# ── _score_amount ─────────────────────────────────────────────────────────────

class TestScoreAmount:
    def test_zero_amount(self):
        s, d = _score_amount(0)
        assert s == 0

    def test_micro(self):
        s, d = _score_amount(500)
        assert s == 0

    def test_low(self):
        s, d = _score_amount(3000)
        assert s == 5

    def test_medium(self):
        s, d = _score_amount(15000)
        assert s == 10

    def test_high(self):
        s, d = _score_amount(50000)
        assert s == 20

    def test_very_high(self):
        s, d = _score_amount(200000)
        assert s == 25

    def test_critical(self):
        s, d = _score_amount(1000000)
        assert s == 30

    def test_description_non_empty(self):
        s, d = _score_amount(5000)
        assert len(d) > 0


# ── _score_velocity ───────────────────────────────────────────────────────────

class TestScoreVelocity:
    def test_first_transaction(self):
        s, d = _score_velocity(0, 0)
        assert s == 0

    def test_moderate_daily(self):
        s, d = _score_velocity(5, 0)
        assert s == 6

    def test_high_daily(self):
        s, d = _score_velocity(12, 0)
        assert s == 12

    def test_critical_daily(self):
        s, d = _score_velocity(25, 0)
        assert s == 20

    def test_hourly_burst(self):
        s1, _ = _score_velocity(0, 0)
        s2, _ = _score_velocity(0, 6)
        assert s2 > s1

    def test_max_capped_at_25(self):
        s, _ = _score_velocity(100, 100)
        assert s <= 25


# ── _score_mcc ────────────────────────────────────────────────────────────────

class TestScoreMcc:
    def test_no_mcc(self):
        s, d = _score_mcc(None)
        assert s == 5
        assert "absent" in d.lower()

    def test_high_risk_mcc_casino(self):
        s, d = _score_mcc("7995")
        assert s == 20

    def test_high_risk_mcc_crypto(self):
        s, d = _score_mcc("6050")
        assert s == 20

    def test_low_risk_mcc_supermarket(self):
        s, d = _score_mcc("5411")
        assert s == 0

    def test_standard_mcc(self):
        s, d = _score_mcc("5999")
        assert 0 <= s <= 20

    def test_unknown_mcc(self):
        s, d = _score_mcc("9999")
        assert s == 5


# ── _score_contactless ────────────────────────────────────────────────────────

class TestScoreContactless:
    def test_contact_transaction(self):
        s, d = _score_contactless(False, 0, 0)
        assert s == 0

    def test_contactless_base_score(self):
        s, d = _score_contactless(True, 0, 0)
        assert s >= 3

    def test_high_cumul_adds_score(self):
        s1, _ = _score_contactless(True, 1000, 0)
        s2, _ = _score_contactless(True, 12000, 0)
        assert s2 > s1

    def test_many_consecutive_adds_score(self):
        s1, _ = _score_contactless(True, 0, 0)
        s2, _ = _score_contactless(True, 0, 5)
        assert s2 > s1

    def test_max_capped_at_15(self):
        s, _ = _score_contactless(True, 100000, 100)
        assert s <= 15


# ── _score_time ────────────────────────────────────────────────────────────────

class TestScoreTime:
    def test_daytime_zero(self):
        s, d = _score_time(10)
        assert s == 0

    def test_midnight_max(self):
        s, d = _score_time(2)
        assert s == 10

    def test_early_morning(self):
        s, d = _score_time(5)
        assert s == 5

    def test_late_evening(self):
        s, d = _score_time(23)
        assert s == 3


# ── score_transaction ─────────────────────────────────────────────────────────

class TestScoreTransaction:
    def test_returns_dict(self):
        r = score_transaction(PAN, 1000)
        assert "score" in r
        assert "level" in r
        assert "decision" in r
        assert "factors" in r

    def test_score_range(self):
        r = score_transaction(PAN, 1000)
        assert 0 <= r["score"] <= 100

    def test_low_risk_scenario(self):
        r = score_transaction(PAN, 500, mcc="5411", is_contactless=False,
                               daily_count=0, hour=12)
        assert r["level"] == "LOW"
        assert r["decision"] == "ALLOW"

    def test_high_risk_scenario(self):
        r = score_transaction(PAN, 1000000, mcc="7995", is_contactless=True,
                               contactless_cumul=15000, consecutive_offline=5,
                               daily_count=20, hour=2)
        assert r["level"] in ("HIGH", "CRITICAL")
        assert r["decision"] in ("CHALLENGE", "BLOCK")

    def test_critical_triggers_block(self):
        r = score_transaction(PAN, 1000000, mcc="7995",
                               daily_count=25, hour=2,
                               contactless_cumul=14000, consecutive_offline=5,
                               hourly_count=8)
        assert r["decision"] == "BLOCK"
        assert r["level"] == "CRITICAL"

    def test_factors_keys_present(self):
        r = score_transaction(PAN, 5000)
        factors = r["factors"]
        assert "amount" in factors
        assert "velocity" in factors
        assert "mcc" in factors
        assert "contactless" in factors
        assert "time" in factors

    def test_factor_score_max_respected(self):
        r = score_transaction(PAN, 1000000, mcc="7995",
                               daily_count=50, hourly_count=20,
                               is_contactless=True, contactless_cumul=20000,
                               consecutive_offline=10, hour=2)
        factors = r["factors"]
        assert factors["amount"]["score"] <= 30
        assert factors["velocity"]["score"] <= 25
        assert factors["mcc"]["score"] <= 20
        assert factors["contactless"]["score"] <= 15
        assert factors["time"]["score"] <= 10

    def test_recommendations_non_empty(self):
        r = score_transaction(PAN, 1000)
        assert len(r["recommendations"]) > 0

    def test_pan_masked(self):
        r = score_transaction(PAN, 1000)
        assert "pan_masked" in r
        assert r["pan_masked"].endswith("1111")
        assert "111111111" not in r["pan_masked"]

    def test_inputs_present(self):
        r = score_transaction(PAN, 5000, currency="978", mcc="5411")
        assert r["inputs"]["amount"] == 5000
        assert r["inputs"]["mcc"] == "5411"

    def test_level_low(self):
        r = score_transaction(PAN, 100, daily_count=0, hour=12)
        assert r["level"] == "LOW"

    def test_level_medium(self):
        r = score_transaction(PAN, 30000, mcc="5732", daily_count=6, hour=12)
        assert r["level"] in ("MEDIUM", "HIGH")

    def test_color_present(self):
        r = score_transaction(PAN, 5000)
        assert "color" in r
        assert r["color"].startswith("#")


# ── Endpoints REST ────────────────────────────────────────────────────────────

class TestRiskScoreEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client

    def test_post_risk_score(self):
        r = self.client.post("/api/v1/risk-score",
                             json={"pan": "4111111111111111", "amount": 5000})
        assert r.status_code == 200
        data = r.get_json()
        assert "score" in data
        assert "level" in data
        assert "decision" in data

    def test_post_risk_score_missing_pan(self):
        r = self.client.post("/api/v1/risk-score", json={"amount": 5000})
        assert r.status_code == 400

    def test_post_risk_score_invalid_amount(self):
        r = self.client.post("/api/v1/risk-score",
                             json={"pan": "4111111111111111", "amount": "abc"})
        assert r.status_code == 400

    def test_post_risk_score_with_mcc(self):
        r = self.client.post("/api/v1/risk-score",
                             json={"pan": "4111111111111111",
                                   "amount": 5000, "mcc": "7995"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["factors"]["mcc"]["score"] == 20

    def test_post_risk_score_contactless_params(self):
        r = self.client.post("/api/v1/risk-score",
                             json={"pan": "4111111111111111",
                                   "amount": 5000,
                                   "is_contactless": True,
                                   "contactless_cumul": 12000})
        assert r.status_code == 200
        data = r.get_json()
        assert data["factors"]["contactless"]["score"] > 0

    def test_get_txn_risk_score_not_found(self):
        r = self.client.get("/api/v1/transactions/nonexistent-id/risk-score")
        assert r.status_code == 404
