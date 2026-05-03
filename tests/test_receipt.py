"""
Tests v1.11.0 — Export TXT/JSON enrichi (emv/receipt.py).
Couvre : format_receipt TXT + JSON, helpers, bulk export, cas limites.
"""
import json
import pytest
from unittest.mock import MagicMock


# ── Fixture transaction ────────────────────────────────────────────────────────

def make_txn(**kwargs):
    t = MagicMock()
    t.id                   = kwargs.get("id", "TXN-TEST-001")
    t.rrn                  = kwargs.get("rrn", "260503001")
    t.pan                  = kwargs.get("pan", "4111111111111111")
    t.amount               = kwargs.get("amount", 5000)
    t.currency             = kwargs.get("currency", "978")
    t.transaction_type     = kwargs.get("transaction_type", "00")
    t.terminal_id          = kwargs.get("terminal_id", "TERM0001")
    t.merchant_id          = kwargs.get("merchant_id", "MERCH001")
    t.merchant_name        = kwargs.get("merchant_name", "SUPERMARCHE TEST")
    t.atc                  = kwargs.get("atc", 5)
    t.arqc                 = kwargs.get("arqc", "AABBCCDD11223344")
    t.arpc                 = kwargs.get("arpc", "55667788AABBCCDD")
    t.issuer_auth_data     = kwargs.get("issuer_auth_data", "9F26")
    t.auth_code            = kwargs.get("auth_code", "A00001")
    t.status               = kwargs.get("status", "APPROVED")
    t.response_code        = kwargs.get("response_code", "00")
    t.decline_reason       = kwargs.get("decline_reason", None)
    t.pos_entry_mode       = kwargs.get("pos_entry_mode", "051")
    t.amount_tier          = kwargs.get("amount_tier", "SMALL")
    t.risk_level           = kwargs.get("risk_level", "LOW")
    t.auth_path            = kwargs.get("auth_path", "ONLINE")
    t.cb_scheme            = kwargs.get("cb_scheme", "VISA")
    t.cb_brand             = kwargs.get("cb_brand", "VISA")
    t.cb_service_indicator = kwargs.get("cb_service_indicator", "01")
    t.cb_sca_exemption     = kwargs.get("cb_sca_exemption", None)
    t.cb_floor_limit       = kwargs.get("cb_floor_limit", 0)
    t.cb_is_contactless    = kwargs.get("cb_is_contactless", False)
    t.cb_response_code     = kwargs.get("cb_response_code", None)
    t.cb_decline_reason    = kwargs.get("cb_decline_reason", None)
    t.created_at           = kwargs.get("created_at", "2026-05-03T10:00:00Z")
    t.processed_at         = kwargs.get("processed_at", "2026-05-03T10:00:01Z")
    t.reversed_at          = kwargs.get("reversed_at", None)
    t.reversal_amount      = kwargs.get("reversal_amount", None)
    t.is_partial_reversal  = kwargs.get("is_partial_reversal", False)
    return t


# ── Tests helpers ─────────────────────────────────────────────────────────────

class TestHelpers:
    def test_pan_mask_16_digits(self):
        from emv.receipt import _pan_mask
        assert _pan_mask("4111111111111111") == "XXXXXXXXXXXX1111"

    def test_pan_mask_preserves_last4(self):
        from emv.receipt import _pan_mask
        assert _pan_mask("5500000000000004")[-4:] == "0004"

    def test_pan_mask_short(self):
        from emv.receipt import _pan_mask
        assert _pan_mask("1234") == "1234"

    def test_pan_mask_empty(self):
        from emv.receipt import _pan_mask
        assert _pan_mask("") == ""

    def test_amount_str_eur(self):
        from emv.receipt import _amount_str
        assert _amount_str(5000, "978") == "50.00 EUR"

    def test_amount_str_usd(self):
        from emv.receipt import _amount_str
        assert _amount_str(10000, "840") == "100.00 USD"

    def test_amount_str_zero(self):
        from emv.receipt import _amount_str
        assert _amount_str(0, "978") == "0.00 EUR"

    def test_center_pads(self):
        from emv.receipt import _center, RECEIPT_WIDTH
        result = _center("TEST")
        assert len(result) == RECEIPT_WIDTH
        assert "TEST" in result

    def test_line_label_value(self):
        from emv.receipt import _line, RECEIPT_WIDTH
        result = _line("CODE AUTH", "A00001")
        assert len(result) == RECEIPT_WIDTH
        assert "CODE AUTH" in result
        assert "A00001" in result

    def test_format_dt_valid(self):
        from emv.receipt import _format_dt
        result = _format_dt("2026-05-03T10:00:00Z")
        assert "03/05/2026" in result
        assert "10:00:00" in result

    def test_format_dt_none(self):
        from emv.receipt import _format_dt
        assert _format_dt(None) == "—"

    def test_wrap_short_text(self):
        from emv.receipt import _wrap
        result = _wrap("Hello world", width=40)
        assert result == ["Hello world"]

    def test_wrap_long_text(self):
        from emv.receipt import _wrap
        text = "A " * 25  # 50 chars
        lines = _wrap(text, width=40)
        assert all(len(line) <= 40 for line in lines)


