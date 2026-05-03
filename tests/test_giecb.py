"""
Tests unitaires — emv/giecb.py
Couvre : identify_card, get_floor_limit, get_sca_exemption,
         check_contactless, evaluate_cb_rules, CBAuthResult.to_dict
"""

import pytest
from emv.giecb import (
    identify_card, get_floor_limit, get_sca_exemption,
    check_contactless, evaluate_cb_rules,
    CB_AIDS, CB_MCC_FLOOR_LIMITS, CB_CAP, CB_CONTACTLESS,
    CB_TAP, CBCardInfo, CBAuthResult,
)


class TestIdentifyCard:
    def test_visa_pan_by_prefix(self):
        info = identify_card("4111111111111111")
        assert info.scheme == "VISA"
        assert info.brand == "VISA CB"

    def test_mc_pan_51_prefix(self):
        info = identify_card("5111111111111111")
        assert info.scheme == "MC"

    def test_mc_pan_55_prefix(self):
        info = identify_card("5500000000000004")
        assert info.scheme == "MC"

    def test_amex_pan_34_prefix(self):
        info = identify_card("341234567890123")
        assert info.scheme == "AMEX"

    def test_amex_pan_37_prefix(self):
        info = identify_card("371234567890123")
        assert info.scheme == "AMEX"

    def test_maestro_pan(self):
        info = identify_card("6304123456789012")
        assert info.scheme == "MAESTRO"

    def test_unknown_pan(self):
        info = identify_card("9999999999999999")
        assert info.scheme == "UNKNOWN"

    def test_unknown_not_cb_network(self):
        info = identify_card("9999999999999999")
        assert info.is_cb_network is False

    def test_visa_is_cb_network(self):
        info = identify_card("4111111111111111")
        assert info.is_cb_network is True

    def test_aid_visa_overrides_pan(self):
        info = identify_card("9999999999999999", aid_hex="A0000000031010")
        assert info.scheme == "VISA"

    def test_aid_mc_overrides(self):
        info = identify_card("4111111111111111", aid_hex="A0000000041010")
        assert info.scheme == "MC"

    def test_aid_cb_native(self):
        info = identify_card("4970100000000154", aid_hex="A0000000421010")
        assert info.scheme == "CB"
        assert info.brand == "CB"

    def test_service_indicator_visa(self):
        info = identify_card("4111111111111111")
        assert info.service_indicator == "02"

    def test_service_indicator_mc(self):
        info = identify_card("5500000000000004")
        assert info.service_indicator == "03"

    def test_service_indicator_cb(self):
        info = identify_card("4970100000000154", aid_hex="A0000000421010")
        assert info.service_indicator == "01"

    def test_visa_electron_no_contactless(self):
        info = identify_card("4111111111111111", aid_hex="A0000000032010")
        assert info.supports_contactless is False

    def test_pan_spaces_stripped(self):
        info1 = identify_card("4111 1111 1111 1111")
        info2 = identify_card("4111111111111111")
        assert info1.scheme == info2.scheme

    def test_aid_name_set_when_known(self):
        info = identify_card("4111111111111111", aid_hex="A0000000031010")
        assert info.aid_name is not None

    def test_aid_name_none_when_only_bin(self):
        info = identify_card("4111111111111111")
        assert info.aid_name is None


class TestGetFloorLimit:
    def test_known_mcc_supermarket(self):
        assert get_floor_limit("5411") == 3000

    def test_known_mcc_pharmacy(self):
        assert get_floor_limit("5912") == 5000

    def test_gas_station_always_online(self):
        assert get_floor_limit("5541") == 0
        assert get_floor_limit("5542") == 0

    def test_hotel_always_online(self):
        assert get_floor_limit("7011") == 0

    def test_unknown_mcc_returns_default(self):
        assert get_floor_limit("9999") == CB_MCC_FLOOR_LIMITS["DEFAULT"]

    def test_none_mcc_returns_default(self):
        assert get_floor_limit(None) == CB_MCC_FLOOR_LIMITS["DEFAULT"]

    def test_empty_string_returns_default(self):
        assert get_floor_limit("") == CB_MCC_FLOOR_LIMITS["DEFAULT"]

    def test_transport_mcc(self):
        assert get_floor_limit("4111") == 5000

    def test_toll_mcc(self):
        assert get_floor_limit("4784") == 5000


class TestGetSCAExemption:
    def test_lvp_for_low_value(self):
        assert get_sca_exemption(100, "00") == "LVP"

    def test_lvp_at_threshold(self):
        assert get_sca_exemption(CB_CONTACTLESS["low_value_threshold"], "00") == "LVP"

    def test_tra_above_low_value(self):
        sca = get_sca_exemption(CB_CONTACTLESS["low_value_threshold"] + 1, "00")
        assert sca == "TRA"

    def test_tra_up_to_25000(self):
        assert get_sca_exemption(25000, "00") == "TRA"

    def test_none_above_25000(self):
        assert get_sca_exemption(25001, "00") == "NONE"

    def test_none_for_high_amount(self):
        assert get_sca_exemption(100000, "00") == "NONE"

    def test_mit_for_recurring(self):
        assert get_sca_exemption(50000, "00", is_recurring=True) == "MIT"

    def test_mit_overrides_amount(self):
        assert get_sca_exemption(100, "00", is_recurring=True) == "MIT"


