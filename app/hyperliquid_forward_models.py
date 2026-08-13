from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class HyperliquidCarryPosition(Base):
    __tablename__ = "hyperliquid_carry_positions"
    __table_args__ = (
        UniqueConstraint("study_id", "external_key", name="hl_carry_study_key_unique"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    study_id: Mapped[str] = mapped_column(ForeignKey("forward_studies.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    coin: Mapped[str] = mapped_column(String(32), index=True)
    spot_book_coin: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    allocated_capital_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    planned_loss_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    target_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entry_spot_price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_spot_fee_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_fee_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_spot_slippage_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_slippage_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))

    exit_spot_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_perp_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    funding_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    gross_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    fees_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    slippage_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    net_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    close_reason: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
