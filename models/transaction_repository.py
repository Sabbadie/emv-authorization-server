"""
TransactionRepository — implémentation DB-backed de TransactionLog (P1).
Actif uniquement lorsque DATABASE_URL est configuré.
"""
import logging
from datetime import datetime

from sqlalchemy import select, desc

from database import get_session
from models.transaction import Transaction, TransactionLog, TransactionStatus
from models.orm_models import TransactionORM

logger = logging.getLogger(__name__)


# ── Convertisseurs ORM ↔ domaine ──────────────────────────────────────────────

def _orm_to_txn(row: TransactionORM) -> Transaction:
    txn = Transaction.__new__(Transaction)
    txn.id                   = row.id
    txn.pan                  = row.pan
    txn.amount               = row.amount or 0
    txn.currency             = row.currency or "978"
    txn.transaction_type     = row.transaction_type or "00"
    txn.terminal_id          = row.terminal_id
    txn.merchant_id          = row.merchant_id
    txn.merchant_name        = row.merchant_name
    txn.atc                  = row.atc
    txn.arqc                 = row.arqc
    txn.emv_data             = row.emv_data
    txn.pos_entry_mode       = row.pos_entry_mode
    txn.status               = row.status or "PENDING"
    txn.response_code        = row.response_code
    txn.auth_code            = row.auth_code
    txn.arpc                 = row.arpc
    txn.issuer_auth_data     = row.issuer_auth_data
    txn.rrn                  = row.rrn or ""
    txn.created_at           = row.created_at or datetime.utcnow().isoformat()
    txn.processed_at         = row.processed_at
    txn.decline_reason       = row.decline_reason
    txn.events               = row.events or []
    txn.amount_tier          = row.amount_tier
    txn.risk_level           = row.risk_level
    txn.auth_path            = row.auth_path
    txn.cb_scheme            = row.cb_scheme
    txn.cb_brand             = row.cb_brand
    txn.cb_is_contactless    = row.cb_is_contactless or False
    txn.cb_sca_exemption     = row.cb_sca_exemption
    txn.cb_floor_limit       = row.cb_floor_limit
    txn.cb_response_code     = row.cb_response_code
    txn.cb_decline_reason    = row.cb_decline_reason
    txn.cb_service_indicator = row.cb_service_indicator
    txn.reversed_at          = row.reversed_at
    txn.reversal_amount      = row.reversal_amount
    txn.reversal_rrn         = row.reversal_rrn
    txn.reversal_terminal_id = row.reversal_terminal_id
    txn.is_partial_reversal  = row.is_partial_reversal or False
    txn.aid                  = row.aid
    return txn


def _txn_to_orm(txn: Transaction, row: TransactionORM | None = None) -> TransactionORM:
    row = row or TransactionORM()
    row.id                   = txn.id
    row.pan                  = txn.pan
    row.amount               = txn.amount
    row.currency             = txn.currency
    row.transaction_type     = txn.transaction_type
    row.terminal_id          = txn.terminal_id
    row.merchant_id          = txn.merchant_id
    row.merchant_name        = txn.merchant_name
    row.atc                  = txn.atc
    row.arqc                 = txn.arqc
    row.emv_data             = txn.emv_data
    row.pos_entry_mode       = txn.pos_entry_mode
    row.status               = txn.status
    row.response_code        = txn.response_code
    row.auth_code            = txn.auth_code
    row.arpc                 = txn.arpc
    row.issuer_auth_data     = txn.issuer_auth_data
    row.rrn                  = txn.rrn
    row.created_at           = txn.created_at
    row.processed_at         = txn.processed_at
    row.decline_reason       = txn.decline_reason
    row.events               = getattr(txn, "events", [])
    row.amount_tier          = txn.amount_tier
    row.risk_level           = txn.risk_level
    row.auth_path            = txn.auth_path
    row.cb_scheme            = txn.cb_scheme
    row.cb_brand             = txn.cb_brand
    row.cb_is_contactless    = txn.cb_is_contactless
    row.cb_sca_exemption     = txn.cb_sca_exemption
    row.cb_floor_limit       = txn.cb_floor_limit
    row.cb_response_code     = txn.cb_response_code
    row.cb_decline_reason    = txn.cb_decline_reason
    row.cb_service_indicator = getattr(txn, "cb_service_indicator", None)
    row.reversed_at          = getattr(txn, "reversed_at", None)
    row.reversal_amount      = getattr(txn, "reversal_amount", None)
    row.reversal_rrn         = getattr(txn, "reversal_rrn", None)
    row.reversal_terminal_id = getattr(txn, "reversal_terminal_id", None)
    row.is_partial_reversal  = getattr(txn, "is_partial_reversal", False)
    row.aid                  = getattr(txn, "aid", None)
    return row


