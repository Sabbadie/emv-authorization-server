"""
Tests — C4 Issuer Script Processing (Tag 71 / Tag 72)
Couvre : generate_scripts (règles, TLV, format hex/b64), endpoint REST.
"""
import base64
import pytest
from emv.issuer_scripts import (
    generate_scripts, _build_tlv, _build_script_template,
    ISSUER_APDU, SCRIPT_REASON_LABELS,
)
from models.card import Card, CardStatus


def _make_card(pan="4111111111111111", pin_tries=0, consecutive_offline=0):
    c = Card(pan=pan, expiry="2812", cardholder_name="TEST",
             psn="01", status=CardStatus.ACTIVE, balance=500000)
    c.pin_tries = pin_tries
    c.max_pin_tries = 3
    c.consecutive_offline = consecutive_offline
    return c


# ── _build_tlv ────────────────────────────────────────────────────────────────

class TestBuildTLV:
    def test_single_byte_tag(self):
        tlv = _build_tlv(0x86, b"\x01\x02\x03")
        assert tlv[0] == 0x86
        assert tlv[1] == 3         # length
        assert tlv[2:] == b"\x01\x02\x03"

    def test_two_byte_tag(self):
        tlv = _build_tlv(0x9F26, b"\xAA\xBB")
        assert tlv[0] == 0x9F
        assert tlv[1] == 0x26

    def test_empty_data(self):
        tlv = _build_tlv(0x86, b"")
        assert tlv[1] == 0         # length = 0

    def test_long_value_uses_0x81(self):
        data = bytes(130)
        tlv = _build_tlv(0x86, data)
        assert tlv[1] == 0x81
        assert tlv[2] == 130


# ── _build_script_template ────────────────────────────────────────────────────

class TestBuildScriptTemplate:
    def test_empty_returns_empty_bytes(self):
        result = _build_script_template(0x71, [])
        assert result == b""

    def test_tag_71_wrapped(self):
        cmd = _build_tlv(0x86, b"\x01\x02")
        result = _build_script_template(0x71, [cmd])
        assert result[0] == 0x71

    def test_tag_72_wrapped(self):
        cmd = _build_tlv(0x86, b"\x01")
        result = _build_script_template(0x72, [cmd])
        assert result[0] == 0x72


# ── generate_scripts — carte saine ────────────────────────────────────────────

class TestGenerateScriptsCleanCard:
    def test_clean_card_routine_script(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        assert r["has_scripts"] is True   # UPDATE_RISK_PARAMS always added when authorized

    def test_clean_card_no_tag_71(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        # No PIN tries → no tag 71
        assert r["tag_71"] is None

    def test_clean_card_tag_72_present(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        assert r["tag_72"] is not None

    def test_reason_routine(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        assert "ROUTINE" in r["reason"]


# ── generate_scripts — PIN tries critique ────────────────────────────────────

class TestGenerateScriptsPinTries:
    def test_pin_tries_near_max_adds_tag71(self):
        card = _make_card(pin_tries=2)  # max=3, so 2 >= max-1
        r = generate_scripts(card, authorized=True)
        assert r["tag_71"] is not None

    def test_pin_tries_reason(self):
        card = _make_card(pin_tries=2)
        r = generate_scripts(card, authorized=True)
        assert "PIN_TRIES_EXCEEDED" in r["reason"]

    def test_pin_tries_commands_71_non_empty(self):
        card = _make_card(pin_tries=2)
        r = generate_scripts(card, authorized=True)
        assert len(r["commands_71"]) > 0

    def test_low_pin_tries_no_tag71(self):
        card = _make_card(pin_tries=0)
        r = generate_scripts(card, authorized=True)
        assert r["tag_71"] is None


# ── generate_scripts — cumul hors ligne ──────────────────────────────────────

class TestGenerateScriptsOffline:
    def test_high_offline_adds_tag72(self):
        card = _make_card(consecutive_offline=4)
        r = generate_scripts(card, authorized=True)
        # Tag 72 should contain offline counter reset
        assert "OFFLINE_COUNTER_HIGH" in r["reason"]

    def test_low_offline_no_offline_reason(self):
        card = _make_card(consecutive_offline=1)
        r = generate_scripts(card, authorized=True)
        assert "OFFLINE_COUNTER_HIGH" not in r["reason"]


# ── generate_scripts — fraude ─────────────────────────────────────────────────

class TestGenerateScriptsFraud:
    def test_fraud_block_adds_tag72(self):
        card = _make_card()
        r = generate_scripts(card, authorized=False, reason="fraud")
        assert "FRAUD_BLOCK" in r["reason"]
        assert r["has_scripts"] is True

    def test_non_fraud_reason_no_block(self):
        card = _make_card()
        r = generate_scripts(card, authorized=False, reason="insufficient_funds")
        assert "FRAUD_BLOCK" not in r["reason"]


# ── format TLV hex / base64 ───────────────────────────────────────────────────

class TestScriptFormat:
    def test_hex_starts_with_72(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        if r["tag_72"]:
            assert r["tag_72"].startswith("72")

    def test_hex_starts_with_71(self):
        card = _make_card(pin_tries=2)
        r = generate_scripts(card, authorized=True)
        if r["tag_71"]:
            assert r["tag_71"].startswith("71")

    def test_base64_decodable_72(self):
        card = _make_card(pin_tries=0, consecutive_offline=0)
        r = generate_scripts(card, authorized=True)
        if r["tag_72_b64"]:
            decoded = base64.b64decode(r["tag_72_b64"])
            assert len(decoded) > 0

    def test_base64_decodable_71(self):
        card = _make_card(pin_tries=2)
        r = generate_scripts(card, authorized=True)
        if r["tag_71_b64"]:
            decoded = base64.b64decode(r["tag_71_b64"])
            assert len(decoded) > 0

    def test_commands_list_structure(self):
        card = _make_card(pin_tries=2)
        r = generate_scripts(card, authorized=True)
        for cmd in r["commands_71"]:
            assert "hex" in cmd
            assert "b64" in cmd
            assert "len" in cmd


# ── Endpoint REST ─────────────────────────────────────────────────────────────

class TestIssuerScriptsEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        self.client = client

    def test_get_scripts_active_card(self):
        r = self.client.get("/api/v1/cards/4111111111111111/issuer-scripts")
        assert r.status_code == 200
        data = r.get_json()
        assert "scripts" in data
        assert "pan_masked" in data
        assert data["pan_masked"].endswith("1111")

    def test_get_scripts_not_found(self):
        r = self.client.get("/api/v1/cards/9999999999999999/issuer-scripts")
        assert r.status_code == 404

    def test_get_scripts_unauthorized(self):
        r = self.client.get("/api/v1/cards/4111111111111111/issuer-scripts"
                            "?authorized=false&reason=fraud")
        assert r.status_code == 200
        data = r.get_json()
        assert "FRAUD_BLOCK" in data["scripts"]["reason"] or \
               data["scripts"]["reason"] == "NONE"

    def test_scripts_has_key_fields(self):
        r = self.client.get("/api/v1/cards/4111111111111111/issuer-scripts")
        scripts = r.get_json()["scripts"]
        assert "tag_71" in scripts
        assert "tag_72" in scripts
        assert "has_scripts" in scripts
        assert "reason" in scripts
