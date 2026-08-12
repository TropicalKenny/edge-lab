from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class PolymarketEventSnapshot(Base):
    __tablename__ = "polymarket_event_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(255))
    neg_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    neg_risk_augmented: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_source: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PolymarketMarketSnapshot(Base):
    __tablename__ = "polymarket_market_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    market_id: Mapped[str] = mapped_column(String(80), index=True)
    condition_id: Mapped[str] = mapped_column(String(100), index=True)
    event_id: Mapped[str | None] = mapped_column(String(80), index=True)
    question: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(255))
    yes_token_id: Mapped[str | None] = mapped_column(String(100))
    no_token_id: Mapped[str | None] = mapped_column(String(100))
    accepting_orders: Mapped[bool] = mapped_column(Boolean, default=False)
    neg_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    neg_risk_other: Mapped[bool] = mapped_column(Boolean, default=False)
    fees_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    fee_exponent: Mapped[int | None]
    resolution_source: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PolymarketBookSnapshot(Base):
    __tablename__ = "polymarket_book_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    condition_id: Mapped[str] = mapped_column(String(100), index=True)
    token_id: Mapped[str] = mapped_column(String(100), index=True)
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    bid_depth_shares: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    ask_depth_shares: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    min_order_size: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    tick_size: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    neg_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    book_hash: Mapped[str | None] = mapped_column(String(255))
    bids_json: Mapped[str] = mapped_column(Text)
    asks_json: Mapped[str] = mapped_column(Text)
    book_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PolymarketStructuralOpportunitySnapshot(Base):
    __tablename__ = "polymarket_structural_opportunities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str | None] = mapped_column(String(80), index=True)
    condition_id: Mapped[str | None] = mapped_column(String(100), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    gross_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    total_fees: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    payout: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    net_profit: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    roi_bps: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    legs_json: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
