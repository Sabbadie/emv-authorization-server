"""
Tests unitaires — emv/cvv.py
Couvre : _compute_cvv_raw, compute_cvv1, compute_cvv2, compute_icvv,
         verify_cvv, generate_cvv_set
"""

import pytest
from emv.cvv import (
    CVVError, _compute_cvv_raw,
    compute_cvv1, compute_cvv2, compute_icvv,
    verify_cvv, generate_cvv_set,
)

CVK1 = bytes.fromhex("0123456789ABCDEF")
CVK2 = bytes.fromhex("FEDCBA9876543210")
PAN  = "4111111111111111"
EXP  = "2812"


class TestComputeCVVRaw:
    def test_returns_string_of_digits(self):
        raw = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        assert raw.isdigit()

    def test_returns_16_chars(self):
        raw = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        assert 0 < len(raw) <= 16

    def test_deterministic(self):
        r1 = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        r2 = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        assert r1 == r2

    def test_different_service_code_different_result(self):
        r1 = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        r2 = _compute_cvv_raw(PAN, EXP, "999", CVK1, CVK2)
        assert r1 != r2

    def test_different_pan_different_result(self):
        r1 = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        r2 = _compute_cvv_raw("5500000000000004", EXP, "101", CVK1, CVK2)
        assert r1 != r2

    def test_different_expiry_different_result(self):
        r1 = _compute_cvv_raw(PAN, "2812", "101", CVK1, CVK2)
        r2 = _compute_cvv_raw(PAN, "2912", "101", CVK1, CVK2)
        assert r1 != r2

    def test_bad_cvk_size_raises(self):
        with pytest.raises(CVVError):
            _compute_cvv_raw(PAN, EXP, "101", b"\x00" * 7, CVK2)

    def test_bad_pan_raises(self):
        with pytest.raises(CVVError):
            _compute_cvv_raw("ABCD1234EFGH5678", EXP, "101", CVK1, CVK2)

    def test_bad_expiry_raises(self):
        with pytest.raises(CVVError):
            _compute_cvv_raw(PAN, "28", "101", CVK1, CVK2)

    def test_pan_with_spaces(self):
        r1 = _compute_cvv_raw("4111 1111 1111 1111", EXP, "101", CVK1, CVK2)
        r2 = _compute_cvv_raw(PAN, EXP, "101", CVK1, CVK2)
        assert r1 == r2


class TestComputeCVV1:
    def test_default_length_3(self):
        cvv1 = compute_cvv1(PAN, EXP, CVK1, CVK2)
        assert len(cvv1) == 3

    def test_digits_only(self):
        cvv1 = compute_cvv1(PAN, EXP, CVK1, CVK2)
        assert cvv1.isdigit()

    def test_deterministic(self):
        assert compute_cvv1(PAN, EXP, CVK1, CVK2) == compute_cvv1(PAN, EXP, CVK1, CVK2)

    def test_custom_digits(self):
        cvv1_4 = compute_cvv1(PAN, EXP, CVK1, CVK2, digits=4)
        assert len(cvv1_4) == 4

    def test_custom_service_code(self):
        c1 = compute_cvv1(PAN, EXP, CVK1, CVK2, service_code="101")
        c2 = compute_cvv1(PAN, EXP, CVK1, CVK2, service_code="201")
        assert c1 != c2

    def test_different_pan(self):
        c1 = compute_cvv1(PAN, EXP, CVK1, CVK2)
        c2 = compute_cvv1("5500000000000004", EXP, CVK1, CVK2)
        assert c1 != c2

    def test_different_expiry(self):
        c1 = compute_cvv1(PAN, "2812", CVK1, CVK2)
        c2 = compute_cvv1(PAN, "2912", CVK1, CVK2)
        assert c1 != c2


class TestComputeCVV2:
    def test_default_length_3(self):
        cvv2 = compute_cvv2(PAN, EXP, CVK1, CVK2)
        assert len(cvv2) == 3

    def test_digits_only(self):
        cvv2 = compute_cvv2(PAN, EXP, CVK1, CVK2)
        assert cvv2.isdigit()

    def test_different_from_cvv1(self):
        cvv1 = compute_cvv1(PAN, EXP, CVK1, CVK2)
        cvv2 = compute_cvv2(PAN, EXP, CVK1, CVK2)
        assert cvv1 != cvv2, "CVV2 doit différer de CVV1 (code de service différent)"

    def test_deterministic(self):
        assert compute_cvv2(PAN, EXP, CVK1, CVK2) == compute_cvv2(PAN, EXP, CVK1, CVK2)

    def test_custom_digits_4(self):
        cvv2 = compute_cvv2(PAN, EXP, CVK1, CVK2, digits=4)
        assert len(cvv2) == 4


