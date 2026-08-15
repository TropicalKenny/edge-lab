"""add M6H lifecycle research journal

Revision ID: j0b37e64a955
Revises: i9a26d53f844
Create Date: 2026-08-15 12:55:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "j0b37e64a955"
down_revision: Union[str, Sequence[str], None] = "i9a26d53f844"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("asset_id", sa.String(100), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("baseline_state", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("baseline_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baseline_entry_value_usd", sa.Numeric(28, 10), nullable=False),
        sa.Column("baseline_exit_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("current_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("mark_quote_available", sa.Boolean(), nullable=False),
        sa.Column("mark_price_impact_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("reentry_quote_available", sa.Boolean(), nullable=False),
        sa.Column("reentry_price_impact_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("liquidity_usd", sa.Numeric(28, 8), nullable=True),
        sa.Column("baseline_entry_liquidity_usd", sa.Numeric(28, 8), nullable=True),
        sa.Column("momentum_score", sa.Numeric(20, 10), nullable=True),
        sa.Column("sell_ratio_5m", sa.Numeric(20, 10), nullable=True),
        sa.Column("volume_acceleration", sa.Numeric(20, 10), nullable=True),
        sa.Column("security_clean", sa.Boolean(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id",
            "position_key",
            "observed_at",
            name="lifecycle_observation_study_position_time_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_observations_study_id", ["study_id"]),
        ("ix_lifecycle_observations_position_key", ["position_key"]),
        ("ix_lifecycle_observations_asset_id", ["asset_id"]),
        ("ix_lifecycle_observations_venue", ["venue"]),
        ("ix_lifecycle_observations_baseline_state", ["baseline_state"]),
        ("ix_lifecycle_observations_observed_at", ["observed_at"]),
    ):
        op.create_index(name, "lifecycle_observations", columns)

    op.create_table(
        "lifecycle_policy_states",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("policy_name", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("virtual_entry_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("virtual_exit_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("virtual_entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("virtual_exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("peak_return_pct", sa.Numeric(20, 10), nullable=False),
        sa.Column("cycle_count", sa.Integer(), nullable=False),
        sa.Column("last_action", sa.String(24), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "study_id",
            "position_key",
            "policy_name",
            "policy_version",
            name="lifecycle_policy_state_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_policy_states_study_id", ["study_id"]),
        ("ix_lifecycle_policy_states_position_key", ["position_key"]),
        ("ix_lifecycle_policy_states_policy_name", ["policy_name"]),
        ("ix_lifecycle_policy_states_state", ["state"]),
    ):
        op.create_index(name, "lifecycle_policy_states", columns)

    op.create_table(
        "lifecycle_policy_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(160), nullable=False),
        sa.Column("policy_name", sa.String(80), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("state_before", sa.String(16), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("state_after", sa.String(16), nullable=False),
        sa.Column("rationale_json", sa.Text(), nullable=False),
        sa.Column("can_execute", sa.Boolean(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observation_id"], ["lifecycle_observations.id"]),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            "policy_name",
            "policy_version",
            name="lifecycle_policy_decision_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_policy_decisions_observation_id", ["observation_id"]),
        ("ix_lifecycle_policy_decisions_study_id", ["study_id"]),
        ("ix_lifecycle_policy_decisions_position_key", ["position_key"]),
        ("ix_lifecycle_policy_decisions_policy_name", ["policy_name"]),
        ("ix_lifecycle_policy_decisions_state_before", ["state_before"]),
        ("ix_lifecycle_policy_decisions_action", ["action"]),
        ("ix_lifecycle_policy_decisions_state_after", ["state_after"]),
        ("ix_lifecycle_policy_decisions_decided_at", ["decided_at"]),
    ):
        op.create_index(name, "lifecycle_policy_decisions", columns)

    op.create_table(
        "lifecycle_decision_outcomes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("horizon_minutes", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("future_value_usd", sa.Numeric(28, 10), nullable=True),
        sa.Column("future_return_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("max_favorable_move_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("max_adverse_move_pct", sa.Numeric(20, 10), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["lifecycle_policy_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "decision_id",
            "horizon_minutes",
            name="lifecycle_decision_outcome_unique",
        ),
    )
    for name, columns in (
        ("ix_lifecycle_decision_outcomes_decision_id", ["decision_id"]),
        ("ix_lifecycle_decision_outcomes_horizon_minutes", ["horizon_minutes"]),
        ("ix_lifecycle_decision_outcomes_resolved_at", ["resolved_at"]),
    ):
        op.create_index(name, "lifecycle_decision_outcomes", columns)


def downgrade() -> None:
    for name in (
        "ix_lifecycle_decision_outcomes_resolved_at",
        "ix_lifecycle_decision_outcomes_horizon_minutes",
        "ix_lifecycle_decision_outcomes_decision_id",
    ):
        op.drop_index(name, table_name="lifecycle_decision_outcomes")
    op.drop_table("lifecycle_decision_outcomes")

    for name in (
        "ix_lifecycle_policy_decisions_decided_at",
        "ix_lifecycle_policy_decisions_state_after",
        "ix_lifecycle_policy_decisions_action",
        "ix_lifecycle_policy_decisions_state_before",
        "ix_lifecycle_policy_decisions_policy_name",
        "ix_lifecycle_policy_decisions_position_key",
        "ix_lifecycle_policy_decisions_study_id",
        "ix_lifecycle_policy_decisions_observation_id",
    ):
        op.drop_index(name, table_name="lifecycle_policy_decisions")
    op.drop_table("lifecycle_policy_decisions")

    for name in (
        "ix_lifecycle_policy_states_state",
        "ix_lifecycle_policy_states_policy_name",
        "ix_lifecycle_policy_states_position_key",
        "ix_lifecycle_policy_states_study_id",
    ):
        op.drop_index(name, table_name="lifecycle_policy_states")
    op.drop_table("lifecycle_policy_states")

    for name in (
        "ix_lifecycle_observations_observed_at",
        "ix_lifecycle_observations_baseline_state",
        "ix_lifecycle_observations_venue",
        "ix_lifecycle_observations_asset_id",
        "ix_lifecycle_observations_position_key",
        "ix_lifecycle_observations_study_id",
    ):
        op.drop_index(name, table_name="lifecycle_observations")
    op.drop_table("lifecycle_observations")
