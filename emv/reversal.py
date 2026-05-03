"""
Traitement des redressements (reversals) EMV / ISO 8583.

Un redressement annule (partiellement ou totalement) une transaction
préalablement approuvée. Il restaure le solde et la limite journalière
de la carte, puis marque la transaction originale comme REVERSED.

Types de redressements supportés :
  - Redressement complet  (montant = montant original)
  - Redressement partiel  (montant < montant original) — pré-autorisation
  - Avis de redressement  (MTI 0420) — pas de réponse attendue

Codes de réponse :
  00  Redressement accepté
  25  Transaction originale introuvable
  40  Transaction non redressable (déjà refusée, erreur, etc.)
  56  Aucune réponse précédente (transaction déjà redressée)
  61  Montant de redressement supérieur au montant original
"""

import logging
from datetime import datetime

from models.card import card_db
from models.transaction import transaction_log, TransactionStatus

logger = logging.getLogger(__name__)


class ReversalError(Exception):
    """Erreur métier lors d'un redressement."""
    def __init__(self, message: str, response_code: str = "40"):
        super().__init__(message)
        self.response_code = response_code


class ReversalResult:
    """Résultat d'un traitement de redressement."""

    def __init__(self, accepted: bool, response_code: str,
                 original_transaction=None, reversal_amount: int = 0,
                 message: str = "", is_advice: bool = False):
        self.accepted = accepted
        self.response_code = response_code
        self.original_transaction = original_transaction
        self.reversal_amount = reversal_amount
        self.message = message
        self.is_advice = is_advice

    def to_dict(self) -> dict:
        d = {
            "accepted":         self.accepted,
            "response_code":    self.response_code,
            "reversal_amount":  self.reversal_amount,
            "reversal_amount_formatted": "{:.2f}".format(self.reversal_amount / 100),
            "message":          self.message,
            "is_advice":        self.is_advice,
        }
        if self.original_transaction:
            d["original_transaction"] = self.original_transaction.to_dict()
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Résolution de la transaction originale
# ─────────────────────────────────────────────────────────────────────────────

