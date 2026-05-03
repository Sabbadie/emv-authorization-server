"""
Préautorisation + capture différée — E4
MTI 0100 (préautorisation) · MTI 0200 (capture) · MTI 0400 (annulation).

Cas d'usage : hôtels, locations de voiture, stations-service.
Cycle de vie : PENDING → CAPTURED | PARTIAL | CANCELLED | EXPIRED
"""
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PREAUTH_STATUSES = {
    "PENDING":   "Préautorisation en attente de capture",
    "CAPTURED":  "Capturée — montant total",
    "PARTIAL":   "Capture partielle — solde non capturé annulé",
    "CANCELLED": "Annulée avant capture",
    "EXPIRED":   "Expirée (délai de capture dépassé)",
}

_preauth_store = {}   # preauth_id -> PreAuth
_preauth_index = {}   # pan         -> [preauth_ids]


class PreAuth:
    """Représente une préautorisation en attente de capture."""

    def __init__(self, pan, authorized_amount, currency,
                 terminal_id=None, merchant_id=None, merchant_name=None,
                 original_txn_id=None, expiry_hours=24, notes=None):
        self.id               = str(uuid.uuid4())
        self.pan              = pan.replace(" ", "")
        self.authorized_amount = authorized_amount
        self.captured_amount   = 0
        self.currency          = currency
        self.terminal_id       = terminal_id
        self.merchant_id       = merchant_id
        self.merchant_name     = merchant_name
        self.original_txn_id   = original_txn_id
        self.status            = "PENDING"
        self.notes             = notes
        self.expiry_hours      = expiry_hours
        self.created_at        = datetime.utcnow().isoformat()
        self.captured_at       = None
        self.cancelled_at      = None
        self.rrn               = self._gen_rrn()
        self.capture_rrn       = None
        self.mti               = "0100"

    def _gen_rrn(self) -> str:
        now = datetime.utcnow()
        return "PA" + now.strftime("%y%j") + str(uuid.uuid4().int)[:6]

    @property
    def remaining_amount(self) -> int:
        return max(self.authorized_amount - self.captured_amount, 0)

    @property
    def captured_formatted(self) -> str:
        return "{:.2f}".format(self.captured_amount / 100)

    @property
    def authorized_formatted(self) -> str:
        return "{:.2f}".format(self.authorized_amount / 100)

    @property
    def remaining_formatted(self) -> str:
        return "{:.2f}".format(self.remaining_amount / 100)

    def to_dict(self) -> dict:
        pan = self.pan
        return {
            "id":                    self.id,
            "rrn":                   self.rrn,
            "mti":                   self.mti,
            "pan":                   "*" * (len(pan) - 4) + pan[-4:],
            "authorized_amount":     self.authorized_amount,
            "authorized_formatted":  "{:.2f}".format(self.authorized_amount / 100),
            "captured_amount":       self.captured_amount,
            "captured_formatted":    "{:.2f}".format(self.captured_amount / 100),
            "remaining_amount":      self.remaining_amount,
            "remaining_formatted":   "{:.2f}".format(self.remaining_amount / 100),
            "currency":              self.currency,
            "terminal_id":           self.terminal_id,
            "merchant_id":           self.merchant_id,
            "merchant_name":         self.merchant_name,
            "original_txn_id":       self.original_txn_id,
            "status":                self.status,
            "status_label":          PREAUTH_STATUSES.get(self.status, self.status),
            "expiry_hours":          self.expiry_hours,
            "notes":                 self.notes,
            "created_at":            self.created_at,
            "captured_at":           self.captured_at,
            "cancelled_at":          self.cancelled_at,
            "capture_rrn":           self.capture_rrn,
        }


class PreAuthResult:
    def __init__(self, success, message, preauth=None,
                 captured_amount=None, error_code=None):
        self.success         = success
        self.message         = message
        self.preauth         = preauth
        self.captured_amount = captured_amount
        self.error_code      = error_code

    def to_dict(self) -> dict:
        d = {"success": self.success, "message": self.message}
        if self.error_code:
            d["error_code"] = self.error_code
        if self.preauth:
            d["preauth"] = self.preauth.to_dict()
        if self.captured_amount is not None:
            d["captured_amount"] = self.captured_amount
            d["captured_formatted"] = "{:.2f}".format(self.captured_amount / 100)
        return d