class TestComputeICVV:
    def test_default_length_3(self):
        icvv = compute_icvv(PAN, EXP, CVK1, CVK2)
        assert len(icvv) == 3

    def test_digits_only(self):
        icvv = compute_icvv(PAN, EXP, CVK1, CVK2)
        assert icvv.isdigit()

    def test_same_as_cvv2(self):
        icvv = compute_icvv(PAN, EXP, CVK1, CVK2)
        cvv2 = compute_cvv2(PAN, EXP, CVK1, CVK2)
        assert icvv == cvv2, "iCVV utilise le même algorithme que CVV2 (service code 999)"

    def test_deterministic(self):
        assert compute_icvv(PAN, EXP, CVK1, CVK2) == compute_icvv(PAN, EXP, CVK1, CVK2)


class TestVerifyCVV:
    def setup_method(self):
        self.cvv1  = compute_cvv1(PAN, EXP, CVK1, CVK2)
        self.cvv2  = compute_cvv2(PAN, EXP, CVK1, CVK2)
        self.icvv  = compute_icvv(PAN, EXP, CVK1, CVK2)

    def test_valid_cvv2_returns_true(self):
        assert verify_cvv(self.cvv2, PAN, EXP, CVK1, CVK2, cvv_type="CVV2") is True

    def test_invalid_cvv2_returns_false(self):
        wrong = str((int(self.cvv2) + 1) % 1000).zfill(3)
        assert verify_cvv(wrong, PAN, EXP, CVK1, CVK2, cvv_type="CVV2") is False

    def test_valid_cvv1_returns_true(self):
        assert verify_cvv(self.cvv1, PAN, EXP, CVK1, CVK2, cvv_type="CVV1") is True

    def test_invalid_cvv1_returns_false(self):
        wrong = str((int(self.cvv1) + 1) % 1000).zfill(3)
        assert verify_cvv(wrong, PAN, EXP, CVK1, CVK2, cvv_type="CVV1") is False

    def test_valid_icvv_returns_true(self):
        assert verify_cvv(self.icvv, PAN, EXP, CVK1, CVK2, cvv_type="iCVV") is True

    def test_wrong_type_string_returns_false(self):
        assert verify_cvv(self.cvv2, PAN, EXP, CVK1, CVK2, cvv_type="UNKNOWN") is False

    def test_empty_cvv_returns_false(self):
        assert verify_cvv("", PAN, EXP, CVK1, CVK2) is False

    def test_whitespace_cvv_returns_false(self):
        assert verify_cvv("   ", PAN, EXP, CVK1, CVK2) is False

    def test_non_digit_cvv_returns_false(self):
        assert verify_cvv("abc", PAN, EXP, CVK1, CVK2) is False

    def test_cvv2_with_leading_zero(self):
        raw = _compute_cvv_raw(PAN, EXP, "999", CVK1, CVK2)
        cvv = raw[:3].zfill(3)
        assert verify_cvv(cvv, PAN, EXP, CVK1, CVK2, cvv_type="CVV2") is True

    def test_wrong_pan_returns_false(self):
        assert verify_cvv(self.cvv2, "5500000000000004", EXP, CVK1, CVK2) is False

    def test_wrong_expiry_returns_false(self):
        assert verify_cvv(self.cvv2, PAN, "2912", CVK1, CVK2) is False

    def test_4_digit_cvv(self):
        cvv4 = compute_cvv2(PAN, EXP, CVK1, CVK2, digits=4)
        assert verify_cvv(cvv4, PAN, EXP, CVK1, CVK2, cvv_type="CVV2") is True


class TestGenerateCVVSet:
    def test_returns_three_keys(self):
        result = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert "cvv1" in result
        assert "cvv2" in result
        assert "icvv" in result

    def test_all_3_digit_strings(self):
        result = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert len(result["cvv1"]) == 3
        assert len(result["cvv2"]) == 3
        assert len(result["icvv"]) == 3

    def test_all_digit_strings(self):
        result = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert result["cvv1"].isdigit()
        assert result["cvv2"].isdigit()
        assert result["icvv"].isdigit()

    def test_cvv1_differs_from_cvv2(self):
        result = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert result["cvv1"] != result["cvv2"]

    def test_cvv2_equals_icvv(self):
        result = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert result["cvv2"] == result["icvv"]

    def test_bad_keys_returns_error(self):
        result = generate_cvv_set(PAN, EXP, b"\x00" * 7, CVK2)
        assert "error" in result

    def test_deterministic(self):
        r1 = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        r2 = generate_cvv_set(PAN, EXP, CVK1, CVK2)
        assert r1 == r2
