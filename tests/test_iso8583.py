"""
Tests unitaires — iso8583/message.py
Couvre : ISO8583Message (set/get_field, properties, to_dict, to_response),
         parse_from_dict, build_authorization_request
"""

import pytest
from iso8583.message import (
    ISO8583Message, parse_from_dict, build_authorization_request,
    ISO8583_FIELDS, PROCESSING_CODES,
)


class TestISO8583MessageInit:
    def test_default_mti(self):
        msg = ISO8583Message()
        assert msg.mti == "0100"

    def test_custom_mti(self):
        msg = ISO8583Message(mti="0110")
        assert msg.mti == "0110"

    def test_empty_fields(self):
        msg = ISO8583Message()
        assert msg.fields == {}


class TestISO8583MessageSetGet:
    def test_set_and_get_field(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        assert msg.get_field(2) == "4111111111111111"

    def test_get_missing_field_returns_none(self):
        msg = ISO8583Message()
        assert msg.get_field(99) is None

    def test_overwrite_field(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        msg.set_field(2, "5500000000000004")
        assert msg.get_field(2) == "5500000000000004"

    def test_multiple_fields(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        msg.set_field(4, "000000005000")
        assert msg.get_field(2) == "4111111111111111"
        assert msg.get_field(4) == "000000005000"


class TestISO8583MessageProperties:
    def test_pan_property(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        assert msg.pan == "4111111111111111"

    def test_pan_empty_when_not_set(self):
        msg = ISO8583Message()
        assert msg.pan == ""

    def test_amount_property(self):
        msg = ISO8583Message()
        msg.set_field(4, "000000005000")
        assert msg.amount == 5000

    def test_amount_zero_when_not_set(self):
        msg = ISO8583Message()
        assert msg.amount == 0

    def test_amount_invalid_returns_zero(self):
        msg = ISO8583Message()
        msg.set_field(4, "INVALID")
        assert msg.amount == 0

    def test_currency_code_default(self):
        msg = ISO8583Message()
        assert msg.currency_code == "840"

    def test_currency_code_set(self):
        msg = ISO8583Message()
        msg.set_field(49, "978")
        assert msg.currency_code == "978"

    def test_terminal_id_stripped(self):
        msg = ISO8583Message()
        msg.set_field(41, "TERM0001")
        assert msg.terminal_id == "TERM0001"

    def test_merchant_id_stripped(self):
        msg = ISO8583Message()
        msg.set_field(42, "MERCH001       ")
        assert msg.merchant_id == "MERCH001"

    def test_merchant_name_stripped(self):
        msg = ISO8583Message()
        msg.set_field(43, "TEST SHOP                ")
        assert "TEST SHOP" in msg.merchant_name

    def test_merchant_name_max_25(self):
        msg = ISO8583Message()
        msg.set_field(43, "A" * 50)
        assert len(msg.merchant_name) <= 25

    def test_emv_data_property(self):
        msg = ISO8583Message()
        msg.set_field(55, "9F360200A1")
        assert msg.emv_data == "9F360200A1"

    def test_emv_data_none_when_not_set(self):
        msg = ISO8583Message()
        assert msg.emv_data is None

    def test_expiry_property(self):
        msg = ISO8583Message()
        msg.set_field(14, "2812")
        assert msg.expiry == "2812"

    def test_pos_entry_mode_default(self):
        msg = ISO8583Message()
        assert msg.pos_entry_mode == "051"

    def test_pos_entry_mode_set(self):
        msg = ISO8583Message()
        msg.set_field(22, "071")
        assert msg.pos_entry_mode == "071"

    def test_rrn_property(self):
        msg = ISO8583Message()
        msg.set_field(37, "123456789012")
        assert msg.rrn == "123456789012"

    def test_transaction_type_from_processing_code(self):
        msg = ISO8583Message()
        msg.set_field(3, "000000")
        assert msg.transaction_type == "00"

    def test_transaction_type_cash_advance(self):
        msg = ISO8583Message()
        msg.set_field(3, "010000")
        assert msg.transaction_type == "01"


class TestISO8583MessageToDict:
    def test_returns_dict(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        d = msg.to_dict()
        assert isinstance(d, dict)

    def test_has_mti(self):
        msg = ISO8583Message()
        d = msg.to_dict()
        assert "mti" in d
        assert d["mti"] == "0100"

    def test_has_fields(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        d = msg.to_dict()
        assert "fields" in d
        assert "2" in d["fields"]

    def test_field_has_name_and_value(self):
        msg = ISO8583Message()
        msg.set_field(2, "4111111111111111")
        f = msg.to_dict()["fields"]["2"]
        assert "name" in f
        assert "value" in f

    def test_bytes_field_hex_encoded(self):
        msg = ISO8583Message()
        msg.set_field(52, bytes.fromhex("AABBCCDDEE112233"))
        f = msg.to_dict()["fields"]["52"]
        assert f["value"] == "AABBCCDDEE112233"


class TestISO8583MessageToResponse:
    def setup_method(self):
        self.req = ISO8583Message(mti="0100")
        self.req.set_field(2, "4111111111111111")
        self.req.set_field(3, "000000")
        self.req.set_field(4, "000000005000")
        self.req.set_field(41, "TERM0001")
        self.req.set_field(49, "978")

    def test_response_mti(self):
        resp = self.req.to_response("00")
        assert resp.mti == "0110"

    def test_copies_key_fields(self):
        resp = self.req.to_response("00")
        assert resp.get_field(2) == "4111111111111111"
        assert resp.get_field(3) == "000000"
        assert resp.get_field(4) == "000000005000"
        assert resp.get_field(49) == "978"

    def test_sets_response_code(self):
        resp = self.req.to_response("05")
        assert resp.get_field(39) == "05"

    def test_sets_auth_code(self):
        resp = self.req.to_response("00", auth_code="ABCDEF")
        assert resp.get_field(38) == "ABCDEF"

    def test_auth_code_padded_to_6(self):
        resp = self.req.to_response("00", auth_code="123")
        auth = resp.get_field(38)
        assert len(auth) == 6

    def test_no_auth_code_field_when_none(self):
        resp = self.req.to_response("05")
        assert resp.get_field(38) is None

    def test_sets_field55_response(self):
        resp = self.req.to_response("00", field_55_response="9F360200A1")
        assert resp.get_field(55) == "9F360200A1"


class TestParseFromDict:
    def test_basic_parse(self):
        data = {
            "mti": "0100",
            "fields": {
                "2": "4111111111111111",
                "4": "000000005000",
            },
        }
        msg = parse_from_dict(data)
        assert msg.mti == "0100"
        assert msg.get_field(2) == "4111111111111111"
        assert msg.get_field(4) == "000000005000"

    def test_default_mti(self):
        msg = parse_from_dict({"fields": {}})
        assert msg.mti == "0100"

    def test_nested_value_format(self):
        data = {
            "fields": {
                "2": {"name": "PAN", "value": "4111111111111111"},
            }
        }
        msg = parse_from_dict(data)
        assert msg.get_field(2) == "4111111111111111"

    def test_invalid_field_number_skipped(self):
        data = {
            "fields": {
                "not_a_number": "value",
                "2": "4111111111111111",
            }
        }
        msg = parse_from_dict(data)
        assert msg.get_field(2) == "4111111111111111"

    def test_empty_fields(self):
        msg = parse_from_dict({"fields": {}})
        assert msg.fields == {}


class TestBuildAuthorizationRequest:
    def test_mti_0100(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.mti == "0100"

    def test_pan_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.pan == "4111111111111111"

    def test_amount_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.amount == 5000

    def test_currency_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.currency_code == "978"

    def test_transmission_date_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.get_field(7) is not None
        assert len(msg.get_field(7)) == 10

    def test_pos_entry_mode_default(self):
        msg = build_authorization_request("4111111111111111", 5000, "978")
        assert msg.pos_entry_mode == "051"

    def test_terminal_id_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978",
                                          terminal_id="TERM0001")
        assert "TERM0001" in msg.terminal_id

    def test_emv_data_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978",
                                          emv_data="9F360200A1")
        assert msg.emv_data == "9F360200A1"

    def test_expiry_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978",
                                          expiry="2812")
        assert msg.expiry == "2812"

    def test_merchant_name_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978",
                                          merchant_name="TEST SHOP")
        assert "TEST SHOP" in msg.merchant_name

    def test_stan_set(self):
        msg = build_authorization_request("4111111111111111", 5000, "978",
                                          stan="000042")
        assert msg.get_field(11) == "000042"


class TestProcessingCodesDict:
    def test_00_is_purchase(self):
        assert PROCESSING_CODES["00"] == "Purchase"

    def test_01_is_cash_advance(self):
        assert PROCESSING_CODES["01"] == "Cash Advance"

    def test_20_is_refund(self):
        assert "Refund" in PROCESSING_CODES["20"] or "Credit" in PROCESSING_CODES["20"]
