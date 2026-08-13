from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class ForwardStudy(Base):
    __tablename__ = "forward_studies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    strategy_version_id: Mapped[str] = mapped_column(ForeignKey("strategy_versions.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    family: Mapped[str] = mapped_column(String(32), index=True)
    venue: Mapped[str] = mapped_column(String(64), index=True)
    instrument: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    initial_capital_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    evaluation_policy_json: Mapped[str] = mapped_column(Text)
    study_config_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForwardNavObservation(Base):
    __tablename__ = "forward_nav_observations"
    __table_args__ = (UniqueConstraint("study_id", "observed_at", name="forward_nav_study_time_unique"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    nav_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    source: Mapped[str] = mapped_column(String(64), default="forward-runner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForwardTradeRecord(Base):
    __tablename__ = "forward_trade_records"
    __table_args__ = (UniqueConstraint("study_id", "external_key", name="forward_trade_study_key_unique"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(140))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    gross_pnl_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    net_pnl_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    fees_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    slippage_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    allocated_capital_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    planned_loss_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForwardExecutionRecord(Base):
    __tablename__ = "forward_execution_records"
    __table_args__ = (UniqueConstraint("study_id", "external_key", name="forward_execution_study_key_unique"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    trade_id: Mapped[str | None] = mapped_column(ForeignKey("forward_trade_records.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    side: Mapped[str] = mapped_column(String(8))
    intended_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    paper_filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    shadow_filled_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    paper_average_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    shadow_average_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    paper_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    shadow_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForwardForecastRecord(Base):
    __tablename__ = "forward_forecast_records"
    __table_args__ = (UniqueConstraint("study_id", "external_key", name="forward_forecast_study_key_unique"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    probability: Mapped[Decimal] = mapped_column(Numeric(12, 10))
    outcome: Mapped[int] = mapped_column(Integer)
    market_probability: Mapped[Decimal | None] = mapped_column(Numeric(12, 10))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForwardStudyIncident(Base):
    __tablename__ = "forward_study_incidents"
    __table_args__ = (UniqueConstraint("study_id", "external_key", name="forward_incident_study_key_unique"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    data_integrity: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
