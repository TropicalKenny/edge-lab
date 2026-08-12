"""add polymarket structural research

Revision ID: 8c27f4a91b02
Revises: 60951fd45221
Create Date: 2026-08-12 22:31:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8c27f4a91b02"
down_revision: Union[str, Sequence[str], None] = "60951fd45221"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "polymarket_event_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("neg_risk", sa.Boolean(), nullable=False),
        sa.Column("neg_risk_augmented", sa.Boolean(), nullable=False),
        sa.Column("resolution_source", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_polymarket_event_snapshots")),
    )
    op.create_index(op.f("ix_polymarket_event_snapshots_event_id"), "polymarket_event_snapshots", ["event_id"], unique=False)
    op.create_index(op.f("ix_polymarket_event_snapshots_captured_at"), "polymarket_event_snapshots", ["captured_at"], unique=False)

    op.create_table(
        "polymarket_market_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=80), nullable=False),
        sa.Column("condition_id", sa.String(length=100), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("yes_token_id", sa.String(length=100), nullable=True),
        sa.Column("no_token_id", sa.String(length=100), nullable=True),
        sa.Column("accepting_orders", sa.Boolean(), nullable=False),
        sa.Column("neg_risk", sa.Boolean(), nullable=False),
        sa.Column("neg_risk_other", sa.Boolean(), nullable=False),
        sa.Column("fees_enabled", sa.Boolean(), nullable=False),
        sa.Column("fee_rate", sa.Numeric(precision=20, scale=12), nullable=True),
        sa.Column("fee_exponent", sa.Integer(), nullable=True),
        sa.Column("resolution_source", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_polymarket_market_snapshots")),
    )
    for column in ("market_id", "condition_id", "event_id", "captured_at"):
        op.create_index(op.f(f"ix_polymarket_market_snapshots_{column}"), "polymarket_market_snapshots", [column], unique=False)

    op.create_table(
        "polymarket_book_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("condition_id", sa.String(length=100), nullable=False),
        sa.Column("token_id", sa.String(length=100), nullable=False),
        sa.Column("best_bid", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("best_ask", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("bid_depth_shares", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("ask_depth_shares", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("min_order_size", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("tick_size", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column("neg_risk", sa.Boolean(), nullable=False),
        sa.Column("book_hash", sa.String(length=255), nullable=True),
        sa.Column("bids_json", sa.Text(), nullable=False),
        sa.Column("asks_json", sa.Text(), nullable=False),
        sa.Column("book_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_polymarket_book_snapshots")),
    )
    for column in ("condition_id", "token_id", "book_timestamp", "captured_at"):
        op.create_index(op.f(f"ix_polymarket_book_snapshots_{column}"), "polymarket_book_snapshots", [column], unique=False)

    op.create_table(
        "polymarket_structural_opportunities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=True),
        sa.Column("condition_id", sa.String(length=100), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("gross_cost", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("total_fees", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("payout", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("net_profit", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("roi_bps", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("legs_json", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_polymarket_structural_opportunities")),
    )
    for column in ("kind", "event_id", "condition_id", "captured_at"):
        op.create_index(op.f(f"ix_polymarket_structural_opportunities_{column}"), "polymarket_structural_opportunities", [column], unique=False)


def downgrade() -> None:
    for column in ("captured_at", "condition_id", "event_id", "kind"):
        op.drop_index(op.f(f"ix_polymarket_structural_opportunities_{column}"), table_name="polymarket_structural_opportunities")
    op.drop_table("polymarket_structural_opportunities")
    for column in ("captured_at", "book_timestamp", "token_id", "condition_id"):
        op.drop_index(op.f(f"ix_polymarket_book_snapshots_{column}"), table_name="polymarket_book_snapshots")
    op.drop_table("polymarket_book_snapshots")
    for column in ("captured_at", "event_id", "condition_id", "market_id"):
        op.drop_index(op.f(f"ix_polymarket_market_snapshots_{column}"), table_name="polymarket_market_snapshots")
    op.drop_table("polymarket_market_snapshots")
    op.drop_index(op.f("ix_polymarket_event_snapshots_captured_at"), table_name="polymarket_event_snapshots")
    op.drop_index(op.f("ix_polymarket_event_snapshots_event_id"), table_name="polymarket_event_snapshots")
    op.drop_table("polymarket_event_snapshots")
