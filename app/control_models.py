from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class StudyControlSetting(Base):
    __tablename__ = "study_control_settings"

    study_id: Mapped[str] = mapped_column(
        ForeignKey("forward_studies.id"), primary_key=True
    )
    lifecycle_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(160), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IncidentControlState(Base):
    __tablename__ = "incident_control_states"

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("forward_study_incidents.id"), primary_key=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(160))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OwnerCommand(Base):
    __tablename__ = "owner_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(160), index=True)
    command: Mapped[str] = mapped_column(String(40), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str | None] = mapped_column(String(160), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), index=True)
    outcome_json: Mapped[str] = mapped_column(Text, default="{}")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationCursor(Base):
    __tablename__ = "integration_cursors"

    integration: Mapped[str] = mapped_column(String(80), primary_key=True)
    cursor_value: Mapped[str] = mapped_column(String(180))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
