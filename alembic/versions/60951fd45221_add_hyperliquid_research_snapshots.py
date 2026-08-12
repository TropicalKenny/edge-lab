"""add hyperliquid research snapshots

Revision ID: 60951fd45221
Revises: 5a2cf4b6a731
Create Date: 2026-08-12 22:13:12.388110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '60951fd45221'
down_revision: Union[str, Sequence[str], None] = '5a2cf4b6a731'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('hyperliquid_funding_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('coin', sa.String(length=80), nullable=False),
    sa.Column('funding_rate', sa.Numeric(precision=20, scale=12), nullable=False),
    sa.Column('premium', sa.Numeric(precision=20, scale=12), nullable=True),
    sa.Column('funding_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hyperliquid_funding_snapshots')),
    sa.UniqueConstraint('coin', 'funding_time', name='hyperliquid_funding_coin_time_unique')
    )
    op.create_index(op.f('ix_hyperliquid_funding_snapshots_coin'), 'hyperliquid_funding_snapshots', ['coin'], unique=False)
    op.create_index(op.f('ix_hyperliquid_funding_snapshots_funding_time'), 'hyperliquid_funding_snapshots', ['funding_time'], unique=False)
    op.create_table('hyperliquid_perp_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('coin', sa.String(length=80), nullable=False),
    sa.Column('mark_px', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('mid_px', sa.Numeric(precision=28, scale=10), nullable=True),
    sa.Column('oracle_px', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('funding_rate_hourly', sa.Numeric(precision=20, scale=12), nullable=False),
    sa.Column('premium', sa.Numeric(precision=20, scale=12), nullable=True),
    sa.Column('open_interest', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('day_ntl_volume', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hyperliquid_perp_snapshots'))
    )
    op.create_index(op.f('ix_hyperliquid_perp_snapshots_captured_at'), 'hyperliquid_perp_snapshots', ['captured_at'], unique=False)
    op.create_index(op.f('ix_hyperliquid_perp_snapshots_coin'), 'hyperliquid_perp_snapshots', ['coin'], unique=False)
    op.create_table('hyperliquid_spot_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('pair', sa.String(length=120), nullable=False),
    sa.Column('book_coin', sa.String(length=80), nullable=False),
    sa.Column('base', sa.String(length=80), nullable=False),
    sa.Column('quote', sa.String(length=80), nullable=False),
    sa.Column('mid_px', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('day_ntl_volume', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hyperliquid_spot_snapshots'))
    )
    op.create_index(op.f('ix_hyperliquid_spot_snapshots_captured_at'), 'hyperliquid_spot_snapshots', ['captured_at'], unique=False)
    op.create_index(op.f('ix_hyperliquid_spot_snapshots_pair'), 'hyperliquid_spot_snapshots', ['pair'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hyperliquid_spot_snapshots_pair'), table_name='hyperliquid_spot_snapshots')
    op.drop_index(op.f('ix_hyperliquid_spot_snapshots_captured_at'), table_name='hyperliquid_spot_snapshots')
    op.drop_table('hyperliquid_spot_snapshots')
    op.drop_index(op.f('ix_hyperliquid_perp_snapshots_coin'), table_name='hyperliquid_perp_snapshots')
    op.drop_index(op.f('ix_hyperliquid_perp_snapshots_captured_at'), table_name='hyperliquid_perp_snapshots')
    op.drop_table('hyperliquid_perp_snapshots')
    op.drop_index(op.f('ix_hyperliquid_funding_snapshots_funding_time'), table_name='hyperliquid_funding_snapshots')
    op.drop_index(op.f('ix_hyperliquid_funding_snapshots_coin'), table_name='hyperliquid_funding_snapshots')
    op.drop_table('hyperliquid_funding_snapshots')
