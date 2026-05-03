"""001 — Schéma initial EMV Authorization Server v1.6.0

Revision ID: 001_initial
Revises:
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision     = "001_initial"
down_revision = None
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── cards ─────────────────────────────────────────────────────────────────
    op.create_table(
        "cards",
        sa.Column("pan",                    sa.String(19),  primary_key=True),
        sa.Column("expiry",                 sa.String(4),   nullable=False),
        sa.Column("cardholder_name",        sa.String(100)),
        sa.Column("psn",                    sa.String(2),   server_default="00"),
        sa.Column("status",                 sa.String(20),  server_default="ACTIVE"),
        sa.Column("balance",                sa.Integer(),   server_default="100000"),
        sa.Column("daily_limit",            sa.Integer(),   server_default="500000"),
        sa.Column("daily_spent",            sa.Integer(),   server_default="0"),
        sa.Column("last_reset_date",        sa.String(10)),
        sa.Column("last_atc",               sa.Integer(),   server_default="0"),
        sa.Column("created_at",             sa.String(30)),
        sa.Column("block_reason",           sa.Text()),
        sa.Column("blocked_at",             sa.String(30)),
        sa.Column("unblocked_at",           sa.String(30)),
        sa.Column("block_history",          sa.JSON(),      server_default="[]"),
        sa.Column("cb_scheme",              sa.String(20),  server_default="VISA"),
        sa.Column("cb_brand",               sa.String(30),  server_default="VISA CB"),
        sa.Column("aid",                    sa.String(20)),
        sa.Column("contactless_cumul",      sa.Integer(),   server_default="0"),
        sa.Column("consecutive_offline",    sa.Integer(),   server_default="0"),
        sa.Column("last_contactless_reset", sa.String(10)),
        sa.Column("pin_tries",              sa.Integer(),   server_default="0"),
        sa.Column("max_pin_tries",          sa.Integer(),   server_default="3"),
        sa.Column("pin_hash",               sa.String(64)),
        sa.Column("master_key_ac",          sa.String(64)),
        sa.Column("master_key_enc",         sa.String(64)),
        sa.Column("master_key_mac",         sa.String(64)),
    )

    # ── transactions ──────────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id",                    sa.String(36),  primary_key=True),
        sa.Column("pan",                   sa.String(19),  nullable=False),
        sa.Column("amount",                sa.Integer()),
        sa.Column("currency",              sa.String(3)),
        sa.Column("transaction_type",      sa.String(2)),
        sa.Column("terminal_id",           sa.String(20)),
        sa.Column("merchant_id",           sa.String(20)),
        sa.Column("merchant_name",         sa.String(100)),
        sa.Column("atc",                   sa.Integer()),
        sa.Column("arqc",                  sa.String(32)),
        sa.Column("emv_data",              sa.Text()),
        sa.Column("pos_entry_mode",        sa.String(3)),
        sa.Column("status",                sa.String(20),  server_default="PENDING"),
        sa.Column("response_code",         sa.String(2)),
        sa.Column("auth_code",             sa.String(6)),
        sa.Column("arpc",                  sa.String(32)),
        sa.Column("issuer_auth_data",      sa.String(32)),
        sa.Column("rrn",                   sa.String(20)),
        sa.Column("created_at",            sa.String(30)),
        sa.Column("processed_at",          sa.String(30)),
        sa.Column("decline_reason",        sa.Text()),
        sa.Column("events",                sa.JSON(),      server_default="[]"),
        sa.Column("amount_tier",           sa.String(20)),
        sa.Column("risk_level",            sa.String(20)),
        sa.Column("auth_path",             sa.String(20)),
        sa.Column("cb_scheme",             sa.String(20)),
        sa.Column("cb_brand",              sa.String(30)),
        sa.Column("cb_is_contactless",     sa.Boolean(),   server_default="false"),
        sa.Column("cb_sca_exemption",      sa.String(20)),
        sa.Column("cb_floor_limit",        sa.Integer()),
        sa.Column("cb_response_code",      sa.String(2)),
        sa.Column("cb_decline_reason",     sa.Text()),
        sa.Column("cb_service_indicator",  sa.String(2)),
        sa.Column("reversed_at",           sa.String(30)),
        sa.Column("reversal_amount",       sa.Integer()),
        sa.Column("reversal_rrn",          sa.String(20)),
        sa.Column("reversal_terminal_id",  sa.String(20)),
        sa.Column("is_partial_reversal",   sa.Boolean(),   server_default="false"),
        sa.Column("aid",                   sa.String(20)),
        sa.Column("mcc",                   sa.String(4)),
    )
    op.create_index("ix_transactions_pan",        "transactions", ["pan"])
    op.create_index("ix_transactions_rrn",        "transactions", ["rrn"])
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])
    op.create_index("ix_transactions_status",     "transactions", ["status"])

    # ── preauths ──────────────────────────────────────────────────────────────
    op.create_table(
        "preauths",
        sa.Column("id",                sa.String(36),  primary_key=True),
        sa.Column("rrn",               sa.String(20)),
        sa.Column("mti",               sa.String(4),   server_default="0100"),
        sa.Column("pan",               sa.String(19),  nullable=False),
        sa.Column("authorized_amount", sa.Integer()),
        sa.Column("captured_amount",   sa.Integer(),   server_default="0"),
        sa.Column("currency",          sa.String(3)),
        sa.Column("terminal_id",       sa.String(20)),
        sa.Column("merchant_id",       sa.String(20)),
        sa.Column("merchant_name",     sa.String(100)),
        sa.Column("original_txn_id",   sa.String(36)),
        sa.Column("status",            sa.String(20),  server_default="PENDING"),
        sa.Column("expiry_hours",      sa.Integer(),   server_default="24"),
        sa.Column("notes",             sa.Text()),
        sa.Column("created_at",        sa.String(30)),
        sa.Column("captured_at",       sa.String(30)),
        sa.Column("cancelled_at",      sa.String(30)),
        sa.Column("capture_rrn",       sa.String(20)),
    )
    op.create_index("ix_preauths_pan", "preauths", ["pan"])

    # ── chargebacks ───────────────────────────────────────────────────────────
    op.create_table(
        "chargebacks",
        sa.Column("id",             sa.String(36),  primary_key=True),
        sa.Column("rrn",            sa.String(20)),
        sa.Column("mti",            sa.String(4),   server_default="0620"),
        sa.Column("transaction_id", sa.String(36),  nullable=False),
        sa.Column("reason_code",    sa.String(6)),
        sa.Column("amount",         sa.Integer()),
        sa.Column("currency",       sa.String(3)),
        sa.Column("status",         sa.String(20),  server_default="OPEN"),
        sa.Column("initiated_by",   sa.String(50),  server_default="PORTEUR"),
        sa.Column("notes",          sa.Text()),
        sa.Column("created_at",     sa.String(30)),
        sa.Column("reversal_at",    sa.String(30)),
        sa.Column("resolved_at",    sa.String(30)),
        sa.Column("resolution",     sa.String(20)),
    )
    op.create_index("ix_chargebacks_txn_id", "chargebacks", ["transaction_id"])
    op.create_index("ix_chargebacks_status",  "chargebacks", ["status"])

    # ── bin_blacklist_bins ────────────────────────────────────────────────────
    op.create_table(
        "bin_blacklist_bins",
        sa.Column("prefix",   sa.String(10), primary_key=True),
        sa.Column("reason",   sa.Text()),
        sa.Column("added_at", sa.String(30)),
        sa.Column("added_by", sa.String(50), server_default="API"),
    )

    # ── bin_blacklist_pans ────────────────────────────────────────────────────
    op.create_table(
        "bin_blacklist_pans",
        sa.Column("pan",        sa.String(19), primary_key=True),
        sa.Column("pan_masked", sa.String(19)),
        sa.Column("reason",     sa.Text()),
        sa.Column("added_at",   sa.String(30)),
        sa.Column("added_by",   sa.String(50), server_default="API"),
    )

    # ── webhook_log ───────────────────────────────────────────────────────────
    op.create_table(
        "webhook_log",
        sa.Column("id",       sa.String(20),  primary_key=True),
        sa.Column("event",    sa.String(50)),
        sa.Column("url",      sa.Text()),
        sa.Column("status",   sa.String(20)),
        sa.Column("payload",  sa.JSON(),      server_default="{}"),
        sa.Column("sent_at",  sa.String(30)),
        sa.Column("response", sa.Integer()),
        sa.Column("error",    sa.Text()),
    )
    op.create_index("ix_webhook_log_sent_at", "webhook_log", ["sent_at"])


def downgrade() -> None:
    op.drop_table("webhook_log")
    op.drop_table("bin_blacklist_pans")
    op.drop_table("bin_blacklist_bins")
    op.drop_table("chargebacks")
    op.drop_table("preauths")
    op.drop_table("transactions")
    op.drop_table("cards")
