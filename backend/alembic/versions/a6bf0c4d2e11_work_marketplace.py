"""Public evidence and the work marketplace."""

from alembic import op
import sqlalchemy as sa

from app.types import UtcDateTime

revision = "a6bf0c4d2e11"
down_revision = "f4b2c81e7a64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_publications",
        sa.Column("evidence_record_id", sa.Integer(), sa.ForeignKey("evidence_records.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("author_name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text()),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("published_at", UtcDateTime(), nullable=False),
    )
    op.create_table(
        "work_holdings",
        sa.Column("evidence_record_id", sa.Integer(), sa.ForeignKey("evidence_records.id"), primary_key=True),
        sa.Column("holder_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
    )
    op.create_index("ix_work_holdings_holder_id", "work_holdings", ["holder_id"])
    op.create_table(
        "work_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("evidence_record_id", sa.Integer(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("buyer_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_work_listings_positive_price"),
    )
    op.create_index("ix_work_listings_status_id", "work_listings", ["status", "id"])
    active = sa.text("status = 'active'")
    op.create_index(
        "uq_work_listings_active", "work_listings", ["evidence_record_id"], unique=True,
        sqlite_where=active, postgresql_where=active,
    )
    op.create_table(
        "work_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_id", sa.String(36), nullable=False, unique=True),
        sa.Column("listing_id", sa.Integer(), sa.ForeignKey("work_listings.id"), nullable=False, unique=True),
        sa.Column("evidence_record_id", sa.Integer(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("buyer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tx_id", sa.String(64)),
        sa.Column("recorded_at", UtcDateTime()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", UtcDateTime()),
        sa.Column("next_attempt_at", UtcDateTime()),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint("evidence_record_id", "sequence", name="uq_work_trades_sequence"),
    )
    op.create_index("ix_work_trades_buyer_id", "work_trades", ["buyer_id"])
    op.create_index("ix_work_trades_seller_id", "work_trades", ["seller_id"])
    op.create_index("ix_work_trades_status_due", "work_trades", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("work_trades")
    op.drop_table("work_listings")
    op.drop_table("work_holdings")
    op.drop_table("work_publications")
