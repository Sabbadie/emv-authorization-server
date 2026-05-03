"""
Tests unitaires — Sécurité S4 : Pydantic schemas (T008).
Couvre AuthorizeRequest, PreAuthRequest, ChargebackCreateRequest,
et la fonction pydantic_error_response.
"""
import pytest
from pydantic import ValidationError
from schemas import (
    AuthorizeRequest,
    PreauthRequest,
    ChargebackRequest,
    pydantic_error_response,
)


# ═══════════════════════════════════════════════════════════════════════════════
# AuthorizeRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthorizeRequest:

    def test_minimal_valid(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 1000,
        })
        assert req.pan == "4970101122334455"
        assert req.amount == 1000
        assert req.currency == "978"
        assert req.transaction_type == "00"

    def test_pan_stripped_of_spaces(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970 1011 2233 4455",
            "amount": 500,
        })
        assert req.pan == "4970101122334455"

    def test_pan_too_short_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            AuthorizeRequest.model_validate({"pan": "12345", "amount": 100})
        assert "PAN" in str(exc_info.value) or "pan" in str(exc_info.value).lower()

    def test_pan_non_numeric_raises(self):
        with pytest.raises(ValidationError):
            AuthorizeRequest.model_validate({"pan": "ABCD1234567890", "amount": 100})

    def test_missing_pan_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            AuthorizeRequest.model_validate({"amount": 500})
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("pan",) for e in errors)

    def test_zero_amount_allowed(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 0,
        })
        assert req.amount == 0

    def test_negative_amount_raises(self):
        with pytest.raises(ValidationError):
            AuthorizeRequest.model_validate({
                "pan": "4970101122334455",
                "amount": -1,
            })

    def test_currency_default_978(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 500,
        })
        assert req.currency == "978"

    def test_currency_zero_padded(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 500,
            "currency": "036",
        })
        assert req.currency == "036"

    def test_invalid_mcc_raises(self):
        with pytest.raises(ValidationError):
            AuthorizeRequest.model_validate({
                "pan": "4970101122334455",
                "amount": 500,
                "mcc": "ABCD",
            })

    def test_valid_mcc(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 500,
            "mcc": "5411",
        })
        assert req.mcc == "5411"

    def test_cvv2_valid(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 500,
            "cvv2": "123",
            "expiry_yymm": "2812",
        })
        assert req.cvv2 == "123"
        assert req.expiry_yymm == "2812"

    def test_cvv2_too_short_raises(self):
        with pytest.raises(ValidationError):
            AuthorizeRequest.model_validate({
                "pan": "4970101122334455",
                "amount": 500,
                "cvv2": "12",
            })

    def test_pos_entry_mode_wrong_length_raises(self):
        with pytest.raises(ValidationError):
            AuthorizeRequest.model_validate({
                "pan": "4970101122334455",
                "amount": 500,
                "pos_entry_mode": "05",  # doit être 3 chars
            })

    def test_is_contactless_default_false(self):
        req = AuthorizeRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 500,
        })
        assert req.is_contactless is False


# ═══════════════════════════════════════════════════════════════════════════════
# PreauthRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestPreauthRequest:

    def test_minimal_valid(self):
        req = PreauthRequest.model_validate({
            "pan": "4970101122334455",
            "amount": 5000,
        })
        assert req.pan == "4970101122334455"
        assert req.amount == 5000

    def test_missing_pan_raises(self):
        with pytest.raises(ValidationError):
            PreauthRequest.model_validate({"amount": 5000})

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError):
            PreauthRequest.model_validate({"pan": "4970101122334455"})

    def test_pan_with_dashes(self):
        req = PreauthRequest.model_validate({
            "pan": "4970-1011-2233-4455",
            "amount": 5000,
        })
        assert req.pan == "4970101122334455"


# ═══════════════════════════════════════════════════════════════════════════════
# ChargebackRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestChargebackRequest:

    def test_minimal_valid(self):
        req = ChargebackRequest.model_validate({
            "reason_code": "CB01",
        })
        assert req.reason_code == "CB01"
        assert req.initiated_by == "PORTEUR"

    def test_missing_reason_code_raises(self):
        with pytest.raises(ValidationError):
            ChargebackRequest.model_validate({})

    def test_invalid_reason_code_pattern_raises(self):
        with pytest.raises(ValidationError):
            ChargebackRequest.model_validate({"reason_code": "INVALID"})

    def test_optional_notes(self):
        req = ChargebackRequest.model_validate({
            "reason_code": "CB02",
            "notes": "Montant incorrect",
        })
        assert req.notes == "Montant incorrect"


# ═══════════════════════════════════════════════════════════════════════════════
# pydantic_error_response
# ═══════════════════════════════════════════════════════════════════════════════

class TestPydanticErrorResponse:

    def _trigger(self, data):
        try:
            AuthorizeRequest.model_validate(data)
        except ValidationError as exc:
            return pydantic_error_response(exc)
        return None

    def test_returns_error_key(self):
        resp = self._trigger({"amount": 100})
        assert "error" in resp
        assert resp["error"] == "Validation échouée"

    def test_returns_details_list(self):
        resp = self._trigger({"amount": 100})
        assert isinstance(resp["details"], list)
        assert len(resp["details"]) >= 1

    def test_detail_has_field_and_message(self):
        resp = self._trigger({"amount": 100})
        detail = resp["details"][0]
        assert "field" in detail
        assert "message" in detail

    def test_pan_error_in_details(self):
        resp = self._trigger({"amount": 100})
        fields = [d["field"] for d in resp["details"]]
        assert "pan" in fields
