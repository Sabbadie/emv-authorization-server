"""
Tests C1 — Simulation flux CB complet.
Couvre : check_mcc_restriction, check_velocity, check_cb_routing,
check_pin_status, check_refund_rules, get_cb_service_indicator,
evaluate_threeds_result, evaluate_cb_rules (nouveaux paramètres).
"""

import pytest
from datetime import datetime, timezone, timedelta
from emv.giecb import (
    check_mcc_restriction, check_velocity, check_cb_routing,
    check_pin_status, check_refund_rules, get_cb_service_indicator,
    evaluate_threeds_result, evaluate_cb_rules,
    CB_BLOCKED_MCCS, CB_VELOCITY_LIMITS, CB_PIN_RULES,
    CB_DECLINE_REASONS, CB_SERVICE_INDICATORS,
)


# ── check_mcc_restriction ─────────────────────────────────────────────────────

class TestCheckMCCRestriction:
    def test_gambling_blocked(self):
        ok, reason, msg = check_mcc_restriction("7995")
        assert ok is False
        assert reason == "R12"
        assert "7995" in msg

    def test_adult_content_blocked(self):
        ok, reason, _ = check_mcc_restriction("5967")
        assert ok is False
        assert reason == "R12"

    def test_casino_online_blocked(self):
        ok, reason, _ = check_mcc_restriction("7801")
        assert ok is False

    def test_crypto_blocked(self):
        ok, _, _ = check_mcc_restriction("6051")
        assert ok is False

    def test_supermarket_allowed(self):
        ok, reason, _ = check_mcc_restriction("5411")
        assert ok is True
        assert reason is None

    def test_restaurant_allowed(self):
        ok, _, _ = check_mcc_restriction("5812")
        assert ok is True

    def test_none_mcc_allowed(self):
        ok, _, msg = check_mcc_restriction(None)
        assert ok is True

    def test_unknown_mcc_allowed(self):
        ok, _, _ = check_mcc_restriction("9999")
        assert ok is True

    def test_all_blocked_mccs_rejected(self):
        for mcc in CB_BLOCKED_MCCS:
            ok, _, _ = check_mcc_restriction(mcc)
            assert ok is False, f"MCC {mcc} devrait être bloqué"


# ── check_velocity ────────────────────────────────────────────────────────────

def _make_txns(count, minutes_ago=5, amount=1000, txn_type="00"):
    now = datetime.now(timezone.utc)
    return [
        {
            "timestamp": (now - timedelta(minutes=minutes_ago)).isoformat(),
            "amount": amount,
            "type": txn_type,
        }
        for _ in range(count)
    ]


class TestCheckVelocity:
    def test_no_recent_txns_ok(self):
        ok, _, msg, _ = check_velocity(None, 1000, "00")
        assert ok is True

    def test_empty_list_ok(self):
        ok, _, _, _ = check_velocity([], 1000, "00")
        assert ok is True

    def test_below_30min_limit_ok(self):
        txns = _make_txns(9, minutes_ago=10)
        ok, _, _, stats = check_velocity(txns, 1000, "00")
        assert ok is True
        assert stats["txn_30min"] == 9

    def test_exceed_30min_limit(self):
        txns = _make_txns(CB_VELOCITY_LIMITS["max_txn_per_30min"], minutes_ago=10)
        ok, reason, msg, _ = check_velocity(txns, 1000, "00")
        assert ok is False
        assert reason == "R13"

    def test_old_txns_not_counted(self):
        txns = _make_txns(12, minutes_ago=90)
        ok, _, _, stats = check_velocity(txns, 1000, "00")
        assert ok is True
        assert stats["txn_30min"] == 0
        assert stats["txn_1h"] == 0

    def test_exceed_hourly_amount(self):
        big_txns = _make_txns(3, minutes_ago=10, amount=70000)
        ok, reason, _, _ = check_velocity(big_txns, 70000, "00")
        assert ok is False
        assert reason == "R13"

    def test_exceed_refund_daily_limit(self):
        refunds = _make_txns(CB_VELOCITY_LIMITS["max_refund_per_day"],
                              minutes_ago=60, txn_type="20")
        ok, reason, _, _ = check_velocity(refunds, 1000, "20")
        assert ok is False
        assert reason == "R13"

    def test_refund_below_limit_ok(self):
        refunds = _make_txns(1, minutes_ago=60, txn_type="20")
        ok, _, _, _ = check_velocity(refunds, 1000, "20")
        assert ok is True

    def test_txn_with_string_timestamp(self):
        now = datetime.now(timezone.utc)
        txns = [{"timestamp": now.isoformat(), "amount": 500, "type": "00"}]
        ok, _, _, stats = check_velocity(txns, 500, "00")
        assert ok is True
        assert stats["txn_30min"] == 1

    def test_txn_with_missing_timestamp_ignored(self):
        txns = [{"amount": 500, "type": "00"}]
        ok, _, _, stats = check_velocity(txns, 500, "00")
        assert ok is True


