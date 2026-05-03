"""
Tests C2 — PKI Simulée CB (Certificats Émetteurs)
"""
import pytest
from emv.pki import (
    get_ca_key_pair, get_issuer_key_pair, get_icc_key_pair,
    build_issuer_cert, build_icc_cert, get_full_pki_info,
    is_available, _sign_data, _verify_signature,
)


pytestmark = pytest.mark.skipif(
    not is_available(),
    reason="Module cryptography non disponible"
)

PAN  = "4111111111111111"
PAN2 = "5500000000000004"
PAN3 = "4970100000000154"


# ── Tests disponibilité ───────────────────────────────────────────────────────

class TestAvailability:

    def test_is_available(self):
        assert is_available() is True


# ── Tests CA Key ──────────────────────────────────────────────────────────────

class TestCAKey:

    def test_ca_key_pair_returns_two_objects(self):
        priv, pub = get_ca_key_pair()
        assert priv is not None
        assert pub is not None

    def test_ca_key_stable_across_calls(self):
        priv1, _ = get_ca_key_pair()
        priv2, _ = get_ca_key_pair()
        # Same object (cached)
        assert priv1 is priv2

    def test_ca_key_size(self):
        priv, _ = get_ca_key_pair()
        assert priv.key_size == 1024


# ── Tests Issuer Key ──────────────────────────────────────────────────────────

class TestIssuerKey:

    def test_issuer_key_returned(self):
        priv, pub = get_issuer_key_pair(PAN)
        assert priv is not None

    def test_same_bin_same_key(self):
        priv1, _ = get_issuer_key_pair("4111111111111111")
        priv2, _ = get_issuer_key_pair("4970100000000154")
        # Même premier chiffre (BIN '4') → même clé
        assert priv1 is priv2

    def test_different_bin_different_key(self):
        priv4, _ = get_issuer_key_pair("4111111111111111")  # BIN 4
        priv5, _ = get_issuer_key_pair("5500000000000004")  # BIN 5
        assert priv4 is not priv5


# ── Tests ICC Key ──────────────────────────────────────────────────────────────

class TestICCKey:

    def test_icc_key_returned(self):
        priv, pub = get_icc_key_pair(PAN)
        assert priv is not None
        assert pub is not None

    def test_same_pan_same_key(self):
        priv1, _ = get_icc_key_pair(PAN)
        priv2, _ = get_icc_key_pair(PAN)
        assert priv1 is priv2

    def test_different_pans_different_keys(self):
        priv1, _ = get_icc_key_pair(PAN)
        priv2, _ = get_icc_key_pair(PAN2)
        assert priv1 is not priv2

    def test_key_size(self):
        priv, _ = get_icc_key_pair(PAN)
        assert priv.key_size == 1024


# ── Tests Sign/Verify ──────────────────────────────────────────────────────────

class TestSignVerify:

    def test_sign_and_verify_roundtrip(self):
        priv, pub = get_icc_key_pair(PAN)
        data = b"test_dynamic_data_12345"
        sig = _sign_data(priv, data)
        assert _verify_signature(pub, data, sig)

    def test_tampered_data_fails(self):
        priv, pub = get_icc_key_pair(PAN)
        data = b"test_dynamic_data_12345"
        sig = _sign_data(priv, data)
        assert not _verify_signature(pub, b"tampered_data", sig)

    def test_wrong_key_fails(self):
        priv1, pub1 = get_icc_key_pair(PAN)
        priv2, pub2 = get_icc_key_pair(PAN2)
        data = b"some_data"
        sig = _sign_data(priv1, data)
        assert not _verify_signature(pub2, data, sig)


# ── Tests Issuer Certificate ──────────────────────────────────────────────────

class TestIssuerCert:

    def test_build_issuer_cert_returns_dict(self):
        cert = build_issuer_cert(PAN)
        assert cert.get("available") is True

    def test_issuer_cert_tags_present(self):
        cert = build_issuer_cert(PAN)
        assert "tag_8F" in cert
        assert "tag_90" in cert
        assert "tag_9F32" in cert

    def test_tag_8F_value(self):
        from emv.pki import CA_KEY_INDEX
        cert = build_issuer_cert(PAN)
        assert cert["tag_8F"] == bytes([CA_KEY_INDEX])

    def test_tag_90_is_bytes(self):
        cert = build_issuer_cert(PAN)
        assert isinstance(cert["tag_90"], bytes)
        assert len(cert["tag_90"]) > 0

    def test_issuer_modulus_present(self):
        cert = build_issuer_cert(PAN)
        assert "issuer_modulus" in cert
        assert len(cert["issuer_modulus"]) == 128  # 1024-bit / 8


# ── Tests ICC Certificate ──────────────────────────────────────────────────────

class TestICCCert:

    def test_build_icc_cert_returns_dict(self):
        cert = build_icc_cert(PAN)
        assert cert.get("available") is True

    def test_icc_cert_tags_present(self):
        cert = build_icc_cert(PAN)
        assert "tag_9F46" in cert
        assert "tag_9F47" in cert

    def test_tag_9F46_is_bytes(self):
        cert = build_icc_cert(PAN)
        assert isinstance(cert["tag_9F46"], bytes)
        assert len(cert["tag_9F46"]) > 0

    def test_tag_9F47_contains_exponent(self):
        cert = build_icc_cert(PAN)
        assert isinstance(cert["tag_9F47"], bytes)
        # RSA exponent 65537 = 0x010001 → 3 octets
        assert len(cert["tag_9F47"]) >= 3

    def test_icc_modulus_length(self):
        cert = build_icc_cert(PAN)
        assert len(cert["icc_modulus"]) == 128


# ── Tests get_full_pki_info ────────────────────────────────────────────────────

class TestFullPKIInfo:

    def test_returns_dict_with_available_true(self):
        info = get_full_pki_info(PAN)
        assert info["available"] is True

    def test_pan_last4_matches(self):
        info = get_full_pki_info(PAN)
        assert info["pan_last4"] == PAN[-4:]

    def test_hex_fields_present(self):
        info = get_full_pki_info(PAN)
        assert "ca_modulus_hex" in info
        assert "issuer_cert_hex" in info
        assert "icc_cert_hex" in info

    def test_ca_key_index_hex(self):
        info = get_full_pki_info(PAN)
        assert info["ca_key_index"].startswith("0x")

    def test_different_pans_different_icc_certs(self):
        info1 = get_full_pki_info(PAN)
        info2 = get_full_pki_info(PAN2)
        assert info1["icc_cert_hex"] != info2["icc_cert_hex"]
