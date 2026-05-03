"""
Disputes / Chargebacks — E6
MTI 0620 (ouverture chargeback) · MTI 0630 (annulation chargeback).

Codes motif CB01–CB12 alignés avec les pratiques GIE CB / Visa / Mastercard.
Cycle de vie : OPEN → ACCEPTED | REJECTED | REVERSED | ARBITRATION
"""
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CHARGEBACK_REASON_CODES = {
    "CB01": "Transaction non reconnue par le porteur",
    "CB02": "Transaction dupliquée",
    "CB03": "Commerçant non livré / prestation non fournie",
    "CB04": "Erreur de montant",
    "CB05": "Fraude confirmée — carte présente",
    "CB06": "Fraude confirmée — carte non présente (CNP)",
    "CB07": "Transaction non autorisée par l'émetteur",
    "CB08": "Dépassement du délai de présentation",
    "CB09": "Erreur de devise / montant de conversion incorrect",
    "CB10": "Chargeback d'office (processing error)",
    "CB11": "Annulation non créditée au porteur",
    "CB12": "Produit retourné / service annulé — remboursement non effectué",
}

CHARGEBACK_STATUSES = {
    "OPEN":         "Ouvert — en cours d'instruction",
    "ACCEPTED":     "Accepté — commerçant concède",
    "REJECTED":     "Rejeté — émetteur débouté",
    "REVERSED":     "Reversé (MTI 0630 — chargeback annulé)",
    "ARBITRATION":  "En arbitrage CB/Visa/MC",
}

_chargeback_store = {}   # cb_id   -> Chargeback
_cb_txn_index    = {}    # txn_id  -> [cb_ids]


class Chargeback:
    def __init__(self, transaction_id, reason_code, amount=None,
                 initiated_by=None, notes=None):
        self.id            = str(uuid.uuid4())
        self.mti           = "0620"
        self.transaction_id = transaction_id
        self.reason_code   = reason_code
        self.reason_label  = CHARGEBACK_REASON_CODES.get(reason_code, "Motif inconnu")
        self.amount        = amount
        self.status        = "OPEN"
        self.initiated_by  = initiated_by or "PORTEUR"
        self.notes         = notes
        self.created_at    = datetime.utcnow().isoformat()
        self.resolved_at   = None
        self.reversal_at   = None
        self.rrn           = self._gen_rrn()

    def _gen_rrn(self) -> str:
        now = datetime.utcnow()
        return "CB" + now.strftime("%y%j") + str(uuid.uuid4().int)[:4]

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "rrn":            self.rrn,
            "mti":            self.mti,
            "transaction_id": self.transaction_id,
            "reason_code":    self.reason_code,
            "reason_label":   self.reason_label,
            "amount":         self.amount,
            "amount_formatted": "{:.2f}".format(self.amount / 100) if self.amount else None,
            "status":         self.status,
            "status_label":   CHARGEBACK_STATUSES.get(self.status, self.status),
            "initiated_by":   self.initiated_by,
            "notes":          self.notes,
            "created_at":     self.created_at,
            "resolved_at":    self.resolved_at,
            "reversal_at":    self.reversal_at,
        }


class ChargebackResult:
    def __init__(self, success, message, chargeback=None, error_code=None):
        self.success    = success
        self.message    = message
        self.chargeback = chargeback
        self.error_code = error_code

    def to_dict(self) -> dict:
        d = {"success": self.success, "message": self.message}
        if self.error_code:
            d["error_code"] = self.error_code
        if self.chargeback:
            d["chargeback"] = self.chargeback.to_dict()
        return d


# ── API publique ──────────────────────────────────────────────────────────────