# ── check_cb_routing ──────────────────────────────────────────────────────────

class TestCheckCBRouting:
    def test_domestic_visa_routed_to_cb(self):
        r = check_cb_routing("4111111111111111", None, "250")
        assert r["preferred_network"] == "CB"
        assert r["is_domestic"] is True

    def test_domestic_mc_routed_to_cb(self):
        r = check_cb_routing("5500000000000004", None, "FRA")
        assert r["preferred_network"] == "CB"

    def test_domestic_fr_code_routed(self):
        r = check_cb_routing("4111111111111111", None, "FR")
        assert r["is_domestic"] is True
        assert r["preferred_network"] == "CB"

    def test_international_stays_visa(self):
        r = check_cb_routing("4111111111111111", None, "840")
        assert r["preferred_network"] == "VISA"
        assert r["is_domestic"] is False

    def test_no_country_not_domestic(self):
        r = check_cb_routing("4111111111111111", None, None)
        assert r["is_domestic"] is False

    def test_cb_aid_domestic(self):
        r = check_cb_routing("4111111111111111", "A0000000421010", "250")
        assert r["actual_scheme"] == "CB"
        assert r["preferred_network"] == "CB"

    def test_overseas_territory_domestic(self):
        r = check_cb_routing("4111111111111111", None, "GP")
        assert r["is_domestic"] is True


# ── check_pin_status ──────────────────────────────────────────────────────────

class TestCheckPINStatus:
    def test_none_tries_ok(self):
        ok, rc, msg = check_pin_status(None)
        assert ok is True
        assert rc is None

    def test_three_tries_ok(self):
        ok, rc, _ = check_pin_status(3)
        assert ok is True

    def test_one_try_warns(self):
        ok, rc, msg = check_pin_status(1)
        assert ok is True
        assert "Dernière" in msg

    def test_zero_tries_blocked(self):
        ok, rc, msg = check_pin_status(0)
        assert ok is False
        assert rc == "75"
        assert "bloqué" in msg

    def test_negative_tries_blocked(self):
        ok, rc, _ = check_pin_status(-1)
        assert ok is False


# ── check_refund_rules ────────────────────────────────────────────────────────

class TestCheckRefundRules:
    def test_no_original_amount_ok(self):
        ok, _, _ = check_refund_rules(5000, None)
        assert ok is True

    def test_equal_amount_ok(self):
        ok, _, _ = check_refund_rules(5000, 5000)
        assert ok is True

    def test_less_than_original_ok(self):
        ok, _, _ = check_refund_rules(3000, 5000)
        assert ok is True

    def test_more_than_original_rejected(self):
        ok, reason, msg = check_refund_rules(6000, 5000)
        assert ok is False
        assert reason == "R15"
        assert "60.00" in msg or "50.00" in msg

    def test_zero_refund_ok(self):
        ok, _, _ = check_refund_rules(0, 5000)
        assert ok is True


# ── get_cb_service_indicator ──────────────────────────────────────────────────

class TestGetCBServiceIndicator:
    def test_withdrawal_national(self):
        assert get_cb_service_indicator("01") == "04"

    def test_withdrawal_international_visa(self):
        assert get_cb_service_indicator("01", scheme="VISA", is_international=True) == "05"

    def test_refund(self):
        assert get_cb_service_indicator("20") == "12"

    def test_cancel(self):
        assert get_cb_service_indicator("22") == "11"

    def test_preauth(self):
        assert get_cb_service_indicator("10") == "10"

    def test_preauth_flag(self):
        assert get_cb_service_indicator("00", is_preauth=True) == "10"

    def test_recurring(self):
        assert get_cb_service_indicator("00", is_recurring=True) == "08"

    def test_ecommerce(self):
        assert get_cb_service_indicator("00", is_ecommerce=True) == "07"

    def test_contactless(self):
        assert get_cb_service_indicator("00", is_contactless=True) == "06"

    def test_visa_default(self):
        assert get_cb_service_indicator("00", scheme="VISA") == "02"

    def test_mc_default(self):
        assert get_cb_service_indicator("00", scheme="MC") == "03"

    def test_cb_default(self):
        assert get_cb_service_indicator("00") == "01"


