from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class HyperliquidPerpSnapshot(Base):
    __tablename__ = 'hyperliquid_perp_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    coin: Mapped[str] = mapped_column(String(80), index=True)
    mark_px: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    mid_px: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    oracle_px: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    funding_rate_hourly: Mapped[Decimal] = mapped_column(Numeric(20, 12))
    premium: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    open_interest: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    day_ntl_volume: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class HyperliquidSpotSnapshot(Base):
    __tablename__ = 'hyperliquid_spot_snapshots'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    pair: Mapped[str] = mapped_column(String(120), index=True)
    book_coin: Mapped[str] = mapped_column(String(80))
    base: Mapped[str] = mapped_column(String(80))
    quote: Mapped[str] = mapped_column(String(80))
    mid_px: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    day_ntl_volume: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class HyperliquidFundingSnapshot(Base):
    __tablename__ = 'hyperliquid_funding_snapshots'
    __table_args__ = (UniqueConstraint('coin', 'funding_time', name='hyperliquid_funding_coin_time_unique'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    coin: Mapped[str] = mapped_column(String(80), index=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(20, 12))
    premium: Mapped[Decimal | None] = mapped_column(Numeric(20, 12))
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
