from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class PortfolioAllocationRun(Base):
    __tablename__ = "portfolio_allocation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    external_run_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16))
    nav_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    authorized_working_capital_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    vault_usd_untouched: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    reserve_floor_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    allocated_notional_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    planned_risk_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    input_json: Mapped[str] = mapped_column(Text)
    policy_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PortfolioAllocationDecision(Base):
    __tablename__ = "portfolio_allocation_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    candidate_id: Mapped[str] = mapped_column(String(100), index=True)
    strategy: Mapped[str] = mapped_column(String(100), index=True)
    strategy_version: Mapped[str] = mapped_column(String(100))
    venue: Mapped[str] = mapped_column(String(64), index=True)
    instrument: Mapped[str] = mapped_column(String(120))
    correlation_bucket: Mapped[str] = mapped_column(String(100), index=True)
    evidence_status: Mapped[str] = mapped_column(String(16))
    requested_notional_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    approved_notional_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    planned_loss_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    score: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    approved: Mapped[bool] = mapped_column(Boolean)
    reasons_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TreasuryRebalanceProposal(Base):
    __tablename__ = "treasury_rebalance_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(100))
    destination: Mapped[str] = mapped_column(String(100), index=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    reason: Mapped[str] = mapped_column(Text)
    proposal_only: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_owner_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    executable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
