"""
Transaction model — avec champs TPA et tranche de montant.
"""

import uuid
from datetime import datetime


class TransactionStatus:
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"
    ERROR = "ERROR"


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
        # Champs TPA / tranche montant
        self.amount_tier = None
        self.risk_level = None
        self.auth_path = None

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

    def error(self, reason):
        self.status = TransactionStatus.ERROR
        self.response_code = "96"
        self.decline_reason = reason
        self.processed_at = datetime.utcnow().isoformat()

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
            "created_at": self.created_at,
            "processed_at": self.processed_at,
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

    def get_all(self, limit=100, offset=0, status=None, tier=None):
        all_txns = list(self._transactions.values())
        if status:
            all_txns = [t for t in all_txns if t.status == status.upper()]
        if tier:
            all_txns = [t for t in all_txns if t.amount_tier == tier.upper()]
        all_txns.sort(key=lambda t: t.created_at, reverse=True)
        return all_txns[offset:offset + limit]

    def get_stats(self):
        total = len(self._transactions)
        approved = sum(1 for t in self._transactions.values()
                       if t.status == TransactionStatus.APPROVED)
        declined = sum(1 for t in self._transactions.values()
                       if t.status == TransactionStatus.DECLINED)
        errors = sum(1 for t in self._transactions.values()
                     if t.status == TransactionStatus.ERROR)
        total_amount = sum(t.amount for t in self._transactions.values()
                           if t.status == TransactionStatus.APPROVED)

        by_tier = {}
        by_path = {}
        by_risk = {}
        for t in self._transactions.values():
            if t.amount_tier:
                by_tier[t.amount_tier] = by_tier.get(t.amount_tier, 0) + 1
            if t.auth_path:
                by_path[t.auth_path] = by_path.get(t.auth_path, 0) + 1
            if t.risk_level:
                by_risk[t.risk_level] = by_risk.get(t.risk_level, 0) + 1

        return {
            "total": total,
            "approved": approved,
            "declined": declined,
            "errors": errors,
            "approval_rate": "{:.1f}%".format(
                (approved / total * 100) if total > 0 else 0),
            "total_approved_amount": total_amount,
            "total_approved_amount_formatted": "{:.2f}".format(total_amount / 100),
            "by_tier": by_tier,
            "by_auth_path": by_path,
            "by_risk_level": by_risk,
        }


transaction_log = TransactionLog()
