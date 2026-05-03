"""
Transaction model — champs TPA, tranche montant, GIE CB.
"""

import uuid
from datetime import datetime


class TransactionStatus:
    APPROVED      = "APPROVED"
    DECLINED      = "DECLINED"
    PENDING       = "PENDING"
    REVERSED      = "REVERSED"
    ERROR         = "ERROR"
    PREAUTHORIZED = "PREAUTHORIZED"   # E4 — En attente de capture
    DISPUTED      = "DISPUTED"        # E6 — Dispute ouverte
    CHARGEBACK    = "CHARGEBACK"      # E6 — Chargeback émis


class Transaction:
    def __init__(self, pan, amount, currency, transaction_type,
                 terminal_id=None, merchant_id=None, merchant_name=None,
                 atc=None, arqc=None, emv_data=None, pos_entry_mode=None):
        self.id = str(uuid.uuid4())
        self.pan = pan
        self.amount = amount
        self.currency = currency
        self.transaction_type = transaction_type
        self.terminal_id = terminal_id
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.atc = atc
        self.arqc = arqc
        self.emv_data = emv_data
        self.pos_entry_mode = pos_entry_mode
        self.status = TransactionStatus.PENDING
        self.response_code = None
        self.arpc = None
        self.issuer_auth_data = None
        self.auth_code = None
        self.created_at = datetime.utcnow().isoformat()
        self.processed_at = None
        self.decline_reason = None
        self.rrn = self._generate_rrn()
        # Journal d'audit
        self.events = []
        # Redressements
        self.reversed_at = None
        self.reversal_amount = None
        self.reversal_rrn = None
        self.reversal_terminal_id = None
        self.is_partial_reversal = False
        # Tranches montant
        self.amount_tier = None
        self.risk_level = None
        self.auth_path = None
        # Champs GIE CB
        self.cb_scheme = None
        self.cb_brand = None
        self.cb_service_indicator = None
        self.cb_sca_exemption = None
        self.cb_floor_limit = None
        self.cb_is_contactless = False
        self.cb_response_code = None
        self.cb_decline_reason = None
        self.aid = None

    def _generate_rrn(self):
        now = datetime.utcnow()
        return now.strftime("%y%j") + str(uuid.uuid4().int)[:6]

    def approve(self, auth_code, arpc=None, issuer_auth_data=None):
        self.status = TransactionStatus.APPROVED
        self.response_code = "00"
        self.auth_code = auth_code
        self.arpc = arpc
        self.issuer_auth_data = issuer_auth_data
        self.processed_at = datetime.utcnow().isoformat()

    def decline(self, response_code, reason=None):
        self.status = TransactionStatus.DECLINED
        self.response_code = response_code
        self.decline_reason = reason
        self.processed_at = datetime.utcnow().isoformat()

    def log_event(self, stage: str, message: str,
                  level: str = "INFO", data: dict | None = None):
        """Ajoute un événement d'audit au journal de la transaction."""
        self.events.append({
            "stage":   stage,
            "at":      datetime.utcnow().isoformat(),
            "level":   level,
            "message": message,
            "data":    data or {},
        })

    def error(self, reason):
        self.status = TransactionStatus.ERROR
        self.response_code = "96"
        self.decline_reason = reason
        self.processed_at = datetime.utcnow().isoformat()

    def reverse(self, reversal_amount=None, reversal_rrn=None, terminal_id=None):
        """
        Marque la transaction comme redressée.
        reversal_amount = montant redressé (défaut : montant total).
        Appelé par emv/reversal.py après validation.
        """
        amount = reversal_amount if reversal_amount is not None else self.amount
        self.status = TransactionStatus.REVERSED
        self.reversed_at = datetime.utcnow().isoformat()
        self.reversal_amount = amount
        self.reversal_rrn = reversal_rrn
        self.reversal_terminal_id = terminal_id
        self.is_partial_reversal = (amount < self.amount)

    def to_dict(self, masked=True):
        pan_display = "*" * (len(self.pan) - 4) + self.pan[-4:] if masked else self.pan
        return {
            "id": self.id,
            "rrn": self.rrn,
            "pan": pan_display,
            "amount": self.amount,
            "amount_formatted": "{:.2f}".format(self.amount / 100),
            "currency": self.currency,
            "transaction_type": self.transaction_type,
            "terminal_id": self.terminal_id,
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "atc": self.atc,
            "arqc": self.arqc,
            "arpc": self.arpc,
            "issuer_auth_data": self.issuer_auth_data,
            "auth_code": self.auth_code,
            "status": self.status,
            "response_code": self.response_code,
            "decline_reason": self.decline_reason,
            "pos_entry_mode": self.pos_entry_mode,
            "amount_tier": self.amount_tier,
            "risk_level": self.risk_level,
            "auth_path": self.auth_path,
            "cb_scheme": self.cb_scheme,
            "cb_brand": self.cb_brand,
            "cb_service_indicator": self.cb_service_indicator,
            "cb_sca_exemption": self.cb_sca_exemption,
            "cb_floor_limit": self.cb_floor_limit,
            "cb_is_contactless": self.cb_is_contactless,
            "cb_response_code": self.cb_response_code,
            "cb_decline_reason": self.cb_decline_reason,
            "created_at": self.created_at,
            "processed_at": self.processed_at,
            "reversed_at": getattr(self, "reversed_at", None),
            "reversal_amount": getattr(self, "reversal_amount", None),
            "reversal_amount_formatted": (
                "{:.2f}".format(self.reversal_amount / 100)
                if getattr(self, "reversal_amount", None) is not None else None
            ),
            "is_partial_reversal": getattr(self, "is_partial_reversal", False),
        }


