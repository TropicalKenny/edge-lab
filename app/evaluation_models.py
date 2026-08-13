from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class StrategyEvaluationRun(Base):
    __tablename__ = "strategy_evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    external_run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    strategy_slug: Mapped[str] = mapped_column(String(100), index=True)
    strategy_version: Mapped[str] = mapped_column(String(64), index=True)
    family: Mapped[str] = mapped_column(String(32), index=True)
    recommendation: Mapped[str] = mapped_column(String(32), index=True)
    forward_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    forward_days: Mapped[int] = mapped_column(Integer)
    trade_count: Mapped[int] = mapped_column(Integer)
    forecast_count: Mapped[int] = mapped_column(Integer)
    execution_observation_count: Mapped[int] = mapped_column(Integer)
    net_pnl_usd: Mapped[float] = mapped_column(Numeric(28, 10))
    stressed_net_pnl_usd: Mapped[float] = mapped_column(Numeric(28, 10))
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(18, 10))
    profit_factor: Mapped[float | None] = mapped_column(Numeric(18, 10))
    brier_score: Mapped[float | None] = mapped_column(Numeric(18, 10))
    calibration_error: Mapped[float | None] = mapped_column(Numeric(18, 10))
    policy_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    reasons_json: Mapped[str] = mapped_column(Text)
    input_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
