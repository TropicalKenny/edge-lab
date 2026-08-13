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
    trade_record_id: Mapped[str | None] = mapped_column(ForeignKey("forward_trade_records.id"), index=True)
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

    # Reference marks are kept separate from executable paper fills so slippage
    # can be measured once and never double-counted inside price PnL.
    entry_spot_mid: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_mid: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_spot_price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_price: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_spot_fee_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_fee_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_spot_slippage_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))
    entry_perp_slippage_usd: Mapped[Decimal] = mapped_column(Numeric(28, 10))

    # Delayed book observations are shadow evidence only. They never replace the
    # paper entry; they measure whether the paper model was actually executable.
    entry_shadow_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_shadow_spot_filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    entry_shadow_perp_filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    entry_shadow_spot_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    entry_shadow_perp_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    entry_shadow_spot_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    entry_shadow_perp_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))

    exit_spot_mid: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_perp_mid: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_spot_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_perp_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_spot_fee_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_perp_fee_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_spot_slippage_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_perp_slippage_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))

    exit_shadow_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_shadow_spot_filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_shadow_perp_filled_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_shadow_spot_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_shadow_perp_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_shadow_spot_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_shadow_perp_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))

    funding_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    gross_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    fees_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    slippage_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    net_pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    close_reason: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
