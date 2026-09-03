"""add M6I owner research controls

Revision ID: l2d59a86c177
Revises: k1c48f75b066
Create Date: 2026-09-03 08:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l2d59a86c177"
down_revision: str | Sequence[str] | None = "k1c48f75b066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "study_control_settings",
        sa.Column("study_id", sa.String(36), nullable=False),
        sa.Column("lifecycle_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(160), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("study_id"),
    )
    op.create_table(
        "incident_control_states",
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("acknowledged_by", sa.String(160), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["forward_study_incidents.id"]),
        sa.PrimaryKeyConstraint("incident_id"),
    )
    op.create_table(
        "owner_commands",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("command", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(160), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_owner_commands_idempotency_key", "owner_commands", ["idempotency_key"])
    op.create_index("ix_owner_commands_actor_type", "owner_commands", ["actor_type"])
    op.create_index("ix_owner_commands_actor_id", "owner_commands", ["actor_id"])
    op.create_index("ix_owner_commands_command", "owner_commands", ["command"])
    op.create_index("ix_owner_commands_target_type", "owner_commands", ["target_type"])
    op.create_index("ix_owner_commands_target_id", "owner_commands", ["target_id"])
    op.create_index("ix_owner_commands_status", "owner_commands", ["status"])
    op.create_table(
        "integration_cursors",
        sa.Column("integration", sa.String(80), nullable=False),
        sa.Column("cursor_value", sa.String(180), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("integration"),
    )


def downgrade() -> None:
    op.drop_table("integration_cursors")
    op.drop_index("ix_owner_commands_status", table_name="owner_commands")
    op.drop_index("ix_owner_commands_target_id", table_name="owner_commands")
    op.drop_index("ix_owner_commands_target_type", table_name="owner_commands")
    op.drop_index("ix_owner_commands_command", table_name="owner_commands")
    op.drop_index("ix_owner_commands_actor_id", table_name="owner_commands")
    op.drop_index("ix_owner_commands_actor_type", table_name="owner_commands")
    op.drop_index("ix_owner_commands_idempotency_key", table_name="owner_commands")
    op.drop_table("owner_commands")
    op.drop_table("incident_control_states")
    op.drop_table("study_control_settings")
