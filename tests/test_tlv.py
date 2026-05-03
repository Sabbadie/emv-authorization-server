"""
Tests unitaires — emv/tlv.py
Couvre : parse, parse_one, find_tag, find_all_tags, encode_tag,
         encode_length, encode, encode_constructed, extract_emv_fields,
         TLV properties (tag_hex, value_hex, name, is_constructed)
"""

import pytest
from emv.tlv import (
    TLV, TLVError,
    parse, parse_one, find_tag, find_all_tags,
    encode_tag, encode_length, encode, encode_constructed,
    extract_emv_fields, tlv_list_to_hex,
)

AMOUNT_TAG  = bytes.fromhex("9F020600000000500095050000000000")
SIMPLE_TLV  = bytes.fromhex("9F360200A1")
TWO_TLVS    = bytes.fromhex("9F360200A19C0100")
TEMPLATE_70 = bytes.fromhex("70089F360200A19C0100")


class TestTLVClass:
    def test_tag_hex_1_byte(self):
        t = TLV(0x5A, b"\x41\x11")
        assert t.tag_hex == "5A"

    def test_tag_hex_2_bytes(self):
        t = TLV(0x9F36, b"\x00\x05")
        assert t.tag_hex == "9F36"

    def test_tag_hex_3_bytes(self):
        t = TLV(0x9F8101, b"\x00")
        assert len(t.tag_hex) == 6

    def test_value_hex_uppercase(self):
        t = TLV(0x5A, bytes.fromhex("aabbcc"))
        assert t.value_hex == "AABBCC"

    def test_value_hex_empty(self):
        t = TLV(0x5A, b"")
        assert t.value_hex == ""

    def test_name_known_tag(self):
        t = TLV(0x9F36, b"\x00\x05")
        assert "Transaction" in t.name or t.name != "Unknown Tag 0x9F36"

    def test_name_unknown_tag(self):
        t = TLV(0xDEAD, b"\x00")
        assert "Unknown" in t.name or "DEAD" in t.name.upper()

    def test_is_constructed_primitive_tag(self):
        t = TLV(0x9F36, b"\x00\x05")
        assert t.is_constructed is False

    def test_is_constructed_constructed_tag(self):
        t = TLV(0x70, b"\x00")
        assert t.is_constructed is True

    def test_is_constructed_6f_template(self):
        t = TLV(0x6F, b"\x00")
        assert t.is_constructed is True

    def test_to_dict_primitive(self):
        t = TLV(0x9C, b"\x00")
        d = t.to_dict()
        assert "tag" in d
        assert "value" in d
        assert "length" in d
        assert d["length"] == 1

    def test_to_dict_constructed_with_children(self):
        child = TLV(0x9C, b"\x00")
        parent = TLV(0x70, b"\x9C\x01\x00", children=[child])
        d = parent.to_dict()
        assert "children" in d
        assert len(d["children"]) == 1

    def test_repr_primitive(self):
        t = TLV(0x9C, b"\x00")
        assert "9C" in repr(t).upper() or "0x9C" in repr(t).upper()

    def test_repr_constructed(self):
        child = TLV(0x9C, b"\x00")
        t = TLV(0x70, b"\x9C\x01\x00", children=[child])
        assert "children" in repr(t)


class TestParse:
    def test_parse_single_primitive_bytes(self):
        results = parse(bytes.fromhex("9F360200A1"))
        assert len(results) == 1
        assert results[0].tag == 0x9F36
        assert results[0].value == b"\x00\xA1"

    def test_parse_single_primitive_hex_string(self):
        results = parse("9F360200A1")
        assert len(results) == 1

    def test_parse_multiple_primitives(self):
        results = parse(TWO_TLVS)
        assert len(results) == 2
        tags = {t.tag for t in results}
        assert 0x9F36 in tags
        assert 0x9C in tags

    def test_parse_empty_bytes(self):
        assert parse(b"") == []

    def test_parse_empty_string(self):
        assert parse("") == []

    def test_parse_skips_00_padding(self):
        data = bytes.fromhex("009F360200A1")
        results = parse(data)
        assert len(results) == 1

    def test_parse_skips_FF_padding(self):
        data = bytes.fromhex("FF9F360200A1")
        results = parse(data)
        assert len(results) == 1

    def test_parse_constructed_template(self):
        results = parse(TEMPLATE_70)
        assert len(results) == 1
        assert results[0].tag == 0x70
        assert results[0].is_constructed is True
        assert len(results[0].children) == 2

    def test_parse_long_length_multi_byte(self):
        value = bytes(200)
        data = bytes([0x9C, 0x81, 200]) + value
        results = parse(data)
        assert len(results) == 1
        assert len(results[0].value) == 200

    def test_parse_raises_on_truncated_value(self):
        data = bytes.fromhex("9F0602FF")
        with pytest.raises(TLVError):
            parse(data)

    def test_parse_raises_indefinite_length(self):
        data = bytes([0x9C, 0x80, 0x00])
        with pytest.raises(TLVError):
            parse(data)

    def test_parse_known_emv_field55(self):
        emv = (
            "9F02060000000050009F03060000000000009F1A020250"
            "950500000000009A032601019C0100"
        )
        results = parse(emv)
        assert len(results) >= 5
        tags = {t.tag for t in results}
        assert 0x9F02 in tags
        assert 0x9C in tags


