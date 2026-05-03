"""
Schémas Pydantic v2 — Validation stricte des entrées API (S4).

Usage dans server.py :
    from schemas import AuthorizeRequest
    try:
        req = AuthorizeRequest.model_validate(request.get_json() or {})
    except ValidationError as e:
        return jsonify({"error": "Validation échouée", "details": e.errors()}), 422
"""
import re
from typing import Optional, Literal, Any
from pydantic import BaseModel, field_validator, model_validator, Field


# ── Utilitaires ───────────────────────────────────────────────────────────────

_PAN_RE   = re.compile(r"^\d{12,19}$")
_HEX_RE   = re.compile(r"^[0-9A-Fa-f]+$")
_ATC_RE   = re.compile(r"^[0-9A-Fa-f]{4}$")


def _clean_pan(v: str) -> str:
    return v.replace(" ", "").replace("-", "")


# ═══════════════════════════════════════════════════════════════════════════════
# Autorisation
# ═══════════════════════════════════════════════════════════════════════════════

class AuthorizeRequest(BaseModel):
    pan:              str
    amount:           int   = Field(ge=0, description="Montant en centimes")
    currency:         str   = Field(default="978", min_length=3, max_length=3)
    transaction_type: str   = Field(default="00",  min_length=2, max_length=2,
                                    pattern=r"^\d{2}$")
    field_55:         Optional[str] = Field(default=None)
    terminal_id:      Optional[str] = Field(default=None, max_length=16)
    merchant_id:      Optional[str] = Field(default=None, max_length=15)
    merchant_name:    Optional[str] = Field(default=None, max_length=40)
    pos_entry_mode:   Optional[str] = Field(default=None, min_length=3, max_length=3)
    is_contactless:   bool          = False
    mcc:              Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    cvv2:             Optional[str] = Field(default=None, min_length=3, max_length=4,
                                            pattern=r"^\d{3,4}$")
    expiry_yymm:      Optional[str] = Field(default=None, min_length=4, max_length=4,
                                            pattern=r"^\d{4}$")
    atc:              Optional[str] = Field(default=None)
    rrn:              Optional[str] = Field(default=None, max_length=20)

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide (12–19 chiffres requis)")
        return cleaned

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v):
        return str(v).zfill(3)

    @field_validator("field_55", mode="before")
    @classmethod
    def validate_field55(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        if s and not _HEX_RE.match(s):
            raise ValueError("field_55 doit être une chaîne hexadécimale")
        return s or None

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError("Montant invalide (entier en centimes requis)")
        if n < 0:
            raise ValueError("Le montant ne peut pas être négatif")
        return n


class ReverseRequest(BaseModel):
    pan:             str
    transaction_id:  Optional[str] = None
    rrn:             Optional[str] = None
    amount:          Optional[int] = Field(default=None, gt=0)
    terminal_id:     Optional[str] = Field(default=None, max_length=16)

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned

    @model_validator(mode="after")
    def require_id_or_rrn(self):
        if not self.transaction_id and not self.rrn:
            raise ValueError("transaction_id ou rrn requis")
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# Préautorisation
# ═══════════════════════════════════════════════════════════════════════════════

class PreauthRequest(BaseModel):
    pan:           str
    amount:        int   = Field(gt=0)
    currency:      str   = Field(default="978", min_length=3, max_length=3)
    terminal_id:   Optional[str] = Field(default=None, max_length=16)
    merchant_id:   Optional[str] = Field(default=None, max_length=15)
    merchant_name: Optional[str] = Field(default=None, max_length=40)
    expiry_hours:  int            = Field(default=24, ge=1, le=720)
    notes:         Optional[str] = Field(default=None, max_length=200)

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v):
        return str(v).zfill(3)

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError("Montant invalide")