def find_original_transaction(transaction_id: str | None = None,
                              rrn: str | None = None):
    """
    Retrouve la transaction originale par ID ou par RRN.
    Retourne None si introuvable.
    """
    if transaction_id:
        txn = transaction_log.get(transaction_id)
        if txn:
            return txn

    if rrn:
        # Parcours du journal — les transactions récentes sont indexées
        for txn in transaction_log._transactions.values():
            if txn.rrn == rrn:
                return txn

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Logique de validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_reversal(original_txn, reversal_amount: int) -> None:
    """
    Valide les conditions d'un redressement.
    Lève ReversalError si le redressement ne peut pas être accepté.
    """
    if original_txn.status == TransactionStatus.REVERSED:
        raise ReversalError(
            "Transaction déjà redressée",
            response_code="56",
        )
    if original_txn.status in (TransactionStatus.DECLINED,
                                TransactionStatus.ERROR):
        raise ReversalError(
            f"Impossible de redresser une transaction {original_txn.status}",
            response_code="40",
        )
    if original_txn.status == TransactionStatus.PENDING:
        raise ReversalError(
            "La transaction est encore en attente de traitement",
            response_code="40",
        )
    if original_txn.status != TransactionStatus.APPROVED:
        raise ReversalError(
            "La transaction originale n'est pas approuvée",
            response_code="40",
        )
    if reversal_amount <= 0:
        raise ReversalError(
            "Le montant du redressement doit être positif",
            response_code="13",
        )
    if reversal_amount > original_txn.amount:
        raise ReversalError(
            f"Montant de redressement ({reversal_amount}) supérieur "
            f"au montant original ({original_txn.amount})",
            response_code="61",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Application du redressement
# ─────────────────────────────────────────────────────────────────────────────

def _apply_reversal(original_txn, reversal_amount: int,
                    reversal_rrn: str | None = None,
                    terminal_id: str | None = None) -> None:
    """
    Applique le redressement : met à jour la transaction et la carte.
    Modification en place — à appeler seulement après validate_reversal().
    """
    now = datetime.utcnow().isoformat()

    # ── Mise à jour de la transaction ────────────────────────────────────────
    original_txn.status        = TransactionStatus.REVERSED
    original_txn.reversed_at   = now
    original_txn.reversal_amount = reversal_amount
    original_txn.reversal_rrn  = reversal_rrn
    original_txn.reversal_terminal_id = terminal_id
    original_txn.is_partial_reversal = (reversal_amount < original_txn.amount)

    # ── Restauration du solde carte ──────────────────────────────────────────
    pan = original_txn.pan
    card = card_db.get_card(pan)
    if card:
        card.balance    += reversal_amount
        card.daily_spent = max(0, card.daily_spent - reversal_amount)
        logger.info(
            "[REVERSAL] PAN=****%s | montant=%d | nouveau_solde=%d",
            pan[-4:], reversal_amount, card.balance,
        )
    else:
        logger.warning(
            "[REVERSAL] Carte introuvable pour PAN=****%s — solde non restauré",
            pan[-4:],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Point d'entrée principal
# ─────────────────────────────────────────────────────────────────────────────

def process_reversal(transaction_id: str | None = None,
                     rrn: str | None = None,
                     reversal_amount: int | None = None,
                     reversal_rrn: str | None = None,
                     terminal_id: str | None = None,
                     is_advice: bool = False) -> ReversalResult:
    """
    Traite un redressement (0400) ou un avis de redressement (0420).

    Paramètres :
      transaction_id  ID interne de la transaction originale
      rrn             Retrieval Reference Number de la transaction originale
      reversal_amount Montant à redresser (centimes) — défaut : montant total
      reversal_rrn    RRN du message de redressement
      terminal_id     Terminal demandeur
      is_advice       True si c'est un avis (0420) — accepté sans validation stricte

    Retourne un ReversalResult avec accepted=True/False et response_code.
    """
    logger.info(
        "[REVERSAL] Début traitement — txn_id=%s rrn=%s advice=%s",
        transaction_id, rrn, is_advice,
    )

    # ── 1. Résolution de la transaction originale ────────────────────────────
    original_txn = find_original_transaction(transaction_id, rrn)
    if not original_txn:
        msg = "Transaction originale introuvable"
        logger.warning("[REVERSAL] %s (id=%s, rrn=%s)", msg, transaction_id, rrn)
        return ReversalResult(
            accepted=False,
            response_code="25",
            message=msg,
            is_advice=is_advice,
        )

    # ── 2. Montant du redressement (défaut = montant total) ──────────────────
    amount_to_reverse = (
        reversal_amount
        if reversal_amount is not None
        else original_txn.amount
    )

    # ── 3. Validation ────────────────────────────────────────────────────────
    try:
        validate_reversal(original_txn, amount_to_reverse)
    except ReversalError as exc:
        # Pour un avis (0420), on accepte quand même (idempotent)
        if is_advice and original_txn.status == TransactionStatus.REVERSED:
            return ReversalResult(
                accepted=True,
                response_code="00",
                original_transaction=original_txn,
                reversal_amount=amount_to_reverse,
                message="Avis de redressement accepté (déjà redressé)",
                is_advice=True,
            )
        logger.warning("[REVERSAL] Validation échouée : %s (RC=%s)", exc, exc.response_code)
        return ReversalResult(
            accepted=False,
            response_code=exc.response_code,
            original_transaction=original_txn,
            reversal_amount=amount_to_reverse,
            message=str(exc),
            is_advice=is_advice,
        )

    # ── 4. Application ───────────────────────────────────────────────────────
    _apply_reversal(original_txn, amount_to_reverse, reversal_rrn, terminal_id)

    partial = amount_to_reverse < original_txn.amount
    msg = (
        f"Redressement partiel accepté ({amount_to_reverse/100:.2f}€ "
        f"sur {original_txn.amount/100:.2f}€)"
        if partial
        else "Redressement complet accepté"
    )
    logger.info(
        "[REVERSAL] Accepté — txn_id=%s | montant=%d | partiel=%s",
        original_txn.id, amount_to_reverse, partial,
    )

    return ReversalResult(
        accepted=True,
        response_code="00",
        original_transaction=original_txn,
        reversal_amount=amount_to_reverse,
        message=msg,
        is_advice=is_advice,
    )
