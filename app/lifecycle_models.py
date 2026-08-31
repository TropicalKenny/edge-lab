from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    mark_input_amount_atomic: Mapped[int | None] = mapped_column(BigInteger)
    mark_output_amount_atomic: Mapped[int | None] = mapped_column(BigInteger)
    mark_input_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    mark_output_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    reentry_quote_available: Mapped[bool] = mapped_column(Boolean, default=False)
    reentry_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    reentry_input_amount_atomic: Mapped[int | None] = mapped_column(BigInteger)
    reentry_output_amount_atomic: Mapped[int | None] = mapped_column(BigInteger)
    reentry_input_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    reentry_output_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
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


class LifecyclePerformanceSnapshot(Base):
    __tablename__ = "lifecycle_performance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "policy_name",
            "policy_version",
            "accounting_version",
            name="lifecycle_performance_snapshot_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_observations.id"), index=True
    )
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_policy_decisions.id"), index=True
    )
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    position_key: Mapped[str] = mapped_column(String(160), index=True)
    policy_name: Mapped[str] = mapped_column(String(80), index=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    accounting_version: Mapped[str] = mapped_column(String(40), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state_after: Mapped[str] = mapped_column(String(16), index=True)
    starting_value_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    token_units: Mapped[Decimal] = mapped_column(Numeric(38, 18), default=0)
    cash_balance_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    gross_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    net_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    hold_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    net_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    hold_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    excess_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    transaction_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    cumulative_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    cost_drag_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    round_trip_count: Mapped[int] = mapped_column(Integer, default=0)
    time_invested_seconds: Mapped[int] = mapped_column(Integer, default=0)
    time_in_cash_seconds: Mapped[int] = mapped_column(Integer, default=0)
    max_favorable_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    max_adverse_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    hold_max_favorable_return_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10)
    )
    hold_max_adverse_return_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10)
    )
    mfe_capture_ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    downside_avoided_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    downside_incurred_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    cycle_index: Mapped[int] = mapped_column(Integer, default=0)
    cycle_entry_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("lifecycle_policy_decisions.id"), index=True
    )
    cycle_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cycle_entry_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    cycle_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    cycle_mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    cycle_mae_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    cycle_invested_seconds: Mapped[int] = mapped_column(Integer, default=0)
    failed_reentry_count: Mapped[int] = mapped_column(Integer, default=0)
    missed_recovery_count: Mapped[int] = mapped_column(Integer, default=0)
    cash_reference_hold_value_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 10)
    )
    cash_max_hold_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    cash_interval_missed_recovery: Mapped[bool] = mapped_column(Boolean, default=False)
    complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LifecyclePolicyCycle(Base):
    __tablename__ = "lifecycle_policy_cycles"
    __table_args__ = (
        UniqueConstraint(
            "study_id",
            "position_key",
            "policy_name",
            "policy_version",
            "accounting_version",
            "cycle_index",
            name="lifecycle_policy_cycle_unique",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    position_key: Mapped[str] = mapped_column(String(160), index=True)
    policy_name: Mapped[str] = mapped_column(String(80), index=True)
    policy_version: Mapped[str] = mapped_column(String(32))
    accounting_version: Mapped[str] = mapped_column(String(40), index=True)
    cycle_index: Mapped[int] = mapped_column(Integer)
    entry_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("lifecycle_policy_decisions.id"), index=True
    )
    exit_decision_id: Mapped[str] = mapped_column(
        ForeignKey("lifecycle_policy_decisions.id"), index=True
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entered_via: Mapped[str] = mapped_column(String(16))
    exited_via: Mapped[str] = mapped_column(String(24), index=True)
    entry_value_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    exit_value_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    net_pnl_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    net_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    modeled_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    max_favorable_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    max_adverse_return_pct: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    invested_seconds: Mapped[int] = mapped_column(Integer)
    failed_reentry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
