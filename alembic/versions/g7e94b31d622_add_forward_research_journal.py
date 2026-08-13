"""add frozen forward research journal

Revision ID: g7e94b31d622
Revises: f6d83a20c511
Create Date: 2026-08-13 05:45:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "g7e94b31d622"
down_revision: Union[str, Sequence[str], None] = "f6d83a20c511"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forward_studies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("strategy_version_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("family", sa.String(32), nullable=False),
        sa.Column("venue", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("initial_capital_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("evaluation_policy_json", sa.Text(), nullable=False),
        sa.Column("study_config_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_forward_studies_external_id", "forward_studies", ["external_id"], unique=True)
    for column in ("strategy_version_id", "experiment_id", "family", "venue", "instrument", "status", "started_at"):
        op.create_index(f"ix_forward_studies_{column}", "forward_studies", [column])

    op.create_table(
        "forward_nav_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nav_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "observed_at", name="forward_nav_study_time_unique"),
    )
    op.create_index("ix_forward_nav_observations_study_id", "forward_nav_observations", ["study_id"])
    op.create_index("ix_forward_nav_observations_observed_at", "forward_nav_observations", ["observed_at"])

    op.create_table(
        "forward_trade_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("external_key", sa.String(140), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gross_pnl_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("net_pnl_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("fees_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("slippage_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("allocated_capital_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("planned_loss_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="forward_trade_study_key_unique"),
    )
    for column in ("study_id", "opened_at", "closed_at"):
        op.create_index(f"ix_forward_trade_records_{column}", "forward_trade_records", [column])

    op.create_table(
        "forward_execution_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("trade_id", sa.String(36), nullable=True),
        sa.Column("external_key", sa.String(160), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("intended_quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("paper_filled_quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("shadow_filled_quantity", sa.Numeric(28, 10), nullable=False),
        sa.Column("paper_average_price", sa.Numeric(28, 10), nullable=True),
        sa.Column("shadow_average_price", sa.Numeric(28, 10), nullable=True),
        sa.Column("paper_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("shadow_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.ForeignKeyConstraint(["trade_id"], ["forward_trade_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="forward_execution_study_key_unique"),
    )
    for column in ("study_id", "trade_id", "observed_at"):
        op.create_index(f"ix_forward_execution_records_{column}", "forward_execution_records", [column])

    op.create_table(
        "forward_forecast_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("external_key", sa.String(160), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Numeric(12, 10), nullable=False),
        sa.Column("outcome", sa.Integer(), nullable=False),
        sa.Column("market_probability", sa.Numeric(12, 10), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="forward_forecast_study_key_unique"),
    )
    op.create_index("ix_forward_forecast_records_study_id", "forward_forecast_records", ["study_id"])
    op.create_index("ix_forward_forecast_records_resolved_at", "forward_forecast_records", ["resolved_at"])

    op.create_table(
        "forward_study_incidents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("external_key", sa.String(160), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_integrity", sa.Boolean(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="forward_incident_study_key_unique"),
    )
    for column in ("study_id", "severity", "code", "resolved", "opened_at"):
        op.create_index(f"ix_forward_study_incidents_{column}", "forward_study_incidents", [column])


def downgrade() -> None:
    for column in ("opened_at", "resolved", "code", "severity", "study_id"):
        op.drop_index(f"ix_forward_study_incidents_{column}", table_name="forward_study_incidents")
    op.drop_table("forward_study_incidents")
    for column in ("resolved_at", "study_id"):
        op.drop_index(f"ix_forward_forecast_records_{column}", table_name="forward_forecast_records")
    op.drop_table("forward_forecast_records")
    for column in ("observed_at", "trade_id", "study_id"):
        op.drop_index(f"ix_forward_execution_records_{column}", table_name="forward_execution_records")
    op.drop_table("forward_execution_records")
    for column in ("closed_at", "opened_at", "study_id"):
        op.drop_index(f"ix_forward_trade_records_{column}", table_name="forward_trade_records")
    op.drop_table("forward_trade_records")
    op.drop_index("ix_forward_nav_observations_observed_at", table_name="forward_nav_observations")
    op.drop_index("ix_forward_nav_observations_study_id", table_name="forward_nav_observations")
    op.drop_table("forward_nav_observations")
    for column in ("started_at", "status", "instrument", "venue", "family", "experiment_id", "strategy_version_id"):
        op.drop_index(f"ix_forward_studies_{column}", table_name="forward_studies")
    op.drop_index("ix_forward_studies_external_id", table_name="forward_studies")
    op.drop_table("forward_studies")
