from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import HealthRegistry
from app.venues.solana import (
    DexSnapshot,
    DexScreenerClient,
    GoPlusSolanaClient,
    JupiterShadowClient,
    JupiterShadowQuote,
    PumpLaunchEvent,
    SecuritySnapshot,
    USDC_MINT,
)
from app.venues.solana_asset import HeliusAssetClient, SolanaAssetMetadata
from app.venues.solana_models import (
    SolanaDexSnapshot,
    SolanaForensicFeatureSnapshot,
    SolanaForwardLabel,
    SolanaLaunchEvent,
    SolanaSecuritySnapshot,
    SolanaShadowQuoteSnapshot,
)

ZERO = Decimal("0")
HORIZONS_MINUTES = (5, 30, 60, 360, 1440)
LABEL_MAX_LATENESS_RATIO = Decimal("0.25")
LABEL_MIN_LATENESS_MINUTES = Decimal("1")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class SolanaResearchRepository:
    @staticmethod
    def save_launch(db: Session, event: PumpLaunchEvent) -> bool:
        existing = db.scalar(
            select(SolanaLaunchEvent.id).where(
                SolanaLaunchEvent.signature == event.signature,
                SolanaLaunchEvent.mint == event.mint,
            )
        )
        if existing:
            return False
        db.add(
            SolanaLaunchEvent(
                signature=event.signature,
                slot=event.slot,
                creator=event.creator,
                mint=event.mint,
                program_id=event.program_id,
                logs_json=json.dumps(list(event.log_messages), separators=(",", ":")),
                observed_at=event.observed_at,
            )
        )
        db.commit()
        return True

    @staticmethod
    def save_dex(db: Session, snapshot: DexSnapshot) -> None:
        db.add(SolanaDexSnapshot(**asdict(snapshot)))
        db.commit()

    @staticmethod
    def save_security(db: Session, snapshot: SecuritySnapshot) -> None:
        values = asdict(snapshot)
        values["raw_json"] = json.dumps(values.pop("raw"), separators=(",", ":"), default=str)
        db.add(SolanaSecuritySnapshot(**values))
        db.commit()

    @staticmethod
    def save_shadow_quote(db: Session, mint: str, direction: str, quote: JupiterShadowQuote) -> None:
        values = asdict(quote)
        values.pop("transaction_present", None)
        db.add(SolanaShadowQuoteSnapshot(mint=mint, direction=direction, **values))
        db.commit()


class ForensicFeatureBuilder:
    @staticmethod
    def build(
        *,
        mint: str,
        creator: str | None,
        launch_at: datetime | None,
        dex: DexSnapshot | None,
        security: SecuritySnapshot | None,
        asset: SolanaAssetMetadata | None,
        exit_quote: JupiterShadowQuote | None,
        exit_test_notional_usd: Decimal | None,
        now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)
        missing: list[str] = []
        if launch_at is None:
            missing.append("launch_at")
        if dex is None:
            missing.append("dex_snapshot")
        if security is None:
            missing.append("security_snapshot")
        if asset is None:
            missing.append("asset_metadata")
        if exit_test_notional_usd is not None and exit_quote is None:
            missing.append("exit_shadow_quote")

        age_minutes = Decimal(str((now - _aware(launch_at)).total_seconds() / 60)) if launch_at else None
        momentum = sell_ratio = volume_accel = liquidity_ratio = None
        if dex:
            total = dex.buys_5m + dex.sells_5m
            if total > 0:
                momentum = Decimal(dex.buys_5m - dex.sells_5m) / Decimal(total)
                sell_ratio = Decimal(dex.sells_5m) / Decimal(total)
            if dex.volume_1h > ZERO:
                expected_5m = dex.volume_1h / Decimal("12")
                volume_accel = dex.volume_5m / expected_5m if expected_5m > ZERO else None
            if dex.market_cap > ZERO:
                liquidity_ratio = dex.liquidity_usd / dex.market_cap

        mintable = security.mintable if security else None
        freezable = security.freezable if security else None
        if asset:
            if mintable is None:
                mintable = asset.mint_authority is not None
            if freezable is None:
                freezable = asset.freeze_authority is not None

        return {
            "mint": mint,
            "creator": creator,
            "source": "pump_onchain",
            "age_minutes": age_minutes,
            "liquidity_usd": dex.liquidity_usd if dex else None,
            "market_cap": dex.market_cap if dex else None,
            "momentum_score": momentum,
            "sell_ratio_5m": sell_ratio,
            "volume_acceleration": volume_accel,
            "liquidity_to_mcap": liquidity_ratio,
            "price_change_5m": dex.price_change_5m if dex else None,
            "price_change_1h": dex.price_change_1h if dex else None,
            "mintable": mintable,
            "freezable": freezable,
            "malicious_creator": security.malicious_creator if security else None,
            "top10_holder_pct": security.top10_holder_pct if security else None,
            "transfer_fee_rate": security.transfer_fee_rate if security else None,
            "exit_quote_usd": exit_quote.out_usd_value if exit_quote else None,
            "exit_price_impact_pct": exit_quote.price_impact_pct if exit_quote else None,
            "missing_fields_json": json.dumps(missing, separators=(",", ":")),
            "captured_at": now,
        }


