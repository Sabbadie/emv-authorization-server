"""
Tests unitaires — emv/authorization.py
Couvre : generate_auth_code, check_tvr, _parse_emv_field55,
         authorize (multiples scénarios), AuthorizationResult.to_dict
"""

import pytest
from emv.authorization import (
    generate_auth_code, check_tvr, _parse_emv_field55,
    authorize, AuthorizationResult,
)
from models.card import card_db, CardStatus
from models.transaction import TransactionStatus

PAN_ACTIVE  = "4111111111111111"
PAN_BLOCKED = "4000000000000028"
PAN_EXPIRED = "4000000000000010"
PAN_INSUF   = "4000000000000036"
PAN_UNKNOWN = "9999999999999999"

SIMPLE_EMV = (
    "9F02060000000050009F03060000000000009F1A020250"
    "950500000000009A032601019C0100"
    "9F370412345678"
    "9F360200059F2608AABBCCDD11223344"
    "9F270140"
)


def _reset_active_card():
    card = card_db.get_card(PAN_ACTIVE)
    if card:
        card.status = CardStatus.ACTIVE
        card.balance = 500000
        card.daily_spent = 0
        card.daily_limit = 200000
        card.contactless_cumul = 0
        card.consecutive_offline = 0
        card.last_reset_date = __import__('datetime').datetime.utcnow().date().isoformat()


def _reset_insuf_card():
    card = card_db.get_card(PAN_INSUF)
    if card:
        card.status = CardStatus.ACTIVE
        card.balance = 100
        card.daily_spent = 0


def _clear_txn_log_for(*pans):
    from models.transaction import transaction_log
    for pan in pans:
        ids = transaction_log._pan_index.pop(pan, [])
        for tid in ids:
            transaction_log._transactions.pop(tid, None)


class TestGenerateAuthCode:
    def test_length_6(self):
        code = generate_auth_code()
        assert len(code) == 6

    def test_digits_only(self):
        code = generate_auth_code()
        assert code.isdigit()

    def test_unique_per_call(self):
        codes = {generate_auth_code() for _ in range(20)}
        assert len(codes) >= 2

    def test_zero_padded_if_needed(self):
        code = generate_auth_code()
        assert len(code) == 6


class TestCheckTVR:
    def test_all_zeros_no_flags(self):
        flags = check_tvr(b"\x00\x00\x00\x00\x00")
        assert flags == []

    def test_sda_failed(self):
        flags = check_tvr(b"\x40\x00\x00\x00\x00")
        assert any("SDA failed" in f for f in flags)

    def test_dda_failed(self):
        flags = check_tvr(b"\x08\x00\x00\x00\x00")
        assert any("DDA failed" in f for f in flags)

    def test_cda_failed(self):
        flags = check_tvr(b"\x04\x00\x00\x00\x00")
        assert any("CDA failed" in f for f in flags)

    def test_offline_not_performed(self):
        flags = check_tvr(b"\x80\x00\x00\x00\x00")
        assert any("not performed" in f.lower() for f in flags)

    def test_card_exception_file(self):
        flags = check_tvr(b"\x10\x00\x00\x00\x00")
        assert any("exception" in f.lower() for f in flags)

    def test_icc_missing(self):
        flags = check_tvr(b"\x20\x00\x00\x00\x00")
        assert any("missing" in f.lower() or "ICC" in f for f in flags)

    def test_expired_application(self):
        flags = check_tvr(b"\x00\x40\x00\x00\x00")
        assert any("Expired" in f for f in flags)

    def test_different_app_versions(self):
        flags = check_tvr(b"\x00\x80\x00\x00\x00")
        assert any("version" in f.lower() for f in flags)

    def test_cardholder_verification_failed(self):
        flags = check_tvr(b"\x00\x00\x80\x00\x00")
        assert any("verification" in f.lower() for f in flags)

    def test_pin_try_limit_exceeded(self):
        flags = check_tvr(b"\x00\x00\x20\x00\x00")
        assert any("pin" in f.lower() for f in flags)

    def test_floor_limit_exceeded(self):
        flags = check_tvr(b"\x00\x00\x00\x80\x00")
        assert any("floor" in f.lower() for f in flags)

    def test_issuer_auth_failed(self):
        flags = check_tvr(b"\x00\x00\x00\x00\x40")
        assert any("authentication" in f.lower() or "Issuer" in f for f in flags)

    def test_multiple_flags(self):
        flags = check_tvr(b"\x48\x00\x00\x00\x00")
        assert len(flags) >= 2

    def test_short_tvr_returns_empty(self):
        flags = check_tvr(b"\x48")
        assert flags == []

    def test_none_returns_empty(self):
        flags = check_tvr(None)
        assert flags == []

    def test_empty_bytes_returns_empty(self):
        flags = check_tvr(b"")
        assert flags == []


