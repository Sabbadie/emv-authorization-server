"""
Tests S5 — HSM simulé : chiffrement des données sensibles en RAM.
Couvre : HsmKeyStore, SimulatedHSM, rotation KEK, révocation, journal d'accès.
"""

import pytest
import time
from emv.hsm import (
    HsmKeyStore, SimulatedHSM, KeyMetadata, get_hsm,
)


@pytest.fixture(autouse=True)
def reset_hsm():
    SimulatedHSM.reset_instance()
    yield
    SimulatedHSM.reset_instance()


# ── HsmKeyStore ───────────────────────────────────────────────────────────────

class TestHsmKeyStore:
    def test_init_creates_kek(self):
        ks = HsmKeyStore()
        assert ks._kek is not None
        assert len(ks._kek) > 0

    def test_load_and_get_key(self):
        ks = HsmKeyStore()
        raw = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")
        ks.load_key("MDK_AC", raw, "MDK_AC")
        result = ks.get_key("MDK_AC")
        assert result == raw

    def test_key_stored_encrypted(self):
        ks = HsmKeyStore()
        raw = b"\xde\xad\xbe\xef" * 4
        ks.load_key("TEST", raw, "CUSTOM")
        wrapped = ks._wrapped_keys["TEST"]
        assert wrapped != raw
        assert raw not in wrapped

    def test_get_nonexistent_key_raises(self):
        ks = HsmKeyStore()
        with pytest.raises(KeyError):
            ks.get_key("NONEXISTENT")

    def test_has_key_true(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x00" * 16, "CUSTOM")
        assert ks.has_key("K1") is True

    def test_has_key_false(self):
        ks = HsmKeyStore()
        assert ks.has_key("MISSING") is False

    def test_revoke_key_disables(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x01" * 16, "CUSTOM")
        ks.revoke_key("K1")
        with pytest.raises(PermissionError):
            ks.get_key("K1")

    def test_revoke_nonexistent_returns_false(self):
        ks = HsmKeyStore()
        assert ks.revoke_key("NONE") is False

    def test_delete_key(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x02" * 16, "CUSTOM")
        result = ks.delete_key("K1")
        assert result is True
        assert not ks.has_key("K1")

    def test_delete_nonexistent_returns_false(self):
        ks = HsmKeyStore()
        assert ks.delete_key("NONE") is False

    def test_use_count_increments(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x03" * 16, "CUSTOM")
        ks.get_key("K1")
        ks.get_key("K1")
        meta = ks._metadata["K1"]
        assert meta.use_count == 2

    def test_list_keys(self):
        ks = HsmKeyStore()
        ks.load_key("MDK_AC", b"\x04" * 16, "MDK_AC")
        ks.load_key("CVK1", b"\x05" * 8, "CVK1")
        keys = ks.list_keys()
        assert len(keys) == 2
        ids = [k["key_id"] for k in keys]
        assert "MDK_AC" in ids

    def test_list_keys_no_values(self):
        ks = HsmKeyStore()
        raw = bytes.fromhex("AABBCCDDEEFF00112233445566778899")
        ks.load_key("SECRET", raw, "CUSTOM")
        keys = ks.list_keys()
        for k in keys:
            assert raw.hex() not in str(k)

    def test_get_status(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x06" * 16, "MDK_AC")
        status = ks.get_status()
        assert status["keys_loaded"] == 1
        assert status["kek_ephemeral"] is True
        assert status["kek_persisted"] is False

    def test_access_log_records_operations(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x07" * 16, "CUSTOM")
        ks.get_key("K1")
        log = ks.get_access_log()
        ops = [e["operation"] for e in log]
        assert "LOAD" in ops
        assert "USE" in ops

    def test_rotate_kek_keeps_keys_accessible(self):
        ks = HsmKeyStore()
        raw = b"\x08" * 16
        ks.load_key("K1", raw, "CUSTOM")
        old_kek = ks._kek
        ks.rotate_kek()
        assert ks._kek != old_kek
        result = ks.get_key("K1")
        assert result == raw

    def test_rotate_kek_logs_event(self):
        ks = HsmKeyStore()
        ks.load_key("K1", b"\x09" * 16, "CUSTOM")
        ks.rotate_kek()
        log = ks.get_access_log()
        ops = [e["operation"] for e in log]
        assert "KEK_ROTATE" in ops

    def test_load_empty_bytes_raises(self):
        ks = HsmKeyStore()
        with pytest.raises(ValueError):
            ks.load_key("K1", b"", "CUSTOM")

    def test_multiple_keys_independent(self):
        ks = HsmKeyStore()
        raw1 = b"\xAA" * 16
        raw2 = b"\xBB" * 16
        ks.load_key("K1", raw1, "CUSTOM")
        ks.load_key("K2", raw2, "CUSTOM")
        assert ks.get_key("K1") == raw1
        assert ks.get_key("K2") == raw2


# ── SimulatedHSM ──────────────────────────────────────────────────────────────

class FakeConfig:
    MDK_AC  = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")
    MDK_ENC = bytes.fromhex("FEDCBA98765432100123456789ABCDEF")
    MDK_MAC = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")
    CVK1    = bytes.fromhex("0123456789ABCDEF")
    CVK2    = bytes.fromhex("FEDCBA9876543210")
    SECRET_KEY = "test-secret-key"


class TestSimulatedHSM:
    def test_singleton(self):
        h1 = SimulatedHSM.get_instance()
        h2 = SimulatedHSM.get_instance()
        assert h1 is h2

    def test_not_initialized_by_default(self):
        hsm = SimulatedHSM.get_instance()
        assert hsm.is_initialized() is False

    def test_initialize_from_config(self):
        hsm = SimulatedHSM.get_instance()
        count = hsm.initialize_from_config(FakeConfig())
        assert count == 6
        assert hsm.is_initialized() is True

    def test_get_mdk_ac(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        result = hsm.get_mdk_ac()
        assert result == FakeConfig.MDK_AC

    def test_get_mdk_enc(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        assert hsm.get_mdk_enc() == FakeConfig.MDK_ENC

    def test_get_mdk_mac(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        assert hsm.get_mdk_mac() == FakeConfig.MDK_MAC

    def test_get_cvk1(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        assert hsm.get_cvk1() == FakeConfig.CVK1

    def test_get_cvk2(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        assert hsm.get_cvk2() == FakeConfig.CVK2

    def test_get_secret_key(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        assert hsm.get_secret_key() == "test-secret-key"

    def test_get_status_initialized(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        status = hsm.get_status()
        assert status["initialized"] is True
        assert status["keys_loaded"] == 6
        assert status["kek_persisted"] is False

    def test_get_key_inventory(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        inv = hsm.get_key_inventory()
        ids = [k["key_id"] for k in inv]
        assert "MDK_AC" in ids
        assert "CVK1" in ids

    def test_load_custom_key(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        custom = b"\xCA\xFE\xBA\xBE" * 4
        hsm.load_key("CUSTOM_KEY", custom, description="Test key")
        assert hsm.get_key("CUSTOM_KEY") == custom

    def test_rotate_kek(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        mdk_before = hsm.get_mdk_ac()
        hsm.rotate_kek()
        mdk_after = hsm.get_mdk_ac()
        assert mdk_before == mdk_after

    def test_revoke_key(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        hsm.load_key("TEMP", b"\xFF" * 16)
        result = hsm.revoke_key("TEMP")
        assert result is True

    def test_get_access_log(self):
        hsm = SimulatedHSM.get_instance()
        hsm.initialize_from_config(FakeConfig())
        hsm.get_mdk_ac()
        log = hsm.get_access_log()
        assert len(log) > 0

    def test_get_hsm_shortcut(self):
        h = get_hsm()
        assert isinstance(h, SimulatedHSM)