def create_chargeback(transaction_id: str, reason_code: str,
                      amount: int = None, initiated_by: str = None,
                      notes: str = None) -> ChargebackResult:
    """
    Ouvre un chargeback sur une transaction approuvée (MTI 0620).
    """
    from models.transaction import transaction_log
    txn = transaction_log.get(transaction_id)
    if not txn:
        return ChargebackResult(False, "Transaction introuvable", error_code="25")
    if txn.status not in ("APPROVED", "REVERSED"):
        return ChargebackResult(False,
            f"Statut '{txn.status}' — chargeback impossible (APPROVED requis)",
            error_code="40")
    if reason_code not in CHARGEBACK_REASON_CODES:
        valid = ", ".join(sorted(CHARGEBACK_REASON_CODES.keys()))
        return ChargebackResult(False,
            f"Code motif inconnu : {reason_code}. Codes valides : {valid}",
            error_code="30")

    cb_amount = amount if amount is not None else txn.amount
    if cb_amount <= 0 or cb_amount > txn.amount:
        return ChargebackResult(False,
            "Montant chargeback invalide (0 < montant ≤ montant transaction)",
            error_code="13")

    cb = Chargeback(transaction_id=transaction_id, reason_code=reason_code,
                    amount=cb_amount, initiated_by=initiated_by, notes=notes)
    _chargeback_store[cb.id] = cb
    _cb_txn_index.setdefault(transaction_id, []).append(cb.id)

    txn.log_event("CHARGEBACK_OPENED",
                  f"Chargeback ouvert — {reason_code} : {cb.reason_label}",
                  level="WARN",
                  data={"chargeback_id": cb.id, "amount": cb_amount,
                        "reason_code": reason_code,
                        "initiated_by": cb.initiated_by})

    logger.info("Chargeback créé : %s TXN=%s Motif=%s Montant=%d",
                cb.id, transaction_id, reason_code, cb_amount)
    return ChargebackResult(True, "Chargeback ouvert (MTI 0620)", chargeback=cb)


def reverse_chargeback(chargeback_id: str,
                       notes: str = None) -> ChargebackResult:
    """Annule un chargeback ouvert (MTI 0630 — chargeback reversal)."""
    cb = _chargeback_store.get(chargeback_id)
    if not cb:
        return ChargebackResult(False, "Chargeback introuvable", error_code="25")
    if cb.status != "OPEN":
        return ChargebackResult(False,
            f"Statut '{cb.status}' — chargeback non annulable", error_code="40")

    cb.status      = "REVERSED"
    cb.reversal_at = datetime.utcnow().isoformat()
    cb.mti         = "0630"
    if notes:
        cb.notes = (cb.notes or "") + " | Reversal: " + notes

    from models.transaction import transaction_log
    txn = transaction_log.get(cb.transaction_id)
    if txn:
        txn.log_event("CHARGEBACK_REVERSED",
                      f"Chargeback annulé : {chargeback_id}",
                      level="INFO",
                      data={"chargeback_id": chargeback_id, "mti": "0630"})

    logger.info("Chargeback annulé (0630) : %s", chargeback_id)
    return ChargebackResult(True, "Chargeback annulé (MTI 0630)", chargeback=cb)


def resolve_chargeback(chargeback_id: str, resolution: str,
                       notes: str = None) -> ChargebackResult:
    """
    Résout un chargeback : ACCEPTED, REJECTED ou ARBITRATION.
    """
    valid_resolutions = ("ACCEPTED", "REJECTED", "ARBITRATION")
    resolution = resolution.upper()
    if resolution not in valid_resolutions:
        return ChargebackResult(False,
            f"Résolution invalide. Valeurs : {valid_resolutions}", error_code="30")

    cb = _chargeback_store.get(chargeback_id)
    if not cb:
        return ChargebackResult(False, "Chargeback introuvable", error_code="25")
    if cb.status != "OPEN":
        return ChargebackResult(False,
            f"Statut '{cb.status}' — non modifiable", error_code="40")

    cb.status      = resolution
    cb.resolved_at = datetime.utcnow().isoformat()
    if notes:
        cb.notes = (cb.notes or "") + " | Résolution: " + notes
    return ChargebackResult(True, f"Chargeback {resolution}", chargeback=cb)


def get_chargeback(cb_id: str) -> Chargeback | None:
    return _chargeback_store.get(cb_id)


def get_chargebacks_by_txn(transaction_id: str) -> list:
    ids = _cb_txn_index.get(transaction_id, [])
    return [_chargeback_store[i] for i in ids if i in _chargeback_store]


def get_all_chargebacks(limit: int = 50, offset: int = 0,
                        status: str = None) -> list:
    all_cb = list(_chargeback_store.values())
    if status:
        all_cb = [c for c in all_cb if c.status == status.upper()]
    all_cb.sort(key=lambda c: c.created_at, reverse=True)
    return all_cb[offset: offset + limit]


def count_chargebacks(status: str = None) -> int:
    return len(get_all_chargebacks(limit=999999, status=status))