class TestCheckContactless:
    def test_ok_small_amount(self):
        ok, code, msg = check_contactless(1000, 0, 0)
        assert ok is True
        assert code == "00"

    def test_ok_at_single_limit(self):
        limit = CB_CONTACTLESS["single_txn_limit"]
        ok, code, _ = check_contactless(limit, 0, 0)
        assert ok is True

    def test_fail_exceeds_single_limit(self):
        limit = CB_CONTACTLESS["single_txn_limit"]
        ok, code, _ = check_contactless(limit + 1, 0, 0)
        assert ok is False
        assert code == "P1"

    def test_fail_cumulative_exceeded(self):
        cumul_limit = CB_CONTACTLESS["cumulative_offline_limit"]
        ok, code, _ = check_contactless(1000, cumul_limit, 0)
        assert ok is False
        assert code == "A5"

    def test_fail_cumulative_with_partial_existing(self):
        cumul_limit = CB_CONTACTLESS["cumulative_offline_limit"]
        ok, code, _ = check_contactless(1000, cumul_limit - 500, 0)
        assert ok is False
        assert code == "A5"

    def test_fail_max_consecutive_offline(self):
        max_off = CB_CONTACTLESS["max_consecutive_offline"]
        ok, code, _ = check_contactless(1000, 0, max_off)
        assert ok is False
        assert code == "A5"

    def test_ok_below_max_consecutive(self):
        max_off = CB_CONTACTLESS["max_consecutive_offline"]
        ok, _, _ = check_contactless(1000, 0, max_off - 1)
        assert ok is True

    def test_msg_not_empty(self):
        _, _, msg = check_contactless(1000, 0, 0)
        assert msg != ""


class TestEvaluateCBRules:
    def test_standard_purchase_approved(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        assert result.allowed is True
        assert result.response_code == "00"

    def test_cap_exceeded_referral(self):
        amount = CB_CAP["referral_threshold"] + 100
        result = evaluate_cb_rules("4111111111111111", amount, "978", "00")
        assert result.allowed is False
        assert result.cb_response_code == "01"

    def test_contactless_ok(self):
        result = evaluate_cb_rules("4111111111111111", 2000, "978", "00",
                                   is_contactless=True, contactless_cumul=0,
                                   consecutive_offline=0)
        assert result.allowed is True
        assert result.is_contactless is True

    def test_contactless_exceeds_limit(self):
        limit = CB_CONTACTLESS["single_txn_limit"]
        result = evaluate_cb_rules("4111111111111111", limit + 1, "978", "00",
                                   is_contactless=True)
        assert result.allowed is False
        assert result.cb_response_code == "P1"

    def test_contactless_cumulative_exceeded(self):
        cumul_limit = CB_CONTACTLESS["cumulative_offline_limit"]
        result = evaluate_cb_rules("4111111111111111", 1000, "978", "00",
                                   is_contactless=True,
                                   contactless_cumul=cumul_limit)
        assert result.allowed is False

    def test_service_indicator_contactless(self):
        result = evaluate_cb_rules("4111111111111111", 500, "978", "00",
                                   is_contactless=True)
        assert result.service_indicator == "06"

    def test_service_indicator_withdrawal(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "01")
        assert result.service_indicator == "04"

    def test_service_indicator_refund(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "20")
        assert result.service_indicator == "12"

    def test_gas_station_warning(self):
        result = evaluate_cb_rules("4111111111111111", 2000, "978", "00",
                                   mcc="5541")
        assert any("ligne" in w or "floor" in w.lower() for w in result.warnings)

    def test_high_value_warning(self):
        result = evaluate_cb_rules("4111111111111111",
                                   CB_CAP["high_value_threshold"], "978", "00")
        assert any("élevé" in w or "high" in w.lower() for w in result.warnings)

    def test_pos_mode_07_sets_contactless(self):
        result = evaluate_cb_rules("4111111111111111", 1000, "978", "00",
                                   pos_entry_mode="071")
        assert result.is_contactless is True

    def test_sca_exemption_low_value(self):
        result = evaluate_cb_rules("4111111111111111", 1000, "978", "00")
        assert result.sca_exemption == "LVP"

    def test_floor_limit_in_result(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00",
                                   mcc="5411")
        assert result.floor_limit_applied == 3000

    def test_tap_params_present(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        assert result.tap_params == CB_TAP

    def test_cap_check_string(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        assert "OK" in result.cap_check

    def test_too_many_offline_warning(self):
        result = evaluate_cb_rules("4111111111111111", 1000, "978", "00",
                                   consecutive_offline=CB_TAP["TAP4_max_offline_count"])
        assert any("TAP4" in w for w in result.warnings)


class TestCBAuthResultToDict:
    def test_contains_required_keys(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        d = result.to_dict()
        required = [
            "allowed", "response_code", "cb_response_code", "response_message",
            "service_indicator", "sca_exemption", "floor_limit_applied",
            "is_contactless", "contactless_check", "mcc_rule", "cap_check",
            "tap_params", "warnings",
        ]
        for key in required:
            assert key in d, f"Clé manquante : {key}"

    def test_warnings_is_list(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        assert isinstance(result.to_dict()["warnings"], list)

    def test_tap_params_is_dict(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00")
        assert isinstance(result.to_dict()["tap_params"], dict)

    def test_is_contactless_bool(self):
        result = evaluate_cb_rules("4111111111111111", 5000, "978", "00",
                                   is_contactless=True)
        assert result.to_dict()["is_contactless"] is True
