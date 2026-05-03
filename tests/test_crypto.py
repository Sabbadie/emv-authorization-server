"""
Tests unitaires — emv/crypto.py
Couvre : _adjust_parity, derive_session_key, derive_udk,
         compute_arqc, verify_arqc, generate_arpc,
         generate_issuer_auth_data, encrypt_pin_block, compute_mac
"""

import pytest
from emv.crypto import (
    _adjust_parity, derive_session_key, derive_udk,
    compute_arqc, verify_arqc, generate_arpc,
    generate_issuer_auth_data, encrypt_pin_block, compute_mac,
    CryptoError,
)

MDK = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")
PAN = "4111111111111111"
PSN = "01"
ATC = 5


def has_odd_parity(byte):
    return bin(byte).count("1") % 2 == 1


class TestAdjustParity:
    def test_all_bytes_have_odd_parity(self):
        data = bytes(range(256))
        result = _adjust_parity(data)
        assert all(has_odd_parity(b) for b in result)

    def test_length_preserved(self):
        data = bytes(range(16))
        result = _adjust_parity(data)
        assert len(result) == 16

    def test_already_odd_parity_unchanged(self):
        data = bytes([0x01, 0x03, 0x07])
        result = _adjust_parity(data)
        for b in result:
            assert has_odd_parity(b)

    def test_empty_input(self):
        assert _adjust_parity(b"") == b""

    def test_returns_bytes(self):
        result = _adjust_parity(b"\x00\xFF")
        assert isinstance(result, bytes)


class TestDeriveSessionKey:
    def test_ac_key_length_16(self):
        sk = derive_session_key(MDK, ATC, "AC")
        assert len(sk) == 16

    def test_enc_key_length_16(self):
        sk = derive_session_key(MDK, ATC, "ENC")
        assert len(sk) == 16

    def test_mac_key_length_16(self):
        sk = derive_session_key(MDK, ATC, "MAC")
        assert len(sk) == 16

    def test_unknown_key_type_raises(self):
        with pytest.raises(CryptoError):
            derive_session_key(MDK, ATC, "UNKNOWN")

    def test_bad_key_size_raises(self):
        with pytest.raises(CryptoError):
            derive_session_key(b"\x00" * 8, ATC, "AC")

    def test_different_atc_different_key(self):
        sk1 = derive_session_key(MDK, 1, "AC")
        sk2 = derive_session_key(MDK, 2, "AC")
        assert sk1 != sk2

    def test_deterministic(self):
        sk1 = derive_session_key(MDK, ATC, "AC")
        sk2 = derive_session_key(MDK, ATC, "AC")
        assert sk1 == sk2

    def test_ac_and_mac_different(self):
        sk_ac  = derive_session_key(MDK, ATC, "AC")
        sk_mac = derive_session_key(MDK, ATC, "MAC")
        assert sk_ac != sk_mac

    def test_all_bytes_odd_parity(self):
        sk = derive_session_key(MDK, ATC, "AC")
        assert all(has_odd_parity(b) for b in sk)

    def test_24_byte_master_key(self):
        key24 = MDK + MDK[:8]
        sk = derive_session_key(key24, ATC, "AC")
        assert len(sk) == 16


class TestDeriveUDK:
    def test_returns_16_bytes(self):
        udk = derive_udk(MDK, PAN, PSN)
        assert len(udk) == 16

    def test_deterministic(self):
        udk1 = derive_udk(MDK, PAN, PSN)
        udk2 = derive_udk(MDK, PAN, PSN)
        assert udk1 == udk2

    def test_different_pans_different_udk(self):
        udk1 = derive_udk(MDK, PAN, PSN)
        udk2 = derive_udk(MDK, "5500000000000004", PSN)
        assert udk1 != udk2

    def test_different_psn_different_udk(self):
        udk1 = derive_udk(MDK, PAN, "00")
        udk2 = derive_udk(MDK, PAN, "01")
        assert udk1 != udk2

    def test_pan_with_spaces(self):
        udk1 = derive_udk(MDK, "4111 1111 1111 1111", PSN)
        udk2 = derive_udk(MDK, PAN, PSN)
        assert udk1 == udk2

    def test_all_bytes_odd_parity(self):
        udk = derive_udk(MDK, PAN, PSN)
        assert all(has_odd_parity(b) for b in udk)


class TestComputeARQC:
    def setup_method(self):
        self.udk = derive_udk(MDK, PAN, PSN)
        self.sk  = derive_session_key(self.udk, ATC, "AC")
        self.txn_data = bytes(28)

    def test_returns_8_bytes(self):
        arqc = compute_arqc(self.sk, self.txn_data)
        assert len(arqc) == 8

    def test_hex_string_input(self):
        arqc = compute_arqc(self.sk, "00" * 28)
        assert len(arqc) == 8

    def test_deterministic(self):
        arqc1 = compute_arqc(self.sk, self.txn_data)
        arqc2 = compute_arqc(self.sk, self.txn_data)
        assert arqc1 == arqc2

    def test_different_data_different_arqc(self):
        arqc1 = compute_arqc(self.sk, bytes(28))
        arqc2 = compute_arqc(self.sk, bytes(27) + b"\x01")
        assert arqc1 != arqc2

    def test_different_keys_different_arqc(self):
        sk2 = derive_session_key(MDK, ATC + 1, "AC")
        arqc1 = compute_arqc(self.sk, self.txn_data)
        arqc2 = compute_arqc(sk2, self.txn_data)
        assert arqc1 != arqc2

    def test_returns_bytes(self):
        arqc = compute_arqc(self.sk, self.txn_data)
        assert isinstance(arqc, bytes)


