"""add M6H lifecycle performance accounting

Revision ID: k1c48f75b066
Revises: j0b37e64a955
Create Date: 2026-08-31 12:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k1c48f75b066"
down_revision: str | Sequence[str] | None = "j0b37e64a955"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type in (
        ("mark_input_amount_atomic", sa.BigInteger()),
        ("mark_output_amount_atomic", sa.BigInteger()),
        ("mark_input_value_usd", sa.Numeric(28, 10)),
        ("mark_output_value_usd", sa.Numeric(28, 10)),
        ("reentry_input_amount_atomic", sa.BigInteger()),
        ("reentry_output_amount_atomic", sa.BigInteger()),
        ("reentry_input_value_usd", sa.Numeric(28, 10)),
        ("reentry_output_value_usd", sa.Numeric(28, 10)),
    ):
        op.add_column(
            "lifecycle_observations",
            sa.Column(name, column_type, nullable=True),
        )

    op.create_table(
        "lifecycle_performance_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("policy_name", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("accounting_version", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_after", sa.String(16), nullable=False),
        sa.Column("starting_value_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("token_units", sa.Numeric(38, 18), nullable=False),
        sa.Column("cash_balance_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("gross_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("net_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("hold_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("net_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("hold_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("excess_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("transaction_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("cumulative_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("cost_drag_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("round_trip_count", sa.Integer(), nullable=False),
        sa.Column("time_invested_seconds", sa.Integer(), nullable=False),
        sa.Column("time_in_cash_seconds", sa.Integer(), nullable=False),
        sa.Column("max_favorable_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("max_adverse_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("hold_max_favorable_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("hold_max_adverse_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("mfe_capture_ratio", sa.Numeric(20, 10), nullable=True),
        sa.Column("downside_avoided_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("downside_incurred_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("cycle_index", sa.Integer(), nullable=False),
        sa.Column("cycle_entry_decision_id", sa.String(36), nullable=True),
        sa.Column("cycle_entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cycle_entry_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("cycle_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("cycle_mfe_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("cycle_mae_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("cycle_invested_seconds", sa.Integer(), nullable=False),
        sa.Column("failed_reentry_count", sa.Integer(), nullable=False),
        sa.Column("missed_recovery_count", sa.Integer(), nullable=False),
        sa.Column("cash_reference_hold_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("cash_max_hold_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("cash_interval_missed_recovery", sa.Boolean(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observation_id"], ["lifecycle_observations.id"]),
        sa.ForeignKeyConstraint(["decision_id"], ["lifecycle_policy_decisions.id"]),
        sa.ForeignKeyConstraint(["cycle_entry_decision_id"], ["lifecycle_policy_decisions.id"]),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            "policy_name",
            "policy_version",
            "accounting_version",
            name="lifecycle_performance_snapshot_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_performance_snapshots_observation_id", ["observation_id"]),
        ("ix_lifecycle_performance_snapshots_decision_id", ["decision_id"]),
        ("ix_lifecycle_performance_snapshots_study_id", ["study_id"]),
        ("ix_lifecycle_performance_snapshots_position_key", ["position_key"]),
        ("ix_lifecycle_performance_snapshots_policy_name", ["policy_name"]),
        (
            "ix_lifecycle_performance_snapshots_accounting_version",
            ["accounting_version"],
        ),
        ("ix_lifecycle_performance_snapshots_observed_at", ["observed_at"]),
        ("ix_lifecycle_performance_snapshots_state_after", ["state_after"]),
        (
            "ix_lifecycle_performance_snapshots_cycle_entry_decision_id",
            ["cycle_entry_decision_id"],
        ),
        ("ix_lifecycle_performance_snapshots_complete", ["complete"]),
    ):
        op.create_index(name, "lifecycle_performance_snapshots", columns)

    op.create_table(
        "lifecycle_policy_cycles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("policy_name", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("accounting_version", sa.String(40), nullable=False),
        sa.Column("cycle_index", sa.Integer(), nullable=False),
        sa.Column("entry_decision_id", sa.String(36), nullable=True),
        sa.Column("exit_decision_id", sa.String(36), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entered_via", sa.String(16), nullable=False),
        sa.Column("exited_via", sa.String(24), nullable=False),
        sa.Column("entry_value_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("exit_value_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("net_pnl_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("net_return_pct", sa.Numeric(20, 10), nullable=False),
        sa.Column("modeled_cost_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("max_favorable_return_pct", sa.Numeric(20, 10), nullable=False),
        sa.Column("max_adverse_return_pct", sa.Numeric(20, 10), nullable=False),
        sa.Column("invested_seconds", sa.Integer(), nullable=False),
        sa.Column("failed_reentry", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.ForeignKeyConstraint(["entry_decision_id"], ["lifecycle_policy_decisions.id"]),
        sa.ForeignKeyConstraint(["exit_decision_id"], ["lifecycle_policy_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id",
            "position_key",
            "policy_name",
            "policy_version",
            "accounting_version",
            "cycle_index",
            name="lifecycle_policy_cycle_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_policy_cycles_study_id", ["study_id"]),
        ("ix_lifecycle_policy_cycles_position_key", ["position_key"]),
        ("ix_lifecycle_policy_cycles_policy_name", ["policy_name"]),
        ("ix_lifecycle_policy_cycles_accounting_version", ["accounting_version"]),
        ("ix_lifecycle_policy_cycles_entry_decision_id", ["entry_decision_id"]),
        ("ix_lifecycle_policy_cycles_exit_decision_id", ["exit_decision_id"]),
        ("ix_lifecycle_policy_cycles_entered_at", ["entered_at"]),
        ("ix_lifecycle_policy_cycles_exited_at", ["exited_at"]),
        ("ix_lifecycle_policy_cycles_exited_via", ["exited_via"]),
        ("ix_lifecycle_policy_cycles_failed_reentry", ["failed_reentry"]),
    ):
        op.create_index(name, "lifecycle_policy_cycles", columns)


def downgrade() -> None:
    for name in (
        "ix_lifecycle_policy_cycles_failed_reentry",
        "ix_lifecycle_policy_cycles_exited_via",
        "ix_lifecycle_policy_cycles_exited_at",
        "ix_lifecycle_policy_cycles_entered_at",
        "ix_lifecycle_policy_cycles_exit_decision_id",
        "ix_lifecycle_policy_cycles_entry_decision_id",
        "ix_lifecycle_policy_cycles_accounting_version",
        "ix_lifecycle_policy_cycles_policy_name",
        "ix_lifecycle_policy_cycles_position_key",
        "ix_lifecycle_policy_cycles_study_id",
    ):
        op.drop_index(name, table_name="lifecycle_policy_cycles")
    op.drop_table("lifecycle_policy_cycles")

    for name in (
        "ix_lifecycle_performance_snapshots_complete",
        "ix_lifecycle_performance_snapshots_cycle_entry_decision_id",
        "ix_lifecycle_performance_snapshots_state_after",
        "ix_lifecycle_performance_snapshots_observed_at",
        "ix_lifecycle_performance_snapshots_accounting_version",
        "ix_lifecycle_performance_snapshots_policy_name",
        "ix_lifecycle_performance_snapshots_position_key",
        "ix_lifecycle_performance_snapshots_study_id",
        "ix_lifecycle_performance_snapshots_decision_id",
        "ix_lifecycle_performance_snapshots_observation_id",
    ):
        op.drop_index(name, table_name="lifecycle_performance_snapshots")
    op.drop_table("lifecycle_performance_snapshots")

    for name in (
        "reentry_output_value_usd",
        "reentry_input_value_usd",
        "reentry_output_amount_atomic",
        "reentry_input_amount_atomic",
        "mark_output_value_usd",
        "mark_input_value_usd",
        "mark_output_amount_atomic",
        "mark_input_amount_atomic",
    ):
        op.drop_column("lifecycle_observations", name)
