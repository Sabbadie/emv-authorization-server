"""
Tests E2 — 3-D Secure 2.x
"""
import pytest
from emv.threeds import (
    authenticate, submit_challenge, get_session, get_all_sessions,
    get_stats_3ds, AUTH_STATUS, ECI, LVP_LIMIT_EUR_CENTS,
    CHALLENGE_THRESHOLD,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

PAN = "4111111111111111"
AMOUNT_SMALL  = 2000   # 20 € → LVP
AMOUNT_MEDIUM = 10000  # 100 € → TRA possible
AMOUNT_LARGE  = 30000  # 300 € → challenge


# ── Tests authenticate ────────────────────────────────────────────────────────

class TestAuthenticate:

    def test_frictionless_low_value(self):
        res = authenticate(PAN, AMOUNT_SMALL, card_status="ACTIVE")
        assert res["status"] == AUTH_STATUS["AUTHENTICATED"]
        assert res["eci"] == ECI["AUTHENTICATED"]
        assert res["cavv"] is not None
        assert res["exemption"] == "LVP"
        assert "threeds_id" not in res or res.get("id")

    def test_frictionless_medium_tra(self):
        res = authenticate(PAN, AMOUNT_MEDIUM, card_status="ACTIVE", history_ok=True)
        assert res["status"] == AUTH_STATUS["AUTHENTICATED"]
        assert res["exemption"] == "TRA"

    def test_challenge_required_large(self):
        res = authenticate(PAN, AMOUNT_LARGE, card_status="ACTIVE",
                           history_ok=False, exemption_hint="NONE")
        assert res["status"] == AUTH_STATUS["CHALLENGE"]
        assert res["cavv"] is None
        assert "acs_url" in res

    def test_force_challenge(self):
        res = authenticate(PAN, AMOUNT_SMALL, card_status="ACTIVE",
                           force_challenge=True)
        assert res["status"] == AUTH_STATUS["CHALLENGE"]

    def test_not_auth_inactive_card(self):
        res = authenticate(PAN, AMOUNT_SMALL, card_status="BLOCKED")
        assert res["status"] == AUTH_STATUS["NOT_AUTH"]
        assert res["eci"] == ECI["NOT_AUTH"]

    def test_session_id_format(self):
        res = authenticate(PAN, AMOUNT_SMALL)
        assert res["id"].startswith("3DS-")
        assert len(res["id"]) > 8

    def test_pan_never_in_response(self):
        res = authenticate(PAN, AMOUNT_SMALL)
        response_str = str(res)
        assert PAN not in response_str

    def test_merchant_info_stored(self):
        res = authenticate(PAN, AMOUNT_SMALL,
                           merchant_id="MCH-001", merchant_name="Boutique Test",
                           mcc="5411")
        assert res["merchant_id"] == "MCH-001"
        assert res["merchant_name"] == "Boutique Test"
        assert res["mcc"] == "5411"

    def test_exemption_mit(self):
        res = authenticate(PAN, AMOUNT_LARGE, exemption_hint="MIT")
        assert res["status"] == AUTH_STATUS["AUTHENTICATED"]
        assert res["exemption"] == "MIT"

    def test_exemption_corp(self):
        res = authenticate(PAN, AMOUNT_LARGE, exemption_hint="CORP")
        assert res["status"] == AUTH_STATUS["AUTHENTICATED"]
        assert res["exemption"] == "CORP"

    def test_completed_at_set_for_frictionless(self):
        res = authenticate(PAN, AMOUNT_SMALL)
        assert res["completed_at"] is not None

    def test_completed_at_none_for_challenge(self):
        res = authenticate(PAN, AMOUNT_LARGE, history_ok=False,
                           exemption_hint="NONE")
        assert res["completed_at"] is None


# ── Tests submit_challenge ─────────────────────────────────────────────────────

class TestSubmitChallenge:

    def _start_challenge(self):
        res = authenticate(PAN, AMOUNT_LARGE, history_ok=False, exemption_hint="NONE")
        return res["id"]

    def test_wrong_otp_does_not_authenticate(self):
        sid = self._start_challenge()
        res = submit_challenge(sid, "0000")
        assert res["status"] in (AUTH_STATUS["CHALLENGE"], AUTH_STATUS["NOT_AUTH"])

    def test_max_attempts_blocks(self):
        sid = self._start_challenge()
        for _ in range(3):
            res = submit_challenge(sid, "0000")
        assert res["status"] == AUTH_STATUS["NOT_AUTH"]

    def test_unknown_session_id(self):
        res = submit_challenge("3DS-UNKNOWN123", "1234")
        assert "error" in res

    def test_challenge_not_pending_if_frictionless(self):
        res = authenticate(PAN, AMOUNT_SMALL)
        sid = res["id"]
        res2 = submit_challenge(sid, "0000")
        assert "error" in res2

    def test_challenge_hint_on_wrong_otp(self):
        sid = self._start_challenge()
        res = submit_challenge(sid, "9999")
        if res["status"] == AUTH_STATUS["CHALLENGE"]:
            assert "challenge_hint" in res


# ── Tests get_session ──────────────────────────────────────────────────────────

class TestGetSession:

    def test_get_existing_session(self):
        res = authenticate(PAN, AMOUNT_SMALL)
        sid = res["id"]
        session = get_session(sid)
        assert session is not None
        assert session["id"] == sid

    def test_get_unknown_session(self):
        assert get_session("3DS-DOESNOTEXIST") is None

    def test_challenge_code_not_exposed(self):
        res = authenticate(PAN, AMOUNT_LARGE, history_ok=False, exemption_hint="NONE")
        session = get_session(res["id"])
        assert "challenge_code" not in session


# ── Tests listing & stats ─────────────────────────────────────────────────────

class TestListingAndStats:

    def test_get_all_sessions_returns_list(self):
        authenticate(PAN, AMOUNT_SMALL)
        sessions = get_all_sessions()
        assert isinstance(sessions, list)
        assert len(sessions) > 0

    def test_filter_by_status(self):
        authenticate("5500000000000004", AMOUNT_SMALL)  # AUTHENTICATED
        sessions = get_all_sessions(status=AUTH_STATUS["AUTHENTICATED"])
        for s in sessions:
            assert s["status"] == AUTH_STATUS["AUTHENTICATED"]

    def test_stats_structure(self):
        stats = get_stats_3ds()
        assert "total" in stats
        assert "authenticated" in stats
        assert "challenge" in stats
        assert "not_auth" in stats
        assert "exemptions" in stats
        assert "auth_rate" in stats

    def test_stats_total_positive(self):
        authenticate(PAN, AMOUNT_SMALL)
        stats = get_stats_3ds()
        assert stats["total"] > 0

    def test_challenge_code_not_in_list(self):
        authenticate(PAN, AMOUNT_LARGE, history_ok=False, exemption_hint="NONE")
        sessions = get_all_sessions()
        for s in sessions:
            assert "challenge_code" not in s


# ── Tests limites LVP ─────────────────────────────────────────────────────────

class TestLimits:

    def test_lvp_boundary_below(self):
        res = authenticate(PAN, LVP_LIMIT_EUR_CENTS - 1)
        assert res["exemption"] == "LVP"

    def test_lvp_boundary_exact(self):
        res = authenticate(PAN, LVP_LIMIT_EUR_CENTS)
        assert res["exemption"] == "LVP"

    def test_above_lvp_without_tra(self):
        res = authenticate(PAN, LVP_LIMIT_EUR_CENTS + 1, history_ok=False,
                           exemption_hint="NONE")
        assert res["exemption"] == "NONE"

    def test_challenge_above_threshold(self):
        res = authenticate(PAN, CHALLENGE_THRESHOLD + 1, history_ok=False,
                           exemption_hint="NONE")
        assert res["status"] == AUTH_STATUS["CHALLENGE"]
