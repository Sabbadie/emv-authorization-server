"""
Modèles ORM SQLAlchemy 2.0 — correspondance avec les classes domaine.
Tous les modèles héritent de database.Base pour être reconnus par Alembic.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, Text, Index,
    JSON as SA_JSON,
)
from database import Base


class CardORM(Base):
    __tablename__ = "cards"

    pan                    = Column(String(19), primary_key=True)
    expiry                 = Column(String(4),  nullable=False)
    cardholder_name        = Column(String(100))
    psn                    = Column(String(2),   default="00")
    status                 = Column(String(20),  default="ACTIVE")
    balance                = Column(Integer,     default=100000)
    daily_limit            = Column(Integer,     default=500000)
    daily_spent            = Column(Integer,     default=0)
    last_reset_date        = Column(String(10))
    last_atc               = Column(Integer,     default=0)
    created_at             = Column(String(30))
    block_reason           = Column(Text,        nullable=True)
    blocked_at             = Column(String(30),  nullable=True)
    unblocked_at           = Column(String(30),  nullable=True)
    block_history          = Column(SA_JSON,     default=list)
    cb_scheme              = Column(String(20),  default="VISA")
    cb_brand               = Column(String(30),  default="VISA CB")
    aid                    = Column(String(20),  nullable=True)
    contactless_cumul      = Column(Integer,     default=0)
    consecutive_offline    = Column(Integer,     default=0)
    last_contactless_reset = Column(String(10))
    pin_tries              = Column(Integer,     default=0)
    max_pin_tries          = Column(Integer,     default=3)
    pin_hash               = Column(String(64),  nullable=True)
    master_key_ac          = Column(String(64))
    master_key_enc         = Column(String(64))
    master_key_mac         = Column(String(64))

    def __repr__(self):
        return f"<CardORM pan=...{self.pan[-4:]} status={self.status}>"


class TransactionORM(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_pan",        "pan"),
        Index("ix_transactions_rrn",        "rrn"),
        Index("ix_transactions_created_at", "created_at"),
        Index("ix_transactions_status",     "status"),
    )

    id                   = Column(String(36),  primary_key=True)
    pan                  = Column(String(19),  nullable=False)
    amount               = Column(Integer)
    currency             = Column(String(3))
    transaction_type     = Column(String(2))
    terminal_id          = Column(String(20),  nullable=True)
    merchant_id          = Column(String(20),  nullable=True)
    merchant_name        = Column(String(100), nullable=True)
    atc                  = Column(Integer,     nullable=True)
    arqc                 = Column(String(32),  nullable=True)
    emv_data             = Column(Text,        nullable=True)
    pos_entry_mode       = Column(String(3),   nullable=True)
    status               = Column(String(20),  default="PENDING")
    response_code        = Column(String(2),   nullable=True)
    auth_code            = Column(String(6),   nullable=True)
    arpc                 = Column(String(32),  nullable=True)
    issuer_auth_data     = Column(String(32),  nullable=True)
    rrn                  = Column(String(20))
    created_at           = Column(String(30))
    processed_at         = Column(String(30),  nullable=True)
    decline_reason       = Column(Text,        nullable=True)
    events               = Column(SA_JSON,     default=list)
    amount_tier          = Column(String(20),  nullable=True)
    risk_level           = Column(String(20),  nullable=True)
    auth_path            = Column(String(20),  nullable=True)
    cb_scheme            = Column(String(20),  nullable=True)
    cb_brand             = Column(String(30),  nullable=True)
    cb_is_contactless    = Column(Boolean,     default=False)
    cb_sca_exemption     = Column(String(20),  nullable=True)
    cb_floor_limit       = Column(Integer,     nullable=True)
    cb_response_code     = Column(String(2),   nullable=True)
    cb_decline_reason    = Column(Text,        nullable=True)
    cb_service_indicator = Column(String(2),   nullable=True)
    reversed_at          = Column(String(30),  nullable=True)
    reversal_amount      = Column(Integer,     nullable=True)
    reversal_rrn         = Column(String(20),  nullable=True)
    reversal_terminal_id = Column(String(20),  nullable=True)
    is_partial_reversal  = Column(Boolean,     default=False)
    aid                  = Column(String(20),  nullable=True)
    mcc                  = Column(String(4),   nullable=True)

    def __repr__(self):
        return f"<TransactionORM id={self.id[:8]} status={self.status}>"


class PreAuthORM(Base):
    __tablename__ = "preauths"
    __table_args__ = (
        Index("ix_preauths_pan", "pan"),
    )

    id                = Column(String(36), primary_key=True)
    rrn               = Column(String(20))
    mti               = Column(String(4),   default="0100")
    pan               = Column(String(19),  nullable=False)
    authorized_amount = Column(Integer)
    captured_amount   = Column(Integer,     default=0)
    currency          = Column(String(3))
    terminal_id       = Column(String(20),  nullable=True)
    merchant_id       = Column(String(20),  nullable=True)
    merchant_name     = Column(String(100), nullable=True)
    original_txn_id   = Column(String(36),  nullable=True)
    status            = Column(String(20),  default="PENDING")
    expiry_hours      = Column(Integer,     default=24)
    notes             = Column(Text,        nullable=True)
    created_at        = Column(String(30))
    captured_at       = Column(String(30),  nullable=True)
    cancelled_at      = Column(String(30),  nullable=True)
    capture_rrn       = Column(String(20),  nullable=True)

    def __repr__(self):
        return f"<PreAuthORM id={self.id[:8]} status={self.status}>"


class ChargebackORM(Base):
    __tablename__ = "chargebacks"
    __table_args__ = (
        Index("ix_chargebacks_txn_id", "transaction_id"),
        Index("ix_chargebacks_status", "status"),
    )

    id             = Column(String(36), primary_key=True)
    rrn            = Column(String(20))
    mti            = Column(String(4),  default="0620")
    transaction_id = Column(String(36), nullable=False)
    reason_code    = Column(String(6))
    amount         = Column(Integer)
    currency       = Column(String(3),  nullable=True)
    status         = Column(String(20), default="OPEN")
    initiated_by   = Column(String(50), default="PORTEUR")
    notes          = Column(Text,       nullable=True)
    created_at     = Column(String(30))
    reversal_at    = Column(String(30), nullable=True)
    resolved_at    = Column(String(30), nullable=True)
    resolution     = Column(String(20), nullable=True)

    def __repr__(self):
        return f"<ChargebackORM id={self.id[:8]} status={self.status}>"


class BINBlacklistBinORM(Base):
    __tablename__ = "bin_blacklist_bins"

    prefix   = Column(String(10), primary_key=True)
    reason   = Column(Text)
    added_at = Column(String(30))
    added_by = Column(String(50), default="API")

    def __repr__(self):
        return f"<BINBlacklistBinORM prefix={self.prefix}>"


class BINBlacklistPanORM(Base):
    __tablename__ = "bin_blacklist_pans"

    pan        = Column(String(19), primary_key=True)
    pan_masked = Column(String(19))
    reason     = Column(Text)
    added_at   = Column(String(30))
    added_by   = Column(String(50), default="API")

    def __repr__(self):
        return f"<BINBlacklistPanORM masked={self.pan_masked}>"


class WebhookLogORM(Base):
    __tablename__ = "webhook_log"
    __table_args__ = (
        Index("ix_webhook_log_sent_at", "sent_at"),
    )

    id       = Column(String(20), primary_key=True)
    event    = Column(String(50))
    url      = Column(Text,        nullable=True)
    status   = Column(String(20))
    payload  = Column(SA_JSON,     default=dict)
    sent_at  = Column(String(30))
    response = Column(Integer,     nullable=True)
    error    = Column(Text,        nullable=True)

    def __repr__(self):
        return f"<WebhookLogORM id={self.id} event={self.event}>"
