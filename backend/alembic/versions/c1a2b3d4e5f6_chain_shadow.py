"""chain shadow: 3 tables（方案 B：积分上链的影子表）

Revision ID: c1a2b3d4e5f6
Revises: e211cfb31c17
Create Date: 2026-11-10 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.types

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'e211cfb31c17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chain_wallets',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=42), nullable=False),
        sa.Column('private_key', sa.String(length=66), nullable=False),
        sa.Column('created_at', app.types.UtcDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('address', name='uq_chain_wallets_address'),
    )

    op.create_table(
        'chain_ops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('ref', sa.String(length=80), nullable=False),
        sa.Column('video_id_hash', sa.String(length=66), nullable=True),
        sa.Column('tx_hash', sa.String(length=66), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', app.types.UtcDateTime(timezone=True), nullable=False),
        sa.Column('updated_at', app.types.UtcDateTime(timezone=True), nullable=False),
        sa.CheckConstraint('amount > 0', name='ck_chain_ops_amount_positive'),
        sa.CheckConstraint('attempts >= 0', name='ck_chain_ops_attempts_nonneg'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ref', name='uq_chain_ops_ref'),
    )
    op.create_index('ix_chain_ops_status_id', 'chain_ops', ['status', 'id'], unique=False)
    op.create_index(
        'ix_chain_ops_user_created', 'chain_ops', ['user_id', 'created_at'], unique=False
    )

    op.create_table(
        'chain_state',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', app.types.UtcDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('chain_state')
    op.drop_index('ix_chain_ops_user_created', table_name='chain_ops')
    op.drop_index('ix_chain_ops_status_id', table_name='chain_ops')
    op.drop_table('chain_ops')
    op.drop_table('chain_wallets')
