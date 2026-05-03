"""
Tests E3 — DDA / CDA Authentification Offline Dynamique
"""
import os
import pytest
from emv.dda_cda import (
    sign_dda, verify_dda, sign_cda, verify_cda,
    detect_offline_auth_type, verify_offline_auth,
    is_available_dda_cda,
)
from emv.pki import is_available as pki_available


pytestmark = pytest.mark.skipif(
    not pki_available(),
    reason="Module cryptography / PKI non disponible"
)

PAN  = "4111111111111111"
PAN2 = "5500000000000004"
UN   = bytes.fromhex("A1B2C3D4")


# ── Tests DDA ─────────────────────────────────────────────────────────────────

class TestDDA:

    def test_sign_dda_success(self):
        res = sign_dda(PAN, UN)
        assert res["success"] is True
        assert res["sdad_hex"] is not None
        assert len(res["sdad_hex"]) > 0

    def test_sign_dda_auth_type(self):
        res = sign_dda(PAN, UN)
        assert res["auth_type"] == "DDA"

    def test_sign_dda_un_hex_matches(self):
        res = sign_dda(PAN, UN)
        assert res["un_hex"].upper() == UN.hex().upper()

    def test_sign_dda_no_un_generates_random(self):
        res = sign_dda(PAN)
        assert res["success"] is True
        assert res["un_hex"] is not None

    def test_verify_dda_valid_signature(self):
        signed = sign_dda(PAN, UN)
        vres   = verify_dda(PAN, signed["sdad_hex"], signed["un_hex"])
        assert vres["valid"] is True
        assert vres["auth_type"] == "DDA"

    def test_verify_dda_wrong_pan(self):
        signed = sign_dda(PAN, UN)
        vres   = verify_dda(PAN2, signed["sdad_hex"], signed["un_hex"])
        assert vres["valid"] is False

    def test_verify_dda_tampered_signature(self):
        signed = sign_dda(PAN, UN)
        tampered = "FF" * (len(signed["sdad_hex"]) // 2)
        vres = verify_dda(PAN, tampered, signed["un_hex"])
        assert vres["valid"] is False

    def test_verify_dda_wrong_un(self):
        signed = sign_dda(PAN, UN)
        vres   = verify_dda(PAN, signed["sdad_hex"], "DEADBEEF")
        assert vres["valid"] is False

    def test_sign_dda_has_signed_at(self):
        res = sign_dda(PAN, UN)
        assert "signed_at" in res

    def test_roundtrip_different_pans_independent(self):
        s1 = sign_dda(PAN, UN)
        s2 = sign_dda(PAN2, UN)
        assert s1["sdad_hex"] != s2["sdad_hex"]

        v1 = verify_dda(PAN, s1["sdad_hex"], s1["un_hex"])
        v2 = verify_dda(PAN2, s2["sdad_hex"], s2["un_hex"])
        assert v1["valid"] is True
        assert v2["valid"] is True

    def test_cross_signature_invalid(self):
        s1 = sign_dda(PAN, UN)
        s2 = sign_dda(PAN2, UN)
        v = verify_dda(PAN, s2["sdad_hex"], s2["un_hex"])
        assert v["valid"] is False


# ── Tests CDA ─────────────────────────────────────────────────────────────────

class TestCDA:

    ARQC = "A1B2C3D4E5F60708"

    def test_sign_cda_success(self):
        res = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        assert res["success"] is True
        assert res["sdad_hex"] is not None

    def test_sign_cda_auth_type(self):
        res = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        assert res["auth_type"] == "CDA"

    def test_sign_cda_cid_hex_present(self):
        res = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        assert "cid_hex" in res

    def test_verify_cda_valid(self):
        signed = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        vres   = verify_cda(PAN, signed["sdad_hex"], signed["un_hex"], self.ARQC)
        assert vres["valid"] is True
        assert vres["auth_type"] == "CDA"

    def test_verify_cda_wrong_arqc(self):
        signed = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        vres   = verify_cda(PAN, signed["sdad_hex"], signed["un_hex"],
                            "0000000000000000")
        assert vres["valid"] is False

    def test_verify_cda_wrong_pan(self):
        signed = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        vres   = verify_cda(PAN2, signed["sdad_hex"], signed["un_hex"], self.ARQC)
        assert vres["valid"] is False

    def test_verify_cda_no_arqc(self):
        signed = sign_cda(PAN, UN)
        vres   = verify_cda(PAN, signed["sdad_hex"], signed["un_hex"], None)
        assert vres["valid"] is True  # signed and verified with same (no) ARQC

    def test_cda_different_from_dda(self):
        dda_signed = sign_dda(PAN, UN)
        cda_signed = sign_cda(PAN, UN, arqc_hex=self.ARQC)
        assert dda_signed["sdad_hex"] != cda_signed["sdad_hex"]


# ── Tests detect_offline_auth_type ────────────────────────────────────────────

class TestDetectAuthType:

    def test_detect_dda_from_sdad(self):
        emv = {"sdad": b"\xAA" * 128}
        assert detect_offline_auth_type(emv) == "DDA"

    def test_detect_cda_from_sdad_and_cid(self):
        emv = {"sdad": b"\xBB" * 128, "cryptogram_info": bytes([0x90])}
        assert detect_offline_auth_type(emv) == "CDA"

    def test_detect_sda_from_ssad(self):
        emv = {"ssad": b"\xCC" * 128}
        assert detect_offline_auth_type(emv) == "SDA"

    def test_detect_none_no_tags(self):
        assert detect_offline_auth_type({}) == "NONE"

    def test_detect_none_empty(self):
        assert detect_offline_auth_type({"tvr": b"\x00\x00\x00\x00\x00"}) == "NONE"


# ── Tests verify_offline_auth ──────────────────────────────────────────────────

class TestVerifyOfflineAuth:

    def test_skip_true_always_valid(self):
        res = verify_offline_auth(PAN, {}, skip=True)
        assert res["valid"] is True
        assert res["auth_type"] == "SKIPPED"

    def test_no_sdad_returns_none_type_valid(self):
        res = verify_offline_auth(PAN, {})
        assert res["valid"] is True
        assert res["auth_type"] == "NONE"

    def test_valid_dda_roundtrip_via_emv_parsed(self):
        signed = sign_dda(PAN, UN)
        sdad_bytes = bytes.fromhex(signed["sdad_hex"])
        emv = {
            "sdad": sdad_bytes,
            "unpredictable_number": UN,
        }
        res = verify_offline_auth(PAN, emv)
        assert res["valid"] is True
        assert res["auth_type"] == "DDA"

    def test_invalid_dda_fails(self):
        emv = {
            "sdad": b"\xAA" * 128,
            "unpredictable_number": UN,
        }
        res = verify_offline_auth(PAN, emv)
        assert res["valid"] is False


# ── Tests is_available_dda_cda ────────────────────────────────────────────────

class TestIsAvailable:

    def test_returns_bool(self):
        result = is_available_dda_cda()
        assert isinstance(result, bool)

    def test_returns_true_when_crypto_available(self):
        assert is_available_dda_cda() is True
