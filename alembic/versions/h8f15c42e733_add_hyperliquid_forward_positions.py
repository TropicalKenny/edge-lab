"""add Hyperliquid carry forward positions

Revision ID: h8f15c42e733
Revises: g7e94b31d622
Create Date: 2026-08-13 05:55:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "h8f15c42e733"
down_revision: Union[str, Sequence[str], None] = "g7e94b31d622"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hyperliquid_carry_positions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("trade_record_id", sa.String(36), nullable=True),
        sa.Column("external_key", sa.String(160), nullable=False),
        sa.Column("coin", sa.String(32), nullable=False),
        sa.Column("spot_book_coin", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("allocated_capital_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("planned_loss_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_spot_mid", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_perp_mid", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_spot_price", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_perp_price", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_spot_fee_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_perp_fee_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_spot_slippage_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("entry_perp_slippage_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("exit_spot_mid", sa.Numeric(28, 10), nullable=True),
        sa.Column("exit_perp_mid", sa.Numeric(28, 10), nullable=True),
        sa.Column("exit_spot_price", sa.Numeric(28, 10), nullable=True),
        sa.Column("exit_perp_price", sa.Numeric(28, 10), nullable=True),
        sa.Column("funding_pnl_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("gross_pnl_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("fees_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("slippage_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("net_pnl_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("close_reason", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.ForeignKeyConstraint(["trade_record_id"], ["forward_trade_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="hl_carry_study_key_unique"),
    )
    for column in ("study_id", "trade_record_id", "coin", "status", "opened_at", "target_close_at"):
        op.create_index(f"ix_hyperliquid_carry_positions_{column}", "hyperliquid_carry_positions", [column])


def downgrade() -> None:
    for column in ("target_close_at", "opened_at", "status", "coin", "trade_record_id", "study_id"):
        op.drop_index(f"ix_hyperliquid_carry_positions_{column}", table_name="hyperliquid_carry_positions")
    op.drop_table("hyperliquid_carry_positions")
