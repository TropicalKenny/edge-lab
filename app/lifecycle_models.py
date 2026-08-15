from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class LifecycleObservation(Base):
    __tablename__ = "lifecycle_observations"
    __table_args__ = (
        UniqueConstraint(
            "study_id",
            "position_key",
            "observed_at",
            name="lifecycle_observation_study_position_time_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    position_key: Mapped[str] = mapped_column(String(160), index=True)
    asset_id: Mapped[str] = mapped_column(String(100), index=True)
    venue: Mapped[str] = mapped_column(String(32), index=True)
    baseline_state: Mapped[str] = mapped_column(String(16), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    baseline_entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    baseline_entry_value_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    baseline_exit_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    current_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    mark_quote_available: Mapped[bool] = mapped_column(Boolean, default=False)
    mark_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    reentry_quote_available: Mapped[bool] = mapped_column(Boolean, default=False)
    reentry_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    baseline_entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    sell_ratio_5m: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    volume_acceleration: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    security_clean: Mapped[bool | None] = mapped_column(Boolean)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LifecyclePolicyState(Base):
    __tablename__ = "lifecycle_policy_states"
    __table_args__ = (
        UniqueConstraint(
            "study_id",
            "position_key",
            "policy_name",
            "policy_version",
            name="lifecycle_policy_state_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    position_key: Mapped[str] = mapped_column(String(160), index=True)
    policy_name: Mapped[str] = mapped_column(String(80), index=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), index=True)
    virtual_entry_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    virtual_exit_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    virtual_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    virtual_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peak_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 10), default=0)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    last_action: Mapped[str] = mapped_column(String(24), default="ENTER")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LifecyclePolicyDecision(Base):
    __tablename__ = "lifecycle_policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "policy_name",
            "policy_version",
            name="lifecycle_policy_decision_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_observations.id"), index=True
    )
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    position_key: Mapped[str] = mapped_column(String(160), index=True)
    policy_name: Mapped[str] = mapped_column(String(80), index=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    state_before: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(24), index=True)
    state_after: Mapped[str] = mapped_column(String(16), index=True)
    rationale_json: Mapped[str] = mapped_column(Text, default="{}")
    can_execute: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LifecycleDecisionOutcome(Base):
    __tablename__ = "lifecycle_decision_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "horizon_minutes",
            name="lifecycle_decision_outcome_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_policy_decisions.id"), index=True
    )
    horizon_minutes: Mapped[int] = mapped_column(Integer, index=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    future_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    future_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    max_favorable_move_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    max_adverse_move_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
