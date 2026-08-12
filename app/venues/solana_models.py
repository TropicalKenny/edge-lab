from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, uid, utcnow


class SolanaLaunchEvent(Base):
    __tablename__ = "solana_launch_events"
    __table_args__ = (UniqueConstraint("signature", "mint", name="solana_launch_signature_mint_unique"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    signature: Mapped[str] = mapped_column(String(100), index=True)
    slot: Mapped[int] = mapped_column(Integer, index=True)
    creator: Mapped[str] = mapped_column(String(64), index=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    program_id: Mapped[str] = mapped_column(String(64))
    logs_json: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SolanaDexSnapshot(Base):
    __tablename__ = "solana_dex_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    pair_address: Mapped[str] = mapped_column(String(64), index=True)
    dex_id: Mapped[str] = mapped_column(String(64))
    quote_symbol: Mapped[str] = mapped_column(String(32))
    price_usd: Mapped[Decimal] = mapped_column(Numeric(28, 12))
    liquidity_usd: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    market_cap: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    volume_5m: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    volume_1h: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    buys_5m: Mapped[int] = mapped_column(Integer)
    sells_5m: Mapped[int] = mapped_column(Integer)
    buys_1h: Mapped[int] = mapped_column(Integer)
    sells_1h: Mapped[int] = mapped_column(Integer)
    price_change_5m: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price_change_1h: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price_change_6h: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price_change_24h: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    pair_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SolanaSecuritySnapshot(Base):
    __tablename__ = "solana_security_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    mintable: Mapped[bool | None] = mapped_column(Boolean)
    freezable: Mapped[bool | None] = mapped_column(Boolean)
    non_transferable: Mapped[bool | None] = mapped_column(Boolean)
    metadata_mutable: Mapped[bool | None] = mapped_column(Boolean)
    malicious_creator: Mapped[bool | None] = mapped_column(Boolean)
    top10_holder_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    transfer_fee_bps: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    trusted_token: Mapped[bool | None] = mapped_column(Boolean)
    raw_json: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SolanaShadowQuoteSnapshot(Base):
    __tablename__ = "solana_shadow_quotes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    input_mint: Mapped[str] = mapped_column(String(64))
    output_mint: Mapped[str] = mapped_column(String(64))
    in_amount: Mapped[int] = mapped_column(Numeric(38, 0))
    out_amount: Mapped[int] = mapped_column(Numeric(38, 0))
    in_usd_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    out_usd_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    fee_bps: Mapped[int | None] = mapped_column(Integer)
    fee_mint: Mapped[str | None] = mapped_column(String(64))
    platform_fee_amount: Mapped[int | None] = mapped_column(Numeric(38, 0))
    signature_fee_lamports: Mapped[int | None] = mapped_column(Integer)
    prioritization_fee_lamports: Mapped[int | None] = mapped_column(Integer)
    router: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(100))
    quote_time_ms: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SolanaForensicFeatureSnapshot(Base):
    __tablename__ = "solana_forensic_feature_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    creator: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), default="pump_onchain")
    age_minutes: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    sell_ratio_5m: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    volume_acceleration: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    liquidity_to_mcap: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    price_change_5m: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    price_change_1h: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    mintable: Mapped[bool | None] = mapped_column(Boolean)
    freezable: Mapped[bool | None] = mapped_column(Boolean)
    malicious_creator: Mapped[bool | None] = mapped_column(Boolean)
    top10_holder_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    transfer_fee_bps: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    exit_quote_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 10))
    exit_price_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    missing_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SolanaForwardLabel(Base):
    __tablename__ = "solana_forward_labels"
    __table_args__ = (UniqueConstraint("mint", "horizon_minutes", "launch_signature", name="solana_label_mint_horizon_launch_unique"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    launch_signature: Mapped[str] = mapped_column(String(100), index=True)
    horizon_minutes: Mapped[int] = mapped_column(Integer, index=True)
    entry_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    future_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 12))
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    max_observed_liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    exit_quote_available: Mapped[bool | None] = mapped_column(Boolean)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