class SolanaForensicService:
    """Read-only enrichment and shadow-execution research for on-chain-discovered Solana mints."""

    def __init__(
        self,
        *,
        dexscreener: DexScreenerClient,
        goplus: GoPlusSolanaClient,
        helius_assets: HeliusAssetClient | None,
        jupiter: JupiterShadowClient | None,
        health: HealthRegistry,
        quote_mint: str = USDC_MINT,
    ) -> None:
        self.dexscreener = dexscreener
        self.goplus = goplus
        self.helius_assets = helius_assets
        self.jupiter = jupiter
        self.health = health
        self.quote_mint = quote_mint

    @staticmethod
    def _latest_launch(db: Session, mint: str) -> SolanaLaunchEvent | None:
        return db.scalar(
            select(SolanaLaunchEvent)
            .where(SolanaLaunchEvent.mint == mint)
            .order_by(SolanaLaunchEvent.observed_at.desc())
            .limit(1)
        )

    async def analyze_mint(
        self,
        db: Session,
        *,
        mint: str,
        exit_test_notional_usd: Decimal = Decimal("25"),
    ) -> SolanaForensicFeatureSnapshot:
        launch = self._latest_launch(db, mint)
        dex = security = asset = exit_quote = None
        errors: list[str] = []
        try:
            dex = await self.dexscreener.token(mint)
            if dex:
                SolanaResearchRepository.save_dex(db, dex)
        except Exception as exc:
            errors.append(f"dex:{type(exc).__name__}")
            db.rollback()

        try:
            security = await self.goplus.token_security(mint)
            if security:
                SolanaResearchRepository.save_security(db, security)
        except Exception as exc:
            errors.append(f"security:{type(exc).__name__}")
            db.rollback()

        if self.helius_assets is not None:
            try:
                asset = await self.helius_assets.get_asset(mint)
            except Exception as exc:
                errors.append(f"asset:{type(exc).__name__}")

        if self.jupiter is not None and dex and asset and dex.price_usd > ZERO and exit_test_notional_usd > ZERO:
            try:
                token_qty = exit_test_notional_usd / dex.price_usd
                atomic = int((token_qty * (Decimal(10) ** asset.decimals)).to_integral_value(rounding=ROUND_DOWN))
                if atomic > 0:
                    exit_quote = await self.jupiter.order_quote(input_mint=mint, output_mint=self.quote_mint, amount=atomic)
                    SolanaResearchRepository.save_shadow_quote(db, mint, "sell", exit_quote)
            except Exception as exc:
                errors.append(f"jupiter:{type(exc).__name__}")
                db.rollback()

        values = ForensicFeatureBuilder.build(
            mint=mint,
            creator=launch.creator if launch else None,
            launch_at=launch.observed_at if launch else None,
            dex=dex,
            security=security,
            asset=asset,
            exit_quote=exit_quote,
            exit_test_notional_usd=exit_test_notional_usd,
        )
        missing = json.loads(values["missing_fields_json"])
        missing.extend(errors)
        values["missing_fields_json"] = json.dumps(sorted(set(missing)), separators=(",", ":"))
        feature = SolanaForensicFeatureSnapshot(**values)
        db.add(feature)
        db.commit()
        db.refresh(feature)
        self.health.set("solana_forensics", True, f"feature snapshot for {mint}; missing={len(missing)}")
        return feature


class ForwardLabelService:
    """Build forward labels only when a snapshot is close enough to the requested horizon."""

    @staticmethod
    def _max_lateness_minutes(horizon: int) -> Decimal:
        return max(LABEL_MIN_LATENESS_MINUTES, Decimal(horizon) * LABEL_MAX_LATENESS_RATIO)

    @staticmethod
    def resolve(db: Session, *, mint: str, horizons: tuple[int, ...] = HORIZONS_MINUTES) -> int:
        launch = db.scalar(
            select(SolanaLaunchEvent)
            .where(SolanaLaunchEvent.mint == mint)
            .order_by(SolanaLaunchEvent.observed_at.asc())
            .limit(1)
        )
        if launch is None:
            return 0
        launch_at = _aware(launch.observed_at)
        snapshots = list(
            db.scalars(
                select(SolanaDexSnapshot)
                .where(
                    SolanaDexSnapshot.mint == mint,
                    SolanaDexSnapshot.captured_at >= launch.observed_at,
                )
                .order_by(SolanaDexSnapshot.captured_at.asc())
            ).all()
        )
        if not snapshots:
            return 0
        entry = snapshots[0]
        entry_at = _aware(entry.captured_at)
        if entry_at < launch_at:
            return 0

        created = 0
        for horizon in horizons:
            if horizon <= 0:
                continue
            if db.scalar(
                select(SolanaForwardLabel.id).where(
                    SolanaForwardLabel.mint == mint,
                    SolanaForwardLabel.horizon_minutes == horizon,
                    SolanaForwardLabel.launch_signature == launch.signature,
                )
            ):
                continue

            target = entry_at + timedelta(minutes=horizon)
            future = next((s for s in snapshots if _aware(s.captured_at) >= target), None)
            if future is None:
                continue
            future_at = _aware(future.captured_at)
            observed_horizon = Decimal(str((future_at - entry_at).total_seconds() / 60))
            lateness = observed_horizon - Decimal(horizon)
            if lateness < ZERO or lateness > ForwardLabelService._max_lateness_minutes(horizon):
                continue

            return_pct = None
            if entry.price_usd > ZERO:
                return_pct = ((future.price_usd - entry.price_usd) / entry.price_usd) * Decimal("100")
            max_liq = max(
                (
                    s.liquidity_usd
                    for s in snapshots
                    if entry_at <= _aware(s.captured_at) <= future_at
                ),
                default=future.liquidity_usd,
            )
            db.add(
                SolanaForwardLabel(
                    mint=mint,
                    launch_signature=launch.signature,
                    horizon_minutes=horizon,
                    entry_observed_at=entry.captured_at,
                    observed_horizon_minutes=observed_horizon,
                    entry_price_usd=entry.price_usd,
                    future_price_usd=future.price_usd,
                    return_pct=return_pct,
                    max_observed_liquidity_usd=max_liq,
                    exit_quote_available=None,
                    resolved_at=future.captured_at,
                )
            )
            created += 1
        db.commit()
        return created
