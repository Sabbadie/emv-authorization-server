"""
Tests unitaires — models/tpa_response.py
Couvre : TPAResponse._build, to_dict, to_flat, to_iso8583_like,
         TPA_FIELD_DEFINITIONS, CB_SERVICE_INDICATOR_LABELS
"""

import pytest
from models.transaction import Transaction, TransactionStatus
from models.tpa_response import (
    TPAResponse, TPA_FIELD_DEFINITIONS,
    CB_SERVICE_INDICATOR_LABELS, CB_RESPONSE_CODE_LABELS,
    SCA_EXEMPTION_LABELS,
)


def make_txn_minimal(pan="4111111111111111", amount=5000):
    txn = Transaction(
        pan=pan, amount=amount, currency="978",
        transaction_type="00",
        terminal_id="TERM0001",
        merchant_id="MERCH001",
        merchant_name="TEST SHOP",
        pos_entry_mode="051",
    )
    return txn


def make_txn_approved(pan="4111111111111111", amount=5000):
    txn = make_txn_minimal(pan, amount)
    txn.approve("654321")
    txn.amount_tier = "STANDARD"
    txn.risk_level = "MEDIUM"
    txn.auth_path = "ONLINE"
    txn.cb_scheme = "VISA"
    txn.cb_brand = "VISA CB"
    txn.cb_service_indicator = "02"
    txn.cb_sca_exemption = "LVP"
    txn.cb_floor_limit = 3000
    txn.cb_is_contactless = False
    txn.cb_response_code = "00"
    return txn


def make_txn_declined(pan="4111111111111111"):
    txn = make_txn_minimal(pan)
    txn.decline("51", "Insufficient funds")
    txn.cb_response_code = "51"
    txn.cb_decline_reason = "R01"
    txn.cb_floor_limit = 0
    return txn


class MockAuthResult:
    def __init__(self, approved=True, response_code="00"):
        self.approved = approved
        self.response_code = response_code
        self.auth_code = "654321" if approved else None
        self.arpc = None
        self.issuer_auth_data = None


class MockAmountDecision:
    def __init__(self):
        from emv.amount_rules import get_tier, evaluate_amount
        self._decision = evaluate_amount(10000, "00")
        self.tier = self._decision.tier
        self.auth_path = "ONLINE"
        self.warnings = ["Test warning"]

    def to_dict(self):
        return self._decision.to_dict()