class TransactionLog:
    def __init__(self):
        self._transactions = {}
        self._pan_index = {}

    def add(self, transaction):
        self._transactions[transaction.id] = transaction
        pan = transaction.pan
        if pan not in self._pan_index:
            self._pan_index[pan] = []
        self._pan_index[pan].append(transaction.id)

    def get(self, transaction_id):
        return self._transactions.get(transaction_id)

    def get_by_pan(self, pan, limit=20):
        ids = self._pan_index.get(pan, [])
        return [self._transactions[i] for i in ids[-limit:] if i in self._transactions]

    def get_by_rrn(self, rrn: str):
        """Retrouve une transaction par son RRN (Retrieval Reference Number)."""
        for txn in self._transactions.values():
            if txn.rrn == rrn:
                return txn
        return None

    def get_all(self, limit=100, offset=0, status=None, tier=None,
                date_from=None, date_to=None,
                amount_min=None, amount_max=None,
                terminal_id=None, merchant_id=None,
                cb_scheme=None, auth_path=None, rrn=None):
        all_txns = list(self._transactions.values())
        if status:
            all_txns = [t for t in all_txns if t.status == status.upper()]
        if tier:
            all_txns = [t for t in all_txns if t.amount_tier == tier.upper()]
        if date_from:
            all_txns = [t for t in all_txns if t.created_at >= date_from]
        if date_to:
            all_txns = [t for t in all_txns if t.created_at <= date_to]
        if amount_min is not None:
            all_txns = [t for t in all_txns if t.amount >= amount_min]
        if amount_max is not None:
            all_txns = [t for t in all_txns if t.amount <= amount_max]
        if terminal_id:
            all_txns = [t for t in all_txns
                        if (t.terminal_id or "").lower() == terminal_id.lower()]
        if merchant_id:
            all_txns = [t for t in all_txns
                        if (t.merchant_id or "").lower() == merchant_id.lower()]
        if cb_scheme:
            all_txns = [t for t in all_txns
                        if (t.cb_scheme or "").upper() == cb_scheme.upper()]
        if auth_path:
            all_txns = [t for t in all_txns
                        if (t.auth_path or "").upper() == auth_path.upper()]
        if rrn:
            all_txns = [t for t in all_txns if t.rrn == rrn]
        all_txns.sort(key=lambda t: t.created_at, reverse=True)
        return all_txns[offset:offset + limit]

    def count(self, status=None, tier=None, date_from=None, date_to=None,
              amount_min=None, amount_max=None,
              terminal_id=None, merchant_id=None,
              cb_scheme=None, auth_path=None, rrn=None) -> int:
        """Compte les transactions correspondant aux filtres sans les paginer."""
        return len(self.get_all(
            limit=999999, offset=0,
            status=status, tier=tier,
            date_from=date_from, date_to=date_to,
            amount_min=amount_min, amount_max=amount_max,
            terminal_id=terminal_id, merchant_id=merchant_id,
            cb_scheme=cb_scheme, auth_path=auth_path, rrn=rrn,
        ))

    def get_stats(self):
        total         = len(self._transactions)
        approved      = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.APPROVED)
        declined      = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.DECLINED)
        reversed_     = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.REVERSED)
        errors        = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.ERROR)
        preauthed     = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.PREAUTHORIZED)
        disputed      = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.DISPUTED)
        chargebacks   = sum(1 for t in self._transactions.values()
                            if t.status == TransactionStatus.CHARGEBACK)
        total_amount  = sum(t.amount for t in self._transactions.values()
                            if t.status == TransactionStatus.APPROVED)
        reversed_amount = sum(
            getattr(t, "reversal_amount", None) or t.amount
            for t in self._transactions.values()
            if t.status == TransactionStatus.REVERSED
        )
        by_tier, by_path, by_risk, by_cb_scheme, by_status = {}, {}, {}, {}, {}
        for t in self._transactions.values():
            if t.amount_tier:
                by_tier[t.amount_tier] = by_tier.get(t.amount_tier, 0) + 1
            if t.auth_path:
                by_path[t.auth_path] = by_path.get(t.auth_path, 0) + 1
            if t.risk_level:
                by_risk[t.risk_level] = by_risk.get(t.risk_level, 0) + 1
            if t.cb_scheme:
                by_cb_scheme[t.cb_scheme] = by_cb_scheme.get(t.cb_scheme, 0) + 1
            by_status[t.status] = by_status.get(t.status, 0) + 1
        return {
            "total":                          total,
            "approved":                       approved,
            "declined":                       declined,
            "reversed":                       reversed_,
            "reversed_amount":                reversed_amount,
            "reversed_amount_formatted":      "{:.2f}".format(reversed_amount / 100),
            "errors":                         errors,
            "preauthorized":                  preauthed,
            "disputed":                       disputed,
            "chargebacks":                    chargebacks,
            "approval_rate":                  "{:.1f}%".format(
                (approved / total * 100) if total > 0 else 0),
            "total_approved_amount":          total_amount,
            "total_approved_amount_formatted":"{:.2f}".format(total_amount / 100),
            "by_tier":                        by_tier,
            "by_auth_path":                   by_path,
            "by_risk_level":                  by_risk,
            "by_cb_scheme":                   by_cb_scheme,
            "by_status":                      by_status,
        }


transaction_log = TransactionLog()