class TestVerifyARQC:
    def setup_method(self):
        self.txn_data = bytes(28)
        udk = derive_udk(MDK, PAN, PSN)
        sk  = derive_session_key(udk, ATC, "AC")
        self.arqc = compute_arqc(sk, self.txn_data)

    def test_valid_arqc_returns_true(self):
        assert verify_arqc(MDK, PAN, PSN, ATC, self.txn_data, self.arqc) is True

    def test_hex_string_arqc(self):
        arqc_hex = self.arqc.hex()
        assert verify_arqc(MDK, PAN, PSN, ATC, self.txn_data, arqc_hex) is True

    def test_wrong_arqc_returns_false(self):
        wrong = bytes([b ^ 0xFF for b in self.arqc])
        assert verify_arqc(MDK, PAN, PSN, ATC, self.txn_data, wrong) is False

    def test_wrong_atc_returns_false(self):
        assert verify_arqc(MDK, PAN, PSN, ATC + 1, self.txn_data, self.arqc) is False

    def test_wrong_pan_returns_false(self):
        assert verify_arqc(MDK, "5500000000000004", PSN, ATC, self.txn_data, self.arqc) is False


class TestGenerateARPC:
    def setup_method(self):
        udk = derive_udk(MDK, PAN, PSN)
        self.sk   = derive_session_key(udk, ATC, "AC")
        self.arqc = compute_arqc(self.sk, bytes(28))
        self.arc  = b"\x30\x30"

    def test_returns_8_bytes(self):
        arpc = generate_arpc(self.sk, self.arqc, self.arc)
        assert len(arpc) == 8

    def test_hex_string_inputs(self):
        arpc = generate_arpc(self.sk, self.arqc.hex(), self.arc.hex())
        assert len(arpc) == 8

    def test_deterministic(self):
        arpc1 = generate_arpc(self.sk, self.arqc, self.arc)
        arpc2 = generate_arpc(self.sk, self.arqc, self.arc)
        assert arpc1 == arpc2

    def test_different_arc_different_arpc(self):
        arpc1 = generate_arpc(self.sk, self.arqc, b"\x30\x30")
        arpc2 = generate_arpc(self.sk, self.arqc, b"\x30\x35")
        assert arpc1 != arpc2

    def test_different_arqc_different_arpc(self):
        arqc2 = bytes([b ^ 0x01 for b in self.arqc])
        arpc1 = generate_arpc(self.sk, self.arqc, self.arc)
        arpc2 = generate_arpc(self.sk, arqc2, self.arc)
        assert arpc1 != arpc2


class TestGenerateIssuerAuthData:
    def setup_method(self):
        udk = derive_udk(MDK, PAN, PSN)
        sk  = derive_session_key(udk, ATC, "AC")
        self.arqc = compute_arqc(sk, bytes(28))

    def test_returns_bytes(self):
        iad = generate_issuer_auth_data(MDK, PAN, PSN, ATC, self.arqc, "00")
        assert isinstance(iad, bytes)

    def test_length_arpc_plus_arc(self):
        iad = generate_issuer_auth_data(MDK, PAN, PSN, ATC, self.arqc, "00")
        assert len(iad) == 10

    def test_bytes_arqc_input(self):
        iad = generate_issuer_auth_data(MDK, PAN, PSN, ATC, self.arqc.hex(), "00")
        assert isinstance(iad, bytes)


class TestEncryptPINBlock:
    def test_returns_bytes(self):
        pin_block = bytes([0x04, 0x12, 0x34, 0xF0, 0x00, 0x00, 0x00, 0x00])
        result = encrypt_pin_block(pin_block, PAN, b"\x00" * 8)
        assert isinstance(result, bytes)

    def test_hex_string_input(self):
        pin_block_hex = "0412340000000000"
        result = encrypt_pin_block(pin_block_hex, PAN, b"\x00" * 8)
        assert isinstance(result, bytes)

    def test_length_8_bytes(self):
        pin_block = bytes(8)
        result = encrypt_pin_block(pin_block, PAN, b"\x00" * 8)
        assert len(result) == 8


class TestComputeMAC:
    def test_returns_8_bytes(self):
        mac = compute_mac(MDK, bytes(16))
        assert len(mac) == 8

    def test_hex_string_input(self):
        mac = compute_mac(MDK, "00" * 16)
        assert len(mac) == 8

    def test_deterministic(self):
        mac1 = compute_mac(MDK, bytes(16))
        mac2 = compute_mac(MDK, bytes(16))
        assert mac1 == mac2

    def test_different_data_different_mac(self):
        mac1 = compute_mac(MDK, bytes(16))
        mac2 = compute_mac(MDK, bytes(15) + b"\x01")
        assert mac1 != mac2

    def test_different_keys_different_mac(self):
        key2 = bytes.fromhex("FEDCBA98765432100123456789ABCDEF")
        mac1 = compute_mac(MDK, bytes(16))
        mac2 = compute_mac(key2, bytes(16))
        assert mac1 != mac2

    def test_8_byte_key(self):
        mac = compute_mac(MDK[:8], bytes(16))
        assert len(mac) == 8