# ── evaluate_threeds_result ───────────────────────────────────────────────────

class TestEvaluate3DSResult:
    def test_none_eci_returns_none(self):
        ok, result, warns = evaluate_threeds_result(None)
        assert ok is None
        assert result is None

    def test_eci_05_authenticated(self):
        ok, result, warns = evaluate_threeds_result("05")
        assert ok is True
        assert "ECI=05" in result
        assert warns == []

    def test_eci_06_attempt(self):
        ok, result, warns = evaluate_threeds_result("06")
        assert ok is True
        assert "ECI=06" in result
        assert len(warns) == 1

    def test_eci_07_not_authenticated(self):
        ok, result, warns = evaluate_threeds_result("07")
        assert ok is False
        assert "ECI=07" in result
        assert len(warns) == 1

    def test_unknown_eci(self):
        ok, result, warns = evaluate_threeds_result("99")
        assert ok is None
        assert "99" in result


# ── evaluate_cb_rules nouveaux paramètres ─────────────────────────────────────

class TestEvaluateCBRulesC1:
    PAN = "4111111111111111"

    def test_blocked_mcc_rejected(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", mcc="7995")
        assert r.allowed is False
        assert r.cb_decline_reason == "R12"

    def test_pin_blocked_rejected(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", pin_tries_remaining=0)
        assert r.allowed is False
        assert r.response_code == "75"

    def test_velocity_exceeded_rejected(self):
        txns = _make_txns(CB_VELOCITY_LIMITS["max_txn_per_30min"], minutes_ago=5)
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00",
                               recent_transactions=txns)
        assert r.allowed is False
        assert r.cb_decline_reason == "R13"

    def test_domestic_routing_info(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", country_code="250")
        assert r.allowed is True
        assert "CB" in r.routing_info

    def test_ecommerce_service_indicator(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", is_ecommerce=True)
        assert r.service_indicator == "07"

    def test_recurring_service_indicator(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", is_recurring=True)
        assert r.service_indicator == "08"

    def test_threeds_authenticated_allowed(self):
        r = evaluate_cb_rules(self.PAN, 10000, "978", "00",
                               is_ecommerce=True, threeds_eci="05")
        assert r.allowed is True
        assert r.threeds_result and "ECI=05" in r.threeds_result

    def test_threeds_not_authenticated_high_amount_rejected(self):
        r = evaluate_cb_rules(self.PAN, 10000, "978", "00",
                               is_ecommerce=True, threeds_eci="07")
        assert r.allowed is False
        assert r.cb_response_code == "1A"

    def test_threeds_attempt_allowed_with_warning(self):
        r = evaluate_cb_rules(self.PAN, 10000, "978", "00",
                               is_ecommerce=True, threeds_eci="06")
        assert r.allowed is True
        assert any("ECI=06" in w for w in r.warnings)

    def test_refund_exceeds_original_rejected(self):
        r = evaluate_cb_rules(self.PAN, 6000, "978", "20",
                               refund_original_amount=5000)
        assert r.allowed is False
        assert r.cb_decline_reason == "R15"

    def test_refund_within_original_ok(self):
        r = evaluate_cb_rules(self.PAN, 4000, "978", "20",
                               refund_original_amount=5000)
        assert r.allowed is True
        assert r.service_indicator == "12"

    def test_preauth_service_indicator(self):
        r = evaluate_cb_rules(self.PAN, 5000, "978", "00", is_preauth=True)
        assert r.service_indicator == "10"

    def test_to_dict_includes_new_fields(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", country_code="250")
        d = r.to_dict()
        assert "velocity_check" in d
        assert "routing_info" in d
        assert "threeds_result" in d
        assert "pin_check" in d

    def test_pos_entry_ecommerce_detected(self):
        r = evaluate_cb_rules(self.PAN, 1000, "978", "00", pos_entry_mode="01")
        assert r.service_indicator == "07"