# ── API publique ──────────────────────────────────────────────────────────────

def create_preauth(pan: str, authorized_amount: int, currency: str,
                   terminal_id=None, merchant_id=None, merchant_name=None,
                   original_txn_id=None, expiry_hours=24,
                   notes=None) -> PreAuthResult:
    """
    Crée une préautorisation (MTI 0100).
    La transaction d'autorisation doit avoir été approuvée au préalable.
    """
    pan = pan.replace(" ", "")
    if authorized_amount <= 0:
        return PreAuthResult(False, "Montant autorisé invalide", error_code="13")

    pa = PreAuth(pan=pan, authorized_amount=authorized_amount,
                 currency=currency, terminal_id=terminal_id,
                 merchant_id=merchant_id, merchant_name=merchant_name,
                 original_txn_id=original_txn_id,
                 expiry_hours=expiry_hours, notes=notes)
    _preauth_store[pa.id] = pa
    _preauth_index.setdefault(pan, []).append(pa.id)

    logger.info("Préautorisation créée : %s PAN=...%s Montant=%d",
                pa.id, pan[-4:], authorized_amount)
    return PreAuthResult(True, "Préautorisation créée", preauth=pa)


def capture(preauth_id: str, capture_amount: int = None,
            capture_rrn: str = None) -> PreAuthResult:
    """
    Capture une préautorisation (MTI 0200).
    capture_amount ≤ authorized_amount (capture partielle acceptée).
    """
    pa = _preauth_store.get(preauth_id)
    if not pa:
        return PreAuthResult(False, "Préautorisation introuvable", error_code="25")
    if pa.status != "PENDING":
        return PreAuthResult(False,
            f"Statut '{pa.status}' — capture impossible", error_code="40")

    amount = capture_amount if capture_amount is not None else pa.authorized_amount
    if amount <= 0:
        return PreAuthResult(False, "Montant de capture invalide", error_code="13")
    if amount > pa.authorized_amount:
        return PreAuthResult(False,
            "Montant capture ({:.2f} €) > montant autorisé ({:.2f} €)".format(
                amount / 100, pa.authorized_amount / 100), error_code="61")

    pa.captured_amount = amount
    pa.status          = "CAPTURED" if amount == pa.authorized_amount else "PARTIAL"
    pa.captured_at     = datetime.utcnow().isoformat()
    pa.capture_rrn     = capture_rrn or ("CAP" + pa._gen_rrn()[2:])
    pa.mti             = "0200"

    logger.info("Capture effectuée : %s Montant=%d Statut=%s",
                preauth_id, amount, pa.status)
    return PreAuthResult(True,
        "Capture effectuée ({:.2f} €)".format(amount / 100),
        preauth=pa, captured_amount=amount)


def cancel_preauth(preauth_id: str, reason: str = None) -> PreAuthResult:
    """Annule une préautorisation avant capture (MTI 0400)."""
    pa = _preauth_store.get(preauth_id)
    if not pa:
        return PreAuthResult(False, "Préautorisation introuvable", error_code="25")
    if pa.status != "PENDING":
        return PreAuthResult(False,
            f"Statut '{pa.status}' — annulation impossible", error_code="40")

    pa.status       = "CANCELLED"
    pa.cancelled_at = datetime.utcnow().isoformat()
    pa.mti          = "0400"
    if reason:
        pa.notes = (pa.notes or "") + " | Annulation: " + reason

    logger.info("Préautorisation annulée : %s Raison=%s", preauth_id, reason)
    return PreAuthResult(True, "Préautorisation annulée", preauth=pa)


def get_preauth(preauth_id: str) -> PreAuth | None:
    return _preauth_store.get(preauth_id)


def get_preauths_by_pan(pan: str, limit: int = 20) -> list:
    pan = pan.replace(" ", "")
    ids = _preauth_index.get(pan, [])
    return [_preauth_store[i] for i in ids[-limit:] if i in _preauth_store]


def get_all_preauths(limit: int = 50, offset: int = 0,
                     status: str = None) -> list:
    all_pa = list(_preauth_store.values())
    if status:
        all_pa = [p for p in all_pa if p.status == status.upper()]
    all_pa.sort(key=lambda p: p.created_at, reverse=True)
    return all_pa[offset: offset + limit]


def count_preauths(status: str = None) -> int:
    return len(get_all_preauths(limit=999999, status=status))
