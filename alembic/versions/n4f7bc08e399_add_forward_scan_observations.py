"""add forward scan observations

Revision ID: n4f7bc08e399
Revises: m3e6ab97d288
Create Date: 2026-09-03 12:55:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n4f7bc08e399"
down_revision: str | Sequence[str] | None = "m3e6ab97d288"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forward_scan_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("study_id", sa.String(length=36), nullable=False),
        sa.Column("external_key", sa.String(length=180), nullable=False),
        sa.Column("observation_kind", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("examined_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deferred_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejection_reasons_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["study_id"], ["forward_studies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "external_key", name="forward_scan_study_key_unique"),
    )
    op.create_index("ix_forward_scan_observations_study_id", "forward_scan_observations", ["study_id"], unique=False)
    op.create_index("ix_forward_scan_observations_observation_kind", "forward_scan_observations", ["observation_kind"], unique=False)
    op.create_index("ix_forward_scan_observations_observed_at", "forward_scan_observations", ["observed_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_forward_scan_observations_observed_at", table_name="forward_scan_observations")
    op.drop_index("ix_forward_scan_observations_observation_kind", table_name="forward_scan_observations")
    op.drop_index("ix_forward_scan_observations_study_id", table_name="forward_scan_observations")
    op.drop_table("forward_scan_observations")
