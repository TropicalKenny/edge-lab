"""add strategy evaluation runs

Revision ID: f6d83a20c511
Revises: e5b72c4d91a8
Create Date: 2026-08-13 05:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6d83a20c511"
down_revision: Union[str, Sequence[str], None] = "e5b72c4d91a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_evaluation_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("external_run_id", sa.String(100), nullable=False),
        sa.Column("strategy_version_id", sa.String(36), nullable=False),
        sa.Column("strategy_slug", sa.String(100), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("family", sa.String(32), nullable=False),
        sa.Column("recommendation", sa.String(32), nullable=False),
        sa.Column("forward_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forward_days", sa.Integer(), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("forecast_count", sa.Integer(), nullable=False),
        sa.Column("execution_observation_count", sa.Integer(), nullable=False),
        sa.Column("net_pnl_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("stressed_net_pnl_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("max_drawdown_pct", sa.Numeric(18, 10), nullable=True),
        sa.Column("profit_factor", sa.Numeric(18, 10), nullable=True),
        sa.Column("brier_score", sa.Numeric(18, 10), nullable=True),
        sa.Column("calibration_error", sa.Numeric(18, 10), nullable=True),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("reasons_json", sa.Text(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_run_id"),
    )
    op.create_index("ix_strategy_evaluation_runs_external_run_id", "strategy_evaluation_runs", ["external_run_id"], unique=True)
    for column in ("strategy_version_id", "strategy_slug", "strategy_version", "family", "recommendation", "created_at"):
        op.create_index(f"ix_strategy_evaluation_runs_{column}", "strategy_evaluation_runs", [column])


def downgrade() -> None:
    for column in ("created_at", "recommendation", "family", "strategy_version", "strategy_slug", "strategy_version_id"):
        op.drop_index(f"ix_strategy_evaluation_runs_{column}", table_name="strategy_evaluation_runs")
    op.drop_index("ix_strategy_evaluation_runs_external_run_id", table_name="strategy_evaluation_runs")
    op.drop_table("strategy_evaluation_runs")