class TestParseEmvField55:
    def test_valid_returns_dict(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert isinstance(result, dict)

    def test_amount_authorized_parsed(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert result is not None
        assert result.get("amount_authorized") is not None

    def test_transaction_type_parsed(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert result is not None
        assert result.get("transaction_type") is not None

    def test_cryptogram_parsed(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert result is not None
        assert result.get("cryptogram") is not None

    def test_atc_parsed(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert result is not None
        assert result.get("atc") is not None

    def test_all_fields_key_present(self):
        result = _parse_emv_field55(SIMPLE_EMV)
        assert result is not None
        assert "all_fields" in result

    def test_invalid_hex_returns_none(self):
        result = _parse_emv_field55("ZZZZZZZZ")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_emv_field55("")
        assert result is None

    def test_none_returns_none(self):
        result = _parse_emv_field55(None)
        assert result is None


class TestAuthorize:
    def setup_method(self):
        _clear_txn_log_for(PAN_ACTIVE, PAN_INSUF, PAN_EXPIRED, PAN_BLOCKED, PAN_UNKNOWN)
        _reset_active_card()
        _reset_insuf_card()

    def test_active_card_approved(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.approved is True
        assert result.response_code == "00"

    def test_approved_has_auth_code(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.auth_code is not None
        assert len(result.auth_code) == 6

    def test_approved_has_transaction(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.transaction is not None
        assert result.transaction.status == TransactionStatus.APPROVED

    def test_blocked_card_declined(self):
        result = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code in ("62", "41", "43")

    def test_expired_card_declined(self):
        result = authorize(PAN_EXPIRED, 5000, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code == "54"

    def test_insufficient_funds_declined(self):
        result = authorize(PAN_INSUF, 5000, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code == "51"

    def test_unknown_pan_declined_14(self):
        result = authorize(PAN_UNKNOWN, 5000, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code == "14"

    def test_zero_amount_declined_13(self):
        result = authorize(PAN_ACTIVE, 0, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code == "13"

    def test_negative_amount_declined(self):
        result = authorize(PAN_ACTIVE, -100, "978", "00", skip_crypto=True)
        assert result.approved is False

    def test_critical_amount_referral(self):
        result = authorize(PAN_ACTIVE, 600000, "978", "00", skip_crypto=True)
        assert result.approved is False
        assert result.response_code == "01"

    def test_has_amount_decision(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.amount_decision is not None

    def test_has_cb_result(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.cb_result is not None

    def test_amount_tier_in_transaction(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.transaction.amount_tier is not None

    def test_cb_scheme_in_transaction(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.transaction.cb_scheme is not None
        assert result.transaction.cb_scheme != ""

    def test_pan_spaces_handled(self):
        result = authorize("4111 1111 1111 1111", 5000, "978", "00", skip_crypto=True)
        assert result.approved is True

    def test_contactless_purchase_approved(self):
        result = authorize(PAN_ACTIVE, 2000, "978", "00",
                           skip_crypto=True, is_contactless=True)
        assert result.approved is True
        assert result.transaction.cb_is_contactless is True

    def test_contactless_purchase_service_indicator_06(self):
        result = authorize(PAN_ACTIVE, 2000, "978", "00",
                           skip_crypto=True, is_contactless=True)
        assert result.transaction.cb_service_indicator == "06"

    def test_withdrawal_type_01(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "01", skip_crypto=True)
        assert result.approved is True

    def test_with_terminal_id(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00",
                           terminal_id="TERM0001", skip_crypto=True)
        assert result.transaction.terminal_id == "TERM0001"

    def test_with_merchant_info(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00",
                           merchant_name="TEST SHOP", skip_crypto=True)
        assert result.transaction.merchant_name == "TEST SHOP"

    def test_transaction_logged(self):
        from models.transaction import transaction_log
        initial_count = len(transaction_log._transactions)
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert len(transaction_log._transactions) == initial_count + 1

    def test_skip_crypto_allows_emv_no_verify(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00",
                           field_55=SIMPLE_EMV, skip_crypto=True)
        assert result.approved is True

    def test_with_mcc(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00",
                           mcc="5411", skip_crypto=True)
        assert result.approved is True

    def test_micro_amount_offline(self):
        result = authorize(PAN_ACTIVE, 200, "978", "00", skip_crypto=True)
        assert result.approved is True
        assert result.amount_decision.auth_path == "OFFLINE"

    def test_large_daily_spend_rejected(self):
        card = card_db.get_card(PAN_ACTIVE)
        card.daily_spent = 199900
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.approved is False

    def test_balance_decremented_on_approve(self):
        card = card_db.get_card(PAN_ACTIVE)
        initial_balance = card.balance
        authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert card.balance == initial_balance - 5000


class TestAuthorizationResultToDict:
    def setup_method(self):
        _clear_txn_log_for(PAN_ACTIVE, PAN_BLOCKED)
        _reset_active_card()

    def test_contains_approved(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "approved" in d
        assert d["approved"] is True

    def test_contains_response_code(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert d["response_code"] == "00"

    def test_contains_auth_code_when_approved(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "auth_code" in d

    def test_contains_amount_decision(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "amount_decision" in d
        assert d["amount_decision"]["tier_name"] is not None

    def test_contains_cb_result(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "cb_result" in d

    def test_contains_transaction(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "transaction" in d

    def test_contains_tpa_response(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=True)
        assert "tpa_response" in d

    def test_declined_no_auth_code(self):
        result = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "auth_code" not in d or d.get("auth_code") is None

    def test_tpa_property_lazy_then_set(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result._tpa is None
        tpa = result.tpa
        assert tpa is not None

    def test_message_not_empty(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        assert result.message != ""

    def test_declined_message_not_empty(self):
        result = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        assert result.message != ""

    def test_without_tpa(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert "tpa_response" not in d

    def test_approved_flag_in_dict(self):
        result = authorize(PAN_ACTIVE, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert d["approved"] is True

    def test_declined_approved_false(self):
        result = authorize(PAN_BLOCKED, 5000, "978", "00", skip_crypto=True)
        d = result.to_dict(include_tpa=False)
        assert d["approved"] is False
