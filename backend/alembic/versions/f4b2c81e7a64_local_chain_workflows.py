"""Persist local-chain confirmations and video evidence.

Revision ID: f4b2c81e7a64
Revises: c1a2b3d4e5f6
"""

from alembic import op
import sqlalchemy as sa

from app.types import UtcDateTime

revision = "f4b2c81e7a64"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("evidence_ref", sa.String(32), nullable=True))
    op.add_column(
        "credit_ledger",
        sa.Column("adjustment_debit", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("chain_ops", sa.Column("signed_tx", sa.Text(), nullable=True))
    op.add_column("chain_ops", sa.Column("deployment_id", sa.String(66), nullable=True))
    op.add_column("chain_ops", sa.Column("lease_token", sa.String(32), nullable=True))
    op.add_column("chain_ops", sa.Column("lease_until", UtcDateTime(), nullable=True))
    op.add_column("chain_ops", sa.Column("next_attempt_at", UtcDateTime(), nullable=True))
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="SET NULL")),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("network_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("chaincode", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tx_id", sa.String(64)),
        sa.Column("recorded_at", UtcDateTime()),
        sa.Column("confirmed_at", UtcDateTime()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", UtcDateTime()),
        sa.Column("next_attempt_at", UtcDateTime()),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("asset_id"),
        sa.UniqueConstraint("evidence_id"),
    )
    op.create_index(
        "ix_evidence_records_status_due", "evidence_records", ["status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_records_status_due", table_name="evidence_records")
    op.drop_table("evidence_records")
    for name in ("next_attempt_at", "lease_until", "lease_token", "deployment_id", "signed_tx"):
        op.drop_column("chain_ops", name)
    op.drop_column("credit_ledger", "adjustment_debit")
    op.drop_column("users", "evidence_ref")