# ── Tests format_receipt TXT ──────────────────────────────────────────────────

class TestReceiptTxt:
    def test_returns_string(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="txt")
        assert isinstance(result, str)

    def test_contains_header(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="txt")
        assert "SERVEUR D'AUTORISATION EMV" in result

    def test_contains_amount(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(amount=5000, currency="978"), fmt="txt")
        assert "50.00 EUR" in result

    def test_contains_pan_masked(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(pan="4111111111111111"), fmt="txt")
        assert "1111" in result
        assert "4111111111" not in result

    def test_approved_label(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(status="APPROVED"), fmt="txt")
        assert "APPROUVÉ" in result

    def test_declined_label(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(status="DECLINED"), fmt="txt")
        assert "REFUSÉ" in result

    def test_contains_auth_code(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(auth_code="Z99999"), fmt="txt")
        assert "Z99999" in result

    def test_contains_rrn(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(rrn="RRN260503"), fmt="txt")
        assert "RRN260503" in result

    def test_contains_terminal(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(terminal_id="TERMXYZ"), fmt="txt")
        assert "TERMXYZ" in result

    def test_contactless_shown(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(cb_is_contactless=True), fmt="txt")
        assert "SANS CONTACT" in result
        assert "OUI" in result

    def test_lines_width(self):
        from emv.receipt import format_receipt, RECEIPT_WIDTH
        result = format_receipt(make_txn(), fmt="txt")
        for line in result.split("\n"):
            assert len(line) <= RECEIPT_WIDTH, "Ligne trop longue : {!r}".format(line)

    def test_decline_reason_shown(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(
            status="DECLINED", response_code="51",
            decline_reason="Provision insuffisante"), fmt="txt")
        assert "51" in result

    def test_arqc_shown(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(arqc="AABBCCDD11223344"), fmt="txt")
        assert "ARQC" in result

    def test_puc_entry_label(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(pos_entry_mode="071"), fmt="txt")
        assert "SANS CONTACT NFC" in result

    def test_sca_exemption_shown(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(cb_sca_exemption="LVP"), fmt="txt")
        assert "LVP" in result

    def test_default_fmt_is_json(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn())
        assert isinstance(result, dict)


# ── Tests format_receipt JSON ─────────────────────────────────────────────────

class TestReceiptJson:
    def test_returns_dict(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="json")
        assert isinstance(result, dict)

    def test_has_required_sections(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="json")
        for section in ["transaction", "card", "amount", "emv", "cb_rules", "risk", "terminal", "timestamps"]:
            assert section in result, "Section manquante : {}".format(section)

    def test_amount_formatted(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(amount=15050, currency="978"), fmt="json")
        assert result["amount"]["formatted"] == "150.50 EUR"

    def test_pan_masked_in_json(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(pan="4111111111111111"), fmt="json")
        assert result["card"]["pan_masked"] == "XXXXXXXXXXXX1111"

    def test_response_label(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(response_code="00"), fmt="json")
        assert result["transaction"]["response_label"] == "APPROUVÉ"

    def test_response_label_51(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(response_code="51"), fmt="json")
        assert "insuffisante" in result["transaction"]["response_label"].lower()

    def test_transaction_type_label(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(transaction_type="20"), fmt="json")
        assert result["emv"]["transaction_type_label"] == "REMBOURSEMENT"

    def test_receipt_version(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="json")
        assert result["receipt_version"] == "1.11.0"

    def test_generated_at_present(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="json")
        assert "generated_at" in result
        assert result["generated_at"].endswith("Z")

    def test_serializable(self):
        from emv.receipt import format_receipt
        result = format_receipt(make_txn(), fmt="json")
        # doit être sérialisable sans erreur
        dumped = json.dumps(result, default=str)
        assert len(dumped) > 100


# ── Tests bulk export TXT ─────────────────────────────────────────────────────

class TestBulkReceiptTxt:
    def test_empty_list(self):
        from emv.receipt import format_bulk_receipt_txt
        result = format_bulk_receipt_txt([])
        assert "0 transaction(s)" in result

    def test_single_transaction(self):
        from emv.receipt import format_bulk_receipt_txt
        result = format_bulk_receipt_txt([make_txn()])
        assert "[1/1]" in result

    def test_multiple_transactions(self):
        from emv.receipt import format_bulk_receipt_txt
        txns = [make_txn(id="TXN-{}".format(i), rrn="RRN{}".format(i)) for i in range(3)]
        result = format_bulk_receipt_txt(txns)
        assert "[1/3]" in result
        assert "[2/3]" in result
        assert "[3/3]" in result

    def test_custom_title(self):
        from emv.receipt import format_bulk_receipt_txt
        result = format_bulk_receipt_txt([make_txn()], title="MON EXPORT")
        assert "MON EXPORT" in result

    def test_fin_export(self):
        from emv.receipt import format_bulk_receipt_txt
        result = format_bulk_receipt_txt([make_txn()])
        assert "FIN D'EXPORT" in result