class CaptureRequest(BaseModel):
    capture_amount: Optional[int] = Field(default=None, gt=0)

    @field_validator("capture_amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError("capture_amount invalide")


# ═══════════════════════════════════════════════════════════════════════════════
# Chargebacks
# ═══════════════════════════════════════════════════════════════════════════════

class ChargebackRequest(BaseModel):
    reason_code:  str   = Field(min_length=2, max_length=6, pattern=r"^CB\d{2}$")
    amount:       Optional[int] = Field(default=None, gt=0)
    initiated_by: Optional[Literal["PORTEUR", "BANQUE", "COMMERÇANT", "RESEAU"]] = "PORTEUR"
    notes:        Optional[str] = Field(default=None, max_length=500)

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError("Montant invalide")


class ChargebackResolveRequest(BaseModel):
    resolution: Literal["ACCEPTED", "REJECTED", "ARBITRATION"]
    notes:      Optional[str] = Field(default=None, max_length=500)


# ═══════════════════════════════════════════════════════════════════════════════
# BIN Blacklist
# ═══════════════════════════════════════════════════════════════════════════════

class BINBlacklistBinRequest(BaseModel):
    prefix:   str   = Field(alias="prefix", min_length=4, max_length=10)
    reason:   Optional[str] = Field(default=None, max_length=200)
    added_by: str            = Field(default="API", max_length=50)

    model_config = {"populate_by_name": True}

    @field_validator("prefix", mode="before")
    @classmethod
    def coerce_prefix(cls, v):
        s = str(v).strip()
        if not s.isdigit():
            raise ValueError("Préfixe BIN invalide (chiffres uniquement)")
        return s


class BINBlacklistPanRequest(BaseModel):
    pan:      str   = Field(min_length=12, max_length=19)
    reason:   Optional[str] = Field(default=None, max_length=200)
    added_by: str            = Field(default="API", max_length=50)

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned


class BINCheckRequest(BaseModel):
    pan: str

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# Devises
# ═══════════════════════════════════════════════════════════════════════════════

class CurrencyConvertRequest(BaseModel):
    amount:        int   = Field(gt=0)
    from_currency: str   = Field(min_length=3, max_length=3)
    to_currency:   str   = Field(min_length=3, max_length=3)

    @field_validator("from_currency", "to_currency", mode="before")
    @classmethod
    def pad_currency(cls, v):
        return str(v).zfill(3)

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ValueError("Montant invalide")
        if n <= 0:
            raise ValueError("Montant doit être positif")
        return n


# ═══════════════════════════════════════════════════════════════════════════════
# Cartes
# ═══════════════════════════════════════════════════════════════════════════════

class CardCreateRequest(BaseModel):
    pan:            str
    expiry:         str   = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    cardholder_name: str  = Field(min_length=2, max_length=100)
    psn:            str   = Field(default="01", min_length=2, max_length=2)
    balance:        int   = Field(default=100000, ge=0)
    daily_limit:    int   = Field(default=200000, ge=0)
    cb_scheme:      str   = Field(default="VISA", max_length=10)
    cb_brand:       str   = Field(default="VISA CB", max_length=30)
    status:         str   = Field(default="ACTIVE")

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned


class CardUpdateRequest(BaseModel):
    balance:         Optional[int] = Field(default=None, ge=0)
    daily_limit:     Optional[int] = Field(default=None, ge=0)
    cardholder_name: Optional[str] = Field(default=None, max_length=100)
    pin_tries:       Optional[int] = Field(default=None, ge=0, le=10)


# ═══════════════════════════════════════════════════════════════════════════════
# Webhooks
# ═══════════════════════════════════════════════════════════════════════════════

class WebhookTestRequest(BaseModel):
    event:       str           = Field(default="authorization.approved", max_length=60)
    payload:     Optional[Any] = None
    webhook_url: Optional[str] = Field(default=None, max_length=500)


# ═══════════════════════════════════════════════════════════════════════════════
# Scoring risque
# ═══════════════════════════════════════════════════════════════════════════════

class RiskScoreRequest(BaseModel):
    pan:                str
    amount:             int   = Field(gt=0)
    currency:           str   = Field(default="978", min_length=3, max_length=3)
    mcc:                Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    is_contactless:     bool          = False
    contactless_cumul:  int   = Field(default=0, ge=0)
    consecutive_offline: int  = Field(default=0, ge=0)
    daily_count:        int   = Field(default=0, ge=0)
    hourly_count:       int   = Field(default=0, ge=0)
    hour:               Optional[int] = Field(default=None, ge=0, le=23)

    @field_validator("pan", mode="before")
    @classmethod
    def validate_pan(cls, v):
        cleaned = _clean_pan(str(v))
        if not _PAN_RE.match(cleaned):
            raise ValueError("PAN invalide")
        return cleaned

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v):
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError("Montant invalide")


# ── Helper pour les réponses d'erreur Pydantic ────────────────────────────────

def pydantic_error_response(exc) -> dict:
    """Formate une ValidationError Pydantic en réponse JSON claire."""
    errors = []
    for e in exc.errors():
        loc  = " → ".join(str(x) for x in e["loc"]) if e["loc"] else "body"
        errors.append({"field": loc, "message": e["msg"]})
    return {"error": "Validation échouée", "details": errors}