# ── Repository ────────────────────────────────────────────────────────────────

class DBTransactionLog(TransactionLog):
    """
    Implémentation PostgreSQL/SQLAlchemy de TransactionLog.
    Même interface que la version in-memory pour transparence totale.
    """

    def __init__(self):
        # N'appelle PAS super().__init__() — on n'utilise pas les dicts en mémoire
        self._transactions = {}   # non utilisé pour stockage ; conservé pour compat
        self._pan_index    = {}

    # ── Écriture ─────────────────────────────────────────────────────────────

    def add(self, txn: Transaction):
        try:
            with get_session() as session:
                existing = session.get(TransactionORM, txn.id)
                row = _txn_to_orm(txn, existing)
                session.merge(row)
        except Exception as exc:
            logger.error("TransactionLog.add(%s): %s", txn.id[:8], exc)

    # ── Lectures ─────────────────────────────────────────────────────────────

    def get(self, txn_id: str) -> Transaction | None:
        try:
            with get_session() as session:
                row = session.get(TransactionORM, txn_id)
                return _orm_to_txn(row) if row else None
        except Exception as exc:
            logger.error("TransactionLog.get(%s): %s", txn_id[:8], exc)
            return None

    def get_by_pan(self, pan: str, limit: int = 20) -> list:
        try:
            with get_session() as session:
                stmt = (
                    select(TransactionORM)
                    .where(TransactionORM.pan == pan)
                    .order_by(desc(TransactionORM.created_at))
                    .limit(limit)
                )
                return [_orm_to_txn(r) for r in session.execute(stmt).scalars()]
        except Exception as exc:
            logger.error("get_by_pan: %s", exc)
            return []

    def get_by_rrn(self, rrn: str) -> Transaction | None:
        try:
            with get_session() as session:
                stmt = (
                    select(TransactionORM)
                    .where(TransactionORM.rrn == rrn)
                    .limit(1)
                )
                row = session.execute(stmt).scalars().first()
                return _orm_to_txn(row) if row else None
        except Exception as exc:
            logger.error("get_by_rrn: %s", exc)
            return None

    def get_all(self, limit: int = 100, offset: int = 0,
                status=None, tier=None, date_from=None, date_to=None,
                amount_min=None, amount_max=None, terminal_id=None,
                merchant_id=None, cb_scheme=None, auth_path=None, rrn=None) -> list:
        try:
            with get_session() as session:
                stmt = select(TransactionORM)
                if status:
                    stmt = stmt.where(TransactionORM.status == status.upper())
                if tier:
                    stmt = stmt.where(TransactionORM.amount_tier == tier.upper())
                if date_from:
                    stmt = stmt.where(TransactionORM.created_at >= date_from)
                if date_to:
                    stmt = stmt.where(TransactionORM.created_at <= date_to)
                if amount_min is not None:
                    stmt = stmt.where(TransactionORM.amount >= int(amount_min))
                if amount_max is not None:
                    stmt = stmt.where(TransactionORM.amount <= int(amount_max))
                if terminal_id:
                    stmt = stmt.where(TransactionORM.terminal_id == terminal_id)
                if merchant_id:
                    stmt = stmt.where(TransactionORM.merchant_id == merchant_id)
                if cb_scheme:
                    stmt = stmt.where(TransactionORM.cb_scheme == cb_scheme.upper())
                if auth_path:
                    stmt = stmt.where(TransactionORM.auth_path == auth_path.upper())
                if rrn:
                    stmt = stmt.where(TransactionORM.rrn == rrn)
                stmt = (
                    stmt
                    .order_by(desc(TransactionORM.created_at))
                    .offset(offset)
                    .limit(limit)
                )
                return [_orm_to_txn(r) for r in session.execute(stmt).scalars()]
        except Exception as exc:
            logger.error("get_all: %s", exc)
            return []

    def get_recent(self, limit: int = 50) -> list:
        return self.get_all(limit=limit)

    # ── Statistiques ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        try:
            with get_session() as session:
                all_txns = session.execute(select(TransactionORM)).scalars().all()
                total        = len(all_txns)
                approved     = sum(1 for t in all_txns if t.status == TransactionStatus.APPROVED)
                declined     = sum(1 for t in all_txns if t.status == TransactionStatus.DECLINED)
                reversed_    = sum(1 for t in all_txns if t.status == TransactionStatus.REVERSED)
                errors       = sum(1 for t in all_txns if t.status == TransactionStatus.ERROR)
                preauthed    = sum(1 for t in all_txns if t.status == TransactionStatus.PREAUTHORIZED)
                disputed     = sum(1 for t in all_txns if t.status == TransactionStatus.DISPUTED)
                chargebacks  = sum(1 for t in all_txns if t.status == TransactionStatus.CHARGEBACK)
                total_amount = sum(t.amount or 0 for t in all_txns
                                   if t.status == TransactionStatus.APPROVED)
                rev_amount   = sum(
                    (t.reversal_amount or t.amount or 0)
                    for t in all_txns if t.status == TransactionStatus.REVERSED
                )
                by_tier, by_path, by_risk, by_scheme, by_status = {}, {}, {}, {}, {}
                for t in all_txns:
                    if t.amount_tier:
                        by_tier[t.amount_tier]   = by_tier.get(t.amount_tier, 0)   + 1
                    if t.auth_path:
                        by_path[t.auth_path]     = by_path.get(t.auth_path, 0)     + 1
                    if t.risk_level:
                        by_risk[t.risk_level]    = by_risk.get(t.risk_level, 0)    + 1
                    if t.cb_scheme:
                        by_scheme[t.cb_scheme]   = by_scheme.get(t.cb_scheme, 0)   + 1
                    by_status[t.status]          = by_status.get(t.status, 0)       + 1
                return {
                    "total":                         total,
                    "approved":                      approved,
                    "declined":                      declined,
                    "reversed":                      reversed_,
                    "reversed_amount":               rev_amount,
                    "reversed_amount_formatted":     "{:.2f}".format(rev_amount / 100),
                    "errors":                        errors,
                    "preauthorized":                 preauthed,
                    "disputed":                      disputed,
                    "chargebacks":                   chargebacks,
                    "approval_rate":                 "{:.1f}%".format(
                        (approved / total * 100) if total > 0 else 0),
                    "total_approved_amount":         total_amount,
                    "total_approved_amount_formatted": "{:.2f}".format(total_amount / 100),
                    "by_tier":                       by_tier,
                    "by_auth_path":                  by_path,
                    "by_risk_level":                 by_risk,
                    "by_cb_scheme":                  by_scheme,
                    "by_status":                     by_status,
                }
        except Exception as exc:
            logger.error("get_stats: %s", exc)
            return {
                "total": 0, "approved": 0, "declined": 0, "reversed": 0,
                "errors": 0, "approval_rate": "0.0%",
                "total_approved_amount": 0,
                "total_approved_amount_formatted": "0.00",
                "by_tier": {}, "by_auth_path": {}, "by_risk_level": {},
                "by_cb_scheme": {}, "by_status": {},
            }