class TestParseOne:
    def test_returns_first_element(self):
        t = parse_one(TWO_TLVS)
        assert t.tag == 0x9F36

    def test_raises_on_empty(self):
        with pytest.raises(TLVError):
            parse_one(b"")


class TestFindTag:
    def setup_method(self):
        self.tlv_list = parse(TWO_TLVS)

    def test_find_existing_tag(self):
        t = find_tag(self.tlv_list, 0x9F36)
        assert t is not None
        assert t.tag == 0x9F36

    def test_find_second_tag(self):
        t = find_tag(self.tlv_list, 0x9C)
        assert t is not None

    def test_returns_none_for_missing(self):
        t = find_tag(self.tlv_list, 0x5A)
        assert t is None

    def test_finds_tag_in_children(self):
        results = parse(TEMPLATE_70)
        t = find_tag(results, 0x9C)
        assert t is not None
        assert t.tag == 0x9C

    def test_empty_list_returns_none(self):
        assert find_tag([], 0x9C) is None


class TestFindAllTags:
    def test_finds_multiple(self):
        data = bytes.fromhex("9C01009C0100")
        tlv_list = parse(data)
        results = find_all_tags(tlv_list, 0x9C)
        assert len(results) == 2

    def test_returns_empty_for_missing(self):
        results = find_all_tags(parse(TWO_TLVS), 0x5A)
        assert results == []

    def test_finds_in_children(self):
        tlv_list = parse(TEMPLATE_70)
        results = find_all_tags(tlv_list, 0x9C)
        assert len(results) >= 1


class TestEncodeTag:
    def test_1_byte_tag(self):
        assert encode_tag(0x9C) == b"\x9C"

    def test_2_byte_tag(self):
        assert encode_tag(0x9F36) == b"\x9F\x36"

    def test_3_byte_tag(self):
        result = encode_tag(0x9F8101)
        assert len(result) == 3

    def test_4_byte_tag(self):
        result = encode_tag(0x9F810101)
        assert len(result) == 4


class TestEncodeLength:
    def test_short_form(self):
        assert encode_length(0) == b"\x00"
        assert encode_length(127) == b"\x7F"

    def test_long_form_1_byte(self):
        data = encode_length(128)
        assert data[0] == 0x81
        assert data[1] == 128
        assert len(data) == 2

    def test_long_form_2_bytes(self):
        data = encode_length(256)
        assert data[0] == 0x82
        assert len(data) == 3

    def test_raises_too_large(self):
        with pytest.raises(TLVError):
            encode_length(0x10000)


class TestEncode:
    def test_encode_bytes_value(self):
        data = encode(0x9C, b"\x00")
        assert data == b"\x9C\x01\x00"

    def test_encode_hex_string_value(self):
        data = encode(0x9C, "00")
        assert data == b"\x9C\x01\x00"

    def test_encode_multi_byte_tag(self):
        data = encode(0x9F36, b"\x00\x05")
        assert data[:2] == b"\x9F\x36"
        assert data[2] == 0x02
        assert data[3:] == b"\x00\x05"

    def test_roundtrip(self):
        original = encode(0x9F36, b"\x00\xA1")
        parsed = parse(original)
        assert len(parsed) == 1
        assert parsed[0].tag == 0x9F36
        assert parsed[0].value == b"\x00\xA1"


class TestEncodeConstructed:
    def test_simple_template(self):
        data = encode_constructed(0x70, [(0x9C, b"\x00"), (0x9F36, b"\x00\x05")])
        parsed = parse(data)
        assert len(parsed) == 1
        assert parsed[0].tag == 0x70
        assert parsed[0].is_constructed

    def test_children_accessible(self):
        data = encode_constructed(0x70, [(0x9C, b"\x00")])
        parsed = parse(data)
        child = find_tag(parsed, 0x9C)
        assert child is not None


class TestTlvListToHex:
    def test_returns_uppercase_hex(self):
        tlv_list = parse(TWO_TLVS)
        result = tlv_list_to_hex(tlv_list)
        assert result == result.upper()

    def test_can_be_parsed_back(self):
        original = parse(TWO_TLVS)
        hex_str = tlv_list_to_hex(original)
        reparsed = parse(hex_str)
        assert len(reparsed) == len(original)


class TestExtractEMVFields:
    def test_returns_dict(self):
        result = extract_emv_fields(TWO_TLVS.hex())
        assert isinstance(result, dict)

    def test_contains_expected_tags(self):
        result = extract_emv_fields(TWO_TLVS.hex())
        assert "9F36" in result
        assert "9C" in result

    def test_field_structure(self):
        result = extract_emv_fields(TWO_TLVS.hex())
        field = result["9C"]
        assert "name" in field
        assert "value" in field
        assert "length" in field

    def test_invalid_hex_returns_error(self):
        result = extract_emv_fields("ZZZZZZ")
        assert "error" in result

    def test_empty_hex_returns_empty(self):
        result = extract_emv_fields("")
        assert result == {}