class TestTPAResponseBuild:
    def test_f00_is_0110(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F00"] == "0110"

    def test_f02_masked_pan(self):
        txn = make_txn_approved(pan="4111111111111111")
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        f02 = tpa.fields["F02"]
        assert f02.endswith("1111")
        assert "*" in f02

    def test_f02_short_pan_not_masked(self):
        txn = make_txn_approved(pan="4111")
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F02"] == "4111"

    def test_f04_amount_zero_padded(self):
        txn = make_txn_approved(amount=5000)
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F04"] == "000000005000"

    def test_f04a_formatted(self):
        txn = make_txn_approved(amount=5000)
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F04A"] == "50.00"

    def test_f03_processing_code(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F03"] == "000000"

    def test_f39_response_code_approved(self):
        txn = make_txn_approved()
        auth = MockAuthResult(approved=True)
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F39"] == "00"

    def test_f39_response_code_declined(self):
        txn = make_txn_declined()
        auth = MockAuthResult(approved=False, response_code="51")
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F39"] == "51"

    def test_f39l_response_label(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F39L"] != ""

    def test_f38_auth_code_when_approved(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "F38" in tpa.fields
        assert len(tpa.fields["F38"]) == 6

    def test_f38_not_set_when_declined(self):
        txn = make_txn_declined()
        auth = MockAuthResult(approved=False, response_code="51")
        tpa = TPAResponse(txn, auth)
        assert "F38" not in tpa.fields

    def test_f49_currency(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F49"] == "978"

    def test_f49l_currency_label(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["F49L"] != "???"

    def test_f41_terminal_id(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "TERM0001" in tpa.fields.get("F41", "")

    def test_f42_merchant_id(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "MERCH001" in tpa.fields.get("F42", "")

    def test_f43_merchant_name(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "TEST SHOP" in tpa.fields.get("F43", "")

    def test_f37_rrn(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "F37" in tpa.fields
        assert tpa.fields["F37"] == txn.rrn

    def test_cb1_card_type(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB1" in tpa.fields
        assert tpa.fields["CB1"] == "VISA CB"

    def test_cb2_scheme(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB2" in tpa.fields
        assert tpa.fields["CB2"] == "VISA"

    def test_cb4_service_indicator(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB4" in tpa.fields

    def test_cb4l_service_label(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB4L" in tpa.fields
        assert tpa.fields["CB4L"] != "—" or tpa.fields["CB4"] in CB_SERVICE_INDICATOR_LABELS

    def test_cb5_contactless_flag(self):
        txn = make_txn_approved()
        txn.cb_is_contactless = True
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["CB5"] == "OUI"

    def test_cb5_not_contactless(self):
        txn = make_txn_approved()
        txn.cb_is_contactless = False
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert tpa.fields["CB5"] == "NON"

    def test_cb6_contactless_cumul(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB6" in tpa.fields

    def test_cb6l_formatted(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB6L" in tpa.fields
        assert "€" in tpa.fields["CB6L"]

    def test_cb9_floor_limit(self):
        txn = make_txn_approved()
        txn.cb_floor_limit = 3000
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB9" in tpa.fields
        assert tpa.fields["CB9"] == "3000"

    def test_cb9l_formatted(self):
        txn = make_txn_approved()
        txn.cb_floor_limit = 3000
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CB9L" in tpa.fields
        assert tpa.fields["CB9L"] == "30.00€"

    def test_cba_cb_response_code(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CBA" in tpa.fields
        assert tpa.fields["CBA"] == "00"

    def test_cbal_response_label(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "CBAL" in tpa.fields

    def test_cbb_decline_reason_when_present(self):
        txn = make_txn_declined()
        txn.cb_decline_reason = "R01"
        auth = MockAuthResult(approved=False, response_code="51")
        tpa = TPAResponse(txn, auth)
        assert "CBB" in tpa.fields
        assert "R01" in tpa.fields["CBB"]

    def test_fe1_tier_when_amount_decision(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        ad = MockAmountDecision()
        tpa = TPAResponse(txn, auth, amount_decision=ad)
        assert "FE1" in tpa.fields
        assert ad.tier.name in tpa.fields["FE1"]

    def test_fe2_risk_level_when_amount_decision(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        ad = MockAmountDecision()
        tpa = TPAResponse(txn, auth, amount_decision=ad)
        assert "FE2" in tpa.fields

    def test_fe3_auth_path(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        ad = MockAmountDecision()
        tpa = TPAResponse(txn, auth, amount_decision=ad)
        assert "FE3" in tpa.fields
        assert tpa.fields["FE3"] in ("ONLINE", "OFFLINE", "REFERRAL")

    def test_fe8_status(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FE8" in tpa.fields
        assert tpa.fields["FE8"] == "APPROVED"

    def test_fe9_transaction_id(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FE9" in tpa.fields
        assert tpa.fields["FE9"] == txn.id

    def test_ff1_timestamp(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FF1" in tpa.fields
        assert "Z" in tpa.fields["FF1"]

    def test_ff2_server_version(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FF2" in tpa.fields
        assert "EMV-AUTH" in tpa.fields["FF2"].upper() or "GIE" in tpa.fields["FF2"]

    def test_arqc_field_when_set(self):
        txn = make_txn_approved()
        txn.arqc = "AABBCCDD11223344"
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FE4" in tpa.fields
        assert tpa.fields["FE4"] == "AABBCCDD11223344"

    def test_arpc_field_when_set(self):
        txn = make_txn_approved()
        txn.arpc = "EEFF001122334455"
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "FE5" in tpa.fields

    def test_f55_set_when_issuer_auth_data(self):
        txn = make_txn_approved()
        txn.issuer_auth_data = "AABBCCDD11223344AABB"
        auth = MockAuthResult()
        tpa = TPAResponse(txn, auth)
        assert "F55" in tpa.fields
        assert "FE6" in tpa.fields


class TestTPAResponseToDict:
    def setup_method(self):
        self.txn = make_txn_approved()
        self.auth = MockAuthResult()
        self.tpa = TPAResponse(self.txn, self.auth)

    def test_returns_dict(self):
        assert isinstance(self.tpa.to_dict(), dict)

    def test_simple_values(self):
        d = self.tpa.to_dict(include_definitions=False)
        assert d["F00"] == "0110"
        assert d["F39"] == "00"

    def test_with_definitions_includes_name(self):
        d = self.tpa.to_dict(include_definitions=True)
        assert "name" in d["F00"]
        assert d["F00"]["name"] == "MTI"

    def test_with_definitions_includes_description(self):
        d = self.tpa.to_dict(include_definitions=True)
        assert "description" in d["F00"]

    def test_with_definitions_includes_value(self):
        d = self.tpa.to_dict(include_definitions=True)
        assert d["F00"]["value"] == "0110"

    def test_with_definitions_includes_format(self):
        d = self.tpa.to_dict(include_definitions=True)
        assert "format" in d["F00"]

    def test_field_without_definition_not_wrapped(self):
        d = self.tpa.to_dict(include_definitions=True)
        for k, v in d.items():
            if k not in TPA_FIELD_DEFINITIONS:
                assert not isinstance(v, dict) or "name" not in v


class TestTPAResponseToFlat:
    def test_returns_dict(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        assert isinstance(tpa.to_flat(), dict)

    def test_sorted_keys(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        keys = list(tpa.to_flat().keys())
        assert keys == sorted(keys)

    def test_same_values_as_fields(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        flat = tpa.to_flat()
        for k, v in flat.items():
            assert tpa.fields[k] == v


class TestTPAResponseToISO8583Like:
    def test_returns_string(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        result = tpa.to_iso8583_like()
        assert isinstance(result, str)

    def test_contains_mti(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        result = tpa.to_iso8583_like()
        assert "0110" in result

    def test_contains_border_characters(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        result = tpa.to_iso8583_like()
        assert "┌" in result or "─" in result

    def test_contains_field_ids(self):
        txn = make_txn_approved()
        tpa = TPAResponse(txn, MockAuthResult())
        result = tpa.to_iso8583_like()
        assert "F00" in result
        assert "F39" in result

    def test_list_values_joined(self):
        txn = make_txn_approved()
        auth = MockAuthResult()
        ad = MockAmountDecision()
        tpa = TPAResponse(txn, auth, amount_decision=ad)
        result = tpa.to_iso8583_like()
        assert isinstance(result, str)


class TestTpaFieldDefinitions:
    def test_f00_defined(self):
        assert "F00" in TPA_FIELD_DEFINITIONS
        assert TPA_FIELD_DEFINITIONS["F00"]["name"] == "MTI"

    def test_f02_pan_defined(self):
        assert "F02" in TPA_FIELD_DEFINITIONS

    def test_f04_amount_defined(self):
        assert "F04" in TPA_FIELD_DEFINITIONS

    def test_cb_fields_defined(self):
        for cb_field in ["CB1", "CB2", "CB4", "CB5", "CB8", "CBA"]:
            assert cb_field in TPA_FIELD_DEFINITIONS, f"{cb_field} manquant"

    def test_fe_fields_defined(self):
        for fe_field in ["FE1", "FE2", "FE3", "FE4", "FE5", "FE8", "FE9"]:
            assert fe_field in TPA_FIELD_DEFINITIONS, f"{fe_field} manquant"

    def test_ff_fields_defined(self):
        assert "FF0" in TPA_FIELD_DEFINITIONS
        assert "FF1" in TPA_FIELD_DEFINITIONS
        assert "FF2" in TPA_FIELD_DEFINITIONS

    def test_all_fields_have_name_description_format(self):
        for fid, defn in TPA_FIELD_DEFINITIONS.items():
            assert "name" in defn, f"{fid}: 'name' manquant"
            assert "description" in defn, f"{fid}: 'description' manquant"
            assert "format" in defn, f"{fid}: 'format' manquant"


class TestCBServiceIndicatorLabels:
    def test_01_national_cb(self):
        assert CB_SERVICE_INDICATOR_LABELS["01"] is not None

    def test_06_contactless_nfc(self):
        assert CB_SERVICE_INDICATOR_LABELS["06"] is not None
        assert "sans contact" in CB_SERVICE_INDICATOR_LABELS["06"].lower()

    def test_all_expected_indicators_present(self):
        for ind in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]:
            assert ind in CB_SERVICE_INDICATOR_LABELS, f"Indicateur {ind} manquant"


class TestSCAExemptionLabels:
    def test_lvp_defined(self):
        assert "LVP" in SCA_EXEMPTION_LABELS

    def test_tra_defined(self):
        assert "TRA" in SCA_EXEMPTION_LABELS

    def test_mit_defined(self):
        assert "MIT" in SCA_EXEMPTION_LABELS

    def test_none_defined(self):
        assert "NONE" in SCA_EXEMPTION_LABELS
