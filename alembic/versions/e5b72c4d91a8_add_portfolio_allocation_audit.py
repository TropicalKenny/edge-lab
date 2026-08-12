"""add portfolio allocation audit

Revision ID: e5b72c4d91a8
Revises: d4a61e90c337
Create Date: 2026-08-12 23:48:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5b72c4d91a8"
down_revision: Union[str, Sequence[str], None] = "d4a61e90c337"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_allocation_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("external_run_id", sa.String(100), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("nav_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("authorized_working_capital_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("vault_usd_untouched", sa.Numeric(28, 8), nullable=False),
        sa.Column("reserve_floor_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("allocated_notional_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("planned_risk_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_run_id"),
    )
    op.create_index("ix_portfolio_allocation_runs_external_run_id", "portfolio_allocation_runs", ["external_run_id"], unique=True)
    op.create_index("ix_portfolio_allocation_runs_created_at", "portfolio_allocation_runs", ["created_at"])

    op.create_table(
        "portfolio_allocation_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("candidate_id", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(100), nullable=False),
        sa.Column("strategy_version", sa.String(100), nullable=False),
        sa.Column("venue", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(120), nullable=False),
        sa.Column("correlation_bucket", sa.String(100), nullable=False),
        sa.Column("evidence_status", sa.String(16), nullable=False),
        sa.Column("requested_notional_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("approved_notional_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("planned_loss_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("score", sa.Numeric(28, 12), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("run_id", "candidate_id", "strategy", "venue", "correlation_bucket", "created_at"):
        op.create_index(f"ix_portfolio_allocation_decisions_{column}", "portfolio_allocation_decisions", [column])

    op.create_table(
        "treasury_rebalance_proposals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(100), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("amount_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(28, 8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("proposal_only", sa.Boolean(), nullable=False),
        sa.Column("requires_owner_approval", sa.Boolean(), nullable=False),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("run_id", "destination", "created_at"):
        op.create_index(f"ix_treasury_rebalance_proposals_{column}", "treasury_rebalance_proposals", [column])


def downgrade() -> None:
    for column in ("created_at", "destination", "run_id"):
        op.drop_index(f"ix_treasury_rebalance_proposals_{column}", table_name="treasury_rebalance_proposals")
    op.drop_table("treasury_rebalance_proposals")
    for column in ("created_at", "correlation_bucket", "venue", "strategy", "candidate_id", "run_id"):
        op.drop_index(f"ix_portfolio_allocation_decisions_{column}", table_name="portfolio_allocation_decisions")
    op.drop_table("portfolio_allocation_decisions")
    op.drop_index("ix_portfolio_allocation_runs_created_at", table_name="portfolio_allocation_runs")
    op.drop_index("ix_portfolio_allocation_runs_external_run_id", table_name="portfolio_allocation_runs")
    op.drop_table("portfolio_allocation_runs")
