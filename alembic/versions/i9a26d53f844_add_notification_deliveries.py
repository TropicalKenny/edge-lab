"""add notification deliveries

Revision ID: i9a26d53f844
Revises: h8f15c42e733
Create Date: 2026-08-13 08:06:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "i9a26d53f844"
down_revision: Union[str, Sequence[str], None] = "h8f15c42e733"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("event_key", sa.String(180), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "event_key", name="notification_channel_event_unique"),
    )
    op.create_index("ix_notification_deliveries_channel", "notification_deliveries", ["channel"])
    op.create_index("ix_notification_deliveries_event_type", "notification_deliveries", ["event_type"])
    op.create_index("ix_notification_deliveries_severity", "notification_deliveries", ["severity"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index("ix_notification_deliveries_next_attempt_at", "notification_deliveries", ["next_attempt_at"])
    op.create_index("ix_notification_deliveries_sent_at", "notification_deliveries", ["sent_at"])
    op.create_index("ix_notification_deliveries_created_at", "notification_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_created_at", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_sent_at", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_next_attempt_at", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_status", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_severity", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_event_type", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_channel", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
