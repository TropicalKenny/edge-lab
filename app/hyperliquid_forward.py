from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forward_models import ForwardExecutionRecord, ForwardNavObservation, ForwardStudy, ForwardTradeRecord
from app.forward_research import ForwardResearchError, ForwardResearchService
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.hyperliquid_research import HyperliquidResearchService
from app.schemas import PaperExecutionResult
from app.services import HealthRegistry, PaperBroker
from app.venues.hyperliquid import (
    FundingCarryAnalyzer,
    HyperliquidInfoClient,
    PerpContext,
    SpotContext,
    l2_book_to_paper_order,
)
from app.venues.hyperliquid_models import HyperliquidFundingSnapshot, HyperliquidPerpSnapshot

ZERO = Decimal("0")
BPS = Decimal("10000")


class CarryRunnerError(RuntimeError):
    pass


class CarryRunnerConfigError(CarryRunnerError):
    pass


@dataclass(frozen=True)
class CarryStudyConfig:
    paired_notional_usd: Decimal
    horizon_hours: int
    min_edge_bps: Decimal
    planned_loss_pct: Decimal
    spot_fee_bps: Decimal
    perp_fee_bps: Decimal
    slippage_reserve_bps_per_leg: Decimal
    shadow_delay_ms: int
    max_exit_delay_hours: int
    max_funding_oracle_age_minutes: int

    @classmethod
    def from_study(cls, study: ForwardStudy) -> "CarryStudyConfig":
        try:
            raw = json.loads(study.study_config_json)
        except json.JSONDecodeError as exc:
            raise CarryRunnerConfigError("study_config_json is invalid JSON") from exc
        if not isinstance(raw, dict) or raw.get("runner") != "hyperliquid_carry_v1":
            raise CarryRunnerConfigError("forward study must declare runner=hyperliquid_carry_v1")
        try:
            config = cls(
                paired_notional_usd=Decimal(str(raw["paired_notional_usd"])),
                horizon_hours=int(raw.get("horizon_hours", 24)),
                min_edge_bps=Decimal(str(raw.get("min_edge_bps", 10))),
                planned_loss_pct=Decimal(str(raw.get("planned_loss_pct", "0.02"))),
                spot_fee_bps=Decimal(str(raw.get("spot_fee_bps", "7.0"))),
                perp_fee_bps=Decimal(str(raw.get("perp_fee_bps", "4.5"))),
                slippage_reserve_bps_per_leg=Decimal(
                    str(raw.get("slippage_reserve_bps_per_leg", "2"))
                ),
                shadow_delay_ms=int(raw.get("shadow_delay_ms", 1000)),
                max_exit_delay_hours=int(raw.get("max_exit_delay_hours", 6)),
                max_funding_oracle_age_minutes=int(raw.get("max_funding_oracle_age_minutes", 5)),
            )
        except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
            raise CarryRunnerConfigError(f"invalid Hyperliquid carry study config: {exc}") from exc
        config.validate(study)
        return config

    def validate(self, study: ForwardStudy) -> None:
        if self.paired_notional_usd <= ZERO:
            raise CarryRunnerConfigError("paired_notional_usd must be positive")
        if self.paired_notional_usd * Decimal("2") > Decimal(study.initial_capital_usd):
            raise CarryRunnerConfigError(
                "paired carry capital exceeds study initial capital without leverage"
            )
        if self.horizon_hours < 1 or self.horizon_hours > 72:
            raise CarryRunnerConfigError("horizon_hours must be between 1 and 72")
        if self.min_edge_bps < ZERO:
            raise CarryRunnerConfigError("min_edge_bps cannot be negative")
        if self.planned_loss_pct <= ZERO or self.planned_loss_pct > Decimal("0.25"):
            raise CarryRunnerConfigError("planned_loss_pct must be >0 and <=0.25")
        for value in (
            self.spot_fee_bps,
            self.perp_fee_bps,
            self.slippage_reserve_bps_per_leg,
        ):
            if value < ZERO:
                raise CarryRunnerConfigError("fees/slippage reserve cannot be negative")
        if self.shadow_delay_ms < 0 or self.shadow_delay_ms > 5000:
            raise CarryRunnerConfigError("shadow_delay_ms must be between 0 and 5000")
        if self.max_exit_delay_hours < 1 or self.max_exit_delay_hours > 24:
            raise CarryRunnerConfigError("max_exit_delay_hours must be between 1 and 24")
        if self.max_funding_oracle_age_minutes < 1 or self.max_funding_oracle_age_minutes > 60:
            raise CarryRunnerConfigError(
                "max_funding_oracle_age_minutes must be between 1 and 60"
            )


@dataclass(frozen=True)
class LegCapture:
    paper: PaperExecutionResult
    shadow: PaperExecutionResult
    paper_at: datetime
    shadow_at: datetime


@dataclass(frozen=True)
class PairCapture:
    spot: LegCapture
    perp: LegCapture

    @property
    def fully_executable(self) -> bool:
        return all(
            result.status == "filled" and result.filled_quantity == result.requested_quantity
            for result in (self.spot.paper, self.spot.shadow, self.perp.paper, self.perp.shadow)
        )


@dataclass(frozen=True)
class TickResult:
    study_id: str
    action: str
    detail: str


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _hour_bucket(value: datetime) -> datetime:
    value = _aware(value)
    return value.replace(minute=0, second=0, microsecond=0)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _fee(result: PaperExecutionResult) -> Decimal:
    return Decimal(result.total_fees) + Decimal(result.network_fee)


def _adverse_slippage(
    side: str, *, mid: Decimal, fill: Decimal, quantity: Decimal
) -> Decimal:
    if side == "buy":
        return max(fill - mid, ZERO) * quantity
    return max(mid - fill, ZERO) * quantity


def _full(result: PaperExecutionResult, quantity: Decimal) -> bool:
    return (
        result.status == "filled"
        and Decimal(result.filled_quantity) == quantity
        and result.average_price is not None
    )


class HyperliquidCarryForwardRunner:
    """Public-data-only paper/shadow runner for long-spot/short-perp funding carry."""

    def __init__(
        self,
        *,
        client: HyperliquidInfoClient,
        health: HealthRegistry | None = None,
        sleep=asyncio.sleep,
    ) -> None:
        self.client = client
        self.health = health or HealthRegistry()
        self.sleep = sleep
        self.research = HyperliquidResearchService(client=client, health=self.health)

    async def run_active_studies(
        self, db: Session, *, now: datetime | None = None
    ) -> list[TickResult]:
        now = _aware(now or datetime.now(timezone.utc))
        studies = db.scalars(
            select(ForwardStudy).where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "hyperliquid",
                ForwardStudy.family == "funding",
            )
        ).all()
        results: list[TickResult] = []
        for study in studies:
            try:
                results.append(await self.run_study_once(db, study=study, now=now))
            except CarryRunnerConfigError as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="critical",
                    code="HL_CARRY_CONFIG_INVALID",
                    message=str(exc),
                    data_integrity=True,
                )
                results.append(TickResult(study.id, "blocked", str(exc)))
            except (ForwardResearchError, CarryRunnerError) as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="HL_CARRY_RUNNER_ERROR",
                    message=str(exc),
                    data_integrity=False,
                )
                results.append(TickResult(study.id, "error", str(exc)))
            except Exception as exc:
                db.rollback()
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="HL_CARRY_UNEXPECTED_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                    data_integrity=False,
                )
                results.append(
                    TickResult(study.id, "error", f"{type(exc).__name__}: {exc}")
                )
        return results

    async def run_study_once(
        self, db: Session, *, study: ForwardStudy, now: datetime
    ) -> TickResult:
        if study.status != "active" or study.venue != "hyperliquid" or study.family != "funding":
            raise CarryRunnerError("study is not an active Hyperliquid funding study")
        config = CarryStudyConfig.from_study(study)
        coin = study.instrument.strip().upper()
        if not coin:
            raise CarryRunnerConfigError("study instrument is required")
        self._ensure_initial_nav(db, study)

        perps, spots = await self.research.market_state(db, persist=True)
        perp = next((row for row in perps if row.coin.upper() == coin), None)
        if perp is None:
            raise CarryRunnerError(f"perp market not found for {coin}")
        aliases = {"BTC": "UBTC"}
        wanted_base = aliases.get(coin, coin)
        spot = next(
            (
                row
                for row in spots
                if row.base.upper() == wanted_base and row.quote.upper() == "USDC"
            ),
            None,
        )
        if spot is None:
            raise CarryRunnerError(f"USDC spot market not found for {coin}")

        positions = db.scalars(
            select(HyperliquidCarryPosition).where(
                HyperliquidCarryPosition.study_id == study.id,
                HyperliquidCarryPosition.status == "open",
            )
        ).all()
        if len(positions) > 1:
            raise CarryRunnerError("multiple open carry positions found for one study")
        position = positions[0] if positions else None
        if position is not None and now >= _aware(position.target_close_at):
            close_result = await self._attempt_close(
                db, study, position, perp, spot, config, now
            )
            if close_result.action == "closed":
                self._record_flat_nav_if_due(
                    db, study, _aware(position.closed_at or datetime.now(timezone.utc))
                )
            else:
                await self._record_open_nav_if_due(
                    db, study, position, perp, spot, config, now
                )
            return close_result

        if position is None:
            entry_result = await self._attempt_entry(db, study, perp, spot, config, now)
            positions = db.scalars(
                select(HyperliquidCarryPosition).where(
                    HyperliquidCarryPosition.study_id == study.id,
                    HyperliquidCarryPosition.status == "open",
                )
            ).all()
            if len(positions) > 1:
                raise CarryRunnerError("multiple open carry positions created for one study")
            position = positions[0] if positions else None
            if position is not None:
                await self._record_open_nav_if_due(
                    db, study, position, perp, spot, config, now
                )
            else:
                self._record_flat_nav_if_due(db, study, now)
            return entry_result

        await self._record_open_nav_if_due(db, study, position, perp, spot, config, now)
        return TickResult(study.id, "holding", f"{coin} carry position remains open")

    def _ensure_initial_nav(self, db: Session, study: ForwardStudy) -> None:
        started_at = _aware(study.started_at)
        exists = db.scalar(
            select(ForwardNavObservation.id).where(
                ForwardNavObservation.study_id == study.id,
                ForwardNavObservation.observed_at == started_at,
            )
        )
        if exists is None:
            ForwardResearchService.record_nav(
                db,
                study_id=study.id,
                observed_at=started_at,
                nav_usd=Decimal(study.initial_capital_usd),
                source="study-initial-capital",
            )

    async def _attempt_entry(
        self,
        db: Session,
        study: ForwardStudy,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
    ) -> TickResult:
        bucket = _hour_bucket(now)
        attempt_key = f"hlcarry:entry:{perp.coin}:{bucket.isoformat()}"
        if self._execution_attempt_exists(db, study.id, attempt_key):
            return TickResult(study.id, "entry_already_attempted", attempt_key)

        analyzer = FundingCarryAnalyzer(
            perp_taker_fee_bps=config.perp_fee_bps,
            spot_taker_fee_bps=config.spot_fee_bps,
            slippage_reserve_bps_per_leg=config.slippage_reserve_bps_per_leg,
        )
        opportunities = analyzer.analyze(
            [perp],
            [spot],
            horizon_hours=config.horizon_hours,
            min_expected_edge_pct=config.min_edge_bps / BPS,
        )
        if not opportunities or not opportunities[0].eligible:
            reason = opportunities[0].reasons if opportunities else ("NO_MATCHING_OPPORTUNITY",)
            return TickResult(study.id, "no_entry", ",".join(reason))
        opportunity = opportunities[0]

        quantity = self._quantity_for(perp, config.paired_notional_usd, spot.mid_px)
        if quantity <= ZERO:
            raise CarryRunnerConfigError("configured notional rounds to zero executable quantity")
        capture = await self._capture_pair(
            spot_coin=spot.book_coin,
            perp_coin=perp.coin,
            spot_side="buy",
            perp_side="sell",
            quantity=quantity,
            config=config,
        )
        self._record_pair_execution(
            db,
            study,
            attempt_key=attempt_key,
            phase="entry",
            spot_coin=spot.book_coin,
            perp_coin=perp.coin,
            spot_side="buy",
            perp_side="sell",
            quantity=quantity,
            capture=capture,
        )
        if not capture.fully_executable:
            return TickResult(
                study.id,
                "entry_rejected",
                "paper/shadow depth insufficient for both hedge legs",
            )

        spot_price = Decimal(capture.spot.paper.average_price)
        perp_price = Decimal(capture.perp.paper.average_price)
        opened_at = max(capture.spot.paper_at, capture.perp.paper_at)
        allocated = config.paired_notional_usd * Decimal("2")
        planned_loss = allocated * config.planned_loss_pct
        entry_spot_slippage = _adverse_slippage(
            "buy", mid=spot.mid_px, fill=spot_price, quantity=quantity
        )
        entry_perp_slippage = _adverse_slippage(
            "sell", mid=perp.mid_px or perp.mark_px, fill=perp_price, quantity=quantity
        )
        position = HyperliquidCarryPosition(
            study_id=study.id,
            external_key=attempt_key,
            coin=perp.coin,
            spot_book_coin=spot.book_coin,
            status="open",
            quantity=quantity,
            allocated_capital_usd=allocated,
            planned_loss_usd=planned_loss,
            opened_at=opened_at,
            target_close_at=opened_at + timedelta(hours=config.horizon_hours),
            entry_spot_mid=spot.mid_px,
            entry_perp_mid=perp.mid_px or perp.mark_px,
            entry_spot_price=spot_price,
            entry_perp_price=perp_price,
            entry_spot_fee_usd=_fee(capture.spot.paper),
            entry_perp_fee_usd=_fee(capture.perp.paper),
            entry_spot_slippage_usd=entry_spot_slippage,
            entry_perp_slippage_usd=entry_perp_slippage,
            metadata_json=_json(
                {
                    "expected_edge_pct": opportunity.expected_edge_pct,
                    "funding_rate_hourly": opportunity.funding_rate_hourly,
                    "basis_bps": opportunity.basis_bps,
                    "signal_captured_at": opportunity.captured_at,
                    "shadow_delay_ms": config.shadow_delay_ms,
                    "max_funding_oracle_age_minutes": config.max_funding_oracle_age_minutes,
                }
            ),
        )
        db.add(position)
        db.commit()
        return TickResult(study.id, "opened", f"opened {perp.coin} carry qty={quantity}")

    async def _attempt_close(
        self,
        db: Session,
        study: ForwardStudy,
        position: HyperliquidCarryPosition,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
    ) -> TickResult:
        bucket = _hour_bucket(now)
        attempt_key = f"hlcarry:exit:{position.id}:{bucket.isoformat()}"
        if self._execution_attempt_exists(db, study.id, attempt_key):
            return TickResult(study.id, "exit_already_attempted", attempt_key)

        elapsed_hours = max(
            1,
            math.ceil((now - _aware(position.opened_at)).total_seconds() / 3600) + 2,
        )
        await self.research.funding_history(
            db,
            coin=position.coin,
            hours=min(elapsed_hours, 24 * 90),
            persist=True,
            now=now,
        )
        capture = await self._capture_pair(
            spot_coin=position.spot_book_coin,
            perp_coin=position.coin,
            spot_side="sell",
            perp_side="buy",
            quantity=Decimal(position.quantity),
            config=config,
        )
        self._record_pair_execution(
            db,
            study,
            attempt_key=attempt_key,
            phase="exit",
            spot_coin=position.spot_book_coin,
            perp_coin=position.coin,
            spot_side="sell",
            perp_side="buy",
            quantity=Decimal(position.quantity),
            capture=capture,
        )
        if not capture.fully_executable:
            if now > _aware(position.target_close_at) + timedelta(
                hours=config.max_exit_delay_hours
            ):
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="critical",
                    code="HL_CARRY_EXIT_DELAY_EXCEEDED",
                    message=f"position {position.id} could not be fully exited inside max delay",
                    data_integrity=False,
                )
            return TickResult(
                study.id,
                "exit_rejected",
                "paper/shadow depth insufficient for both exit legs",
            )

        quantity = Decimal(position.quantity)
        close_at = max(capture.spot.paper_at, capture.perp.paper_at)
        exit_spot_price = Decimal(capture.spot.paper.average_price)
        exit_perp_price = Decimal(capture.perp.paper.average_price)
        exit_spot_mid = spot.mid_px
        exit_perp_mid = perp.mid_px or perp.mark_px
        funding_pnl = self._funding_pnl(
            db,
            position,
            close_at,
            max_oracle_age_minutes=config.max_funding_oracle_age_minutes,
        )
        gross_pnl = (
            quantity * (exit_spot_mid - Decimal(position.entry_spot_mid))
            + quantity * (Decimal(position.entry_perp_mid) - exit_perp_mid)
            + funding_pnl
        )
        exit_spot_slippage = _adverse_slippage(
            "sell", mid=exit_spot_mid, fill=exit_spot_price, quantity=quantity
        )
        exit_perp_slippage = _adverse_slippage(
            "buy", mid=exit_perp_mid, fill=exit_perp_price, quantity=quantity
        )
        fees = (
            Decimal(position.entry_spot_fee_usd)
            + Decimal(position.entry_perp_fee_usd)
            + _fee(capture.spot.paper)
            + _fee(capture.perp.paper)
        )
        slippage = (
            Decimal(position.entry_spot_slippage_usd)
            + Decimal(position.entry_perp_slippage_usd)
            + exit_spot_slippage
            + exit_perp_slippage
        )
        net_pnl = gross_pnl - fees - slippage
        trade_key = f"hlcarry:trade:{position.external_key}"
        if db.scalar(
            select(ForwardTradeRecord.id).where(
                ForwardTradeRecord.study_id == study.id,
                ForwardTradeRecord.external_key == trade_key,
            )
        ) is not None:
            raise CarryRunnerError("closed trade exists while carry position is still open")
        trade = ForwardTradeRecord(
            study_id=study.id,
            external_key=trade_key,
            opened_at=_aware(position.opened_at),
            closed_at=close_at,
            gross_pnl_usd=gross_pnl,
            net_pnl_usd=net_pnl,
            fees_usd=fees,
            slippage_usd=slippage,
            allocated_capital_usd=Decimal(position.allocated_capital_usd),
            planned_loss_usd=Decimal(position.planned_loss_usd),
            metadata_json=_json(
                {
                    "position_id": position.id,
                    "coin": position.coin,
                    "funding_pnl_usd": funding_pnl,
                    "entry_spot_mid": position.entry_spot_mid,
                    "entry_perp_mid": position.entry_perp_mid,
                    "exit_spot_mid": exit_spot_mid,
                    "exit_perp_mid": exit_perp_mid,
                    "close_reason": "horizon_elapsed",
                }
            ),
        )
        db.add(trade)
        db.flush()
        position.trade_record_id = trade.id
        position.status = "closed"
        position.closed_at = close_at
        position.exit_spot_mid = exit_spot_mid
        position.exit_perp_mid = exit_perp_mid
        position.exit_spot_price = exit_spot_price
        position.exit_perp_price = exit_perp_price
        position.funding_pnl_usd = funding_pnl
        position.gross_pnl_usd = gross_pnl
        position.fees_usd = fees
        position.slippage_usd = slippage
        position.net_pnl_usd = net_pnl
        position.close_reason = "horizon_elapsed"
        db.commit()
        return TickResult(
            study.id, "closed", f"closed {position.coin} carry net_pnl={net_pnl}"
        )

    async def _capture_pair(
        self,
        *,
        spot_coin: str,
        perp_coin: str,
        spot_side: str,
        perp_side: str,
        quantity: Decimal,
        config: CarryStudyConfig,
    ) -> PairCapture:
        spot_payload, perp_payload = await asyncio.gather(
            self.client.l2_book(spot_coin),
            self.client.l2_book(perp_coin),
        )
        spot_order = l2_book_to_paper_order(
            spot_payload,
            side=spot_side,
            quantity=quantity,
            fee_bps=config.spot_fee_bps,
            allow_partial=True,
            max_data_age_seconds=10,
        )
        perp_order = l2_book_to_paper_order(
            perp_payload,
            side=perp_side,
            quantity=quantity,
            fee_bps=config.perp_fee_bps,
            allow_partial=True,
            max_data_age_seconds=10,
        )
        paper_now = datetime.now(timezone.utc)
        paper_spot = PaperBroker.simulate(spot_order, now=paper_now)
        paper_perp = PaperBroker.simulate(perp_order, now=paper_now)

        if config.shadow_delay_ms:
            await self.sleep(config.shadow_delay_ms / 1000)
        shadow_spot_payload, shadow_perp_payload = await asyncio.gather(
            self.client.l2_book(spot_coin),
            self.client.l2_book(perp_coin),
        )
        shadow_spot_order = l2_book_to_paper_order(
            shadow_spot_payload,
            side=spot_side,
            quantity=quantity,
            fee_bps=config.spot_fee_bps,
            allow_partial=True,
            max_data_age_seconds=10,
        )
        shadow_perp_order = l2_book_to_paper_order(
            shadow_perp_payload,
            side=perp_side,
            quantity=quantity,
            fee_bps=config.perp_fee_bps,
            allow_partial=True,
            max_data_age_seconds=10,
        )
        shadow_now = datetime.now(timezone.utc)
        shadow_spot = PaperBroker.simulate(shadow_spot_order, now=shadow_now)
        shadow_perp = PaperBroker.simulate(shadow_perp_order, now=shadow_now)
        return PairCapture(
            spot=LegCapture(
                paper_spot,
                shadow_spot,
                _aware(spot_order.market_data_at),
                _aware(shadow_spot_order.market_data_at),
            ),
            perp=LegCapture(
                paper_perp,
                shadow_perp,
                _aware(perp_order.market_data_at),
                _aware(shadow_perp_order.market_data_at),
            ),
        )

    def _record_pair_execution(
        self,
        db: Session,
        study: ForwardStudy,
        *,
        attempt_key: str,
        phase: str,
        spot_coin: str,
        perp_coin: str,
        spot_side: str,
        perp_side: str,
        quantity: Decimal,
        capture: PairCapture,
    ) -> None:
        for leg, instrument, side, result in (
            ("spot", spot_coin, spot_side, capture.spot),
            ("perp", perp_coin, perp_side, capture.perp),
        ):
            ForwardResearchService.record_execution(
                db,
                study_id=study.id,
                external_key=f"{attempt_key}:{leg}",
                observed_at=result.shadow_at,
                side=side,
                intended_quantity=quantity,
                paper_filled_quantity=Decimal(result.paper.filled_quantity),
                shadow_filled_quantity=Decimal(result.shadow.filled_quantity),
                paper_average_price=(
                    Decimal(result.paper.average_price)
                    if result.paper.average_price is not None
                    else None
                ),
                shadow_average_price=(
                    Decimal(result.shadow.average_price)
                    if result.shadow.average_price is not None
                    else None
                ),
                paper_cost_usd=_fee(result.paper),
                shadow_cost_usd=_fee(result.shadow),
                metadata={
                    "phase": phase,
                    "leg": leg,
                    "instrument": instrument,
                    "paper_market_data_at": result.paper_at,
                    "shadow_market_data_at": result.shadow_at,
                },
            )

    async def _record_open_nav_if_due(
        self,
        db: Session,
        study: ForwardStudy,
        position: HyperliquidCarryPosition,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
    ) -> None:
        quantity = Decimal(position.quantity)
        spot_payload, perp_payload = await asyncio.gather(
            self.client.l2_book(position.spot_book_coin),
            self.client.l2_book(position.coin),
        )
        spot_order = l2_book_to_paper_order(
            spot_payload,
            side="sell",
            quantity=quantity,
            fee_bps=config.spot_fee_bps,
            allow_partial=False,
            max_data_age_seconds=10,
        )
        perp_order = l2_book_to_paper_order(
            perp_payload,
            side="buy",
            quantity=quantity,
            fee_bps=config.perp_fee_bps,
            allow_partial=False,
            max_data_age_seconds=10,
        )
        observed_at = max(
            _aware(spot_order.market_data_at), _aware(perp_order.market_data_at)
        )
        if observed_at <= _aware(study.started_at) or self._nav_exists_for_hour(
            db, study.id, observed_at
        ):
            return
        mark_now = datetime.now(timezone.utc)
        spot_exit = PaperBroker.simulate(spot_order, now=mark_now)
        perp_exit = PaperBroker.simulate(perp_order, now=mark_now)
        if not _full(spot_exit, quantity) or not _full(perp_exit, quantity):
            self._record_runner_incident(
                db,
                study,
                now,
                severity="warning",
                code="HL_CARRY_NAV_NOT_EXECUTABLE",
                message=f"could not compute executable NAV for open position {position.id}",
                data_integrity=False,
            )
            return
        funding = self._funding_pnl(
            db,
            position,
            observed_at,
            max_oracle_age_minutes=config.max_funding_oracle_age_minutes,
        )
        current_perp_mid = perp.mid_px or perp.mark_px
        gross = (
            quantity * (spot.mid_px - Decimal(position.entry_spot_mid))
            + quantity * (Decimal(position.entry_perp_mid) - current_perp_mid)
            + funding
        )
        exit_slippage = _adverse_slippage(
            "sell", mid=spot.mid_px, fill=Decimal(spot_exit.average_price), quantity=quantity
        ) + _adverse_slippage(
            "buy",
            mid=current_perp_mid,
            fill=Decimal(perp_exit.average_price),
            quantity=quantity,
        )
        entry_costs = (
            Decimal(position.entry_spot_fee_usd)
            + Decimal(position.entry_perp_fee_usd)
            + Decimal(position.entry_spot_slippage_usd)
            + Decimal(position.entry_perp_slippage_usd)
        )
        exit_costs = _fee(spot_exit) + _fee(perp_exit) + exit_slippage
        realised = self._realised_pnl(db, study.id)
        nav = Decimal(study.initial_capital_usd) + realised + gross - entry_costs - exit_costs
        if nav <= ZERO:
            self._record_runner_incident(
                db,
                study,
                now,
                severity="critical",
                code="HL_CARRY_NAV_NON_POSITIVE",
                message=f"computed non-positive NAV {nav}",
                data_integrity=True,
            )
            return
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=observed_at,
            nav_usd=nav,
            source="hyperliquid-carry-executable-mark",
        )

    def _record_flat_nav_if_due(
        self, db: Session, study: ForwardStudy, observed_at: datetime
    ) -> None:
        observed_at = _aware(observed_at)
        if observed_at <= _aware(study.started_at) or self._nav_exists_for_hour(
            db, study.id, observed_at
        ):
            return
        nav = Decimal(study.initial_capital_usd) + self._realised_pnl(db, study.id)
        if nav <= ZERO:
            raise CarryRunnerError("flat study NAV is non-positive")
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=observed_at,
            nav_usd=nav,
            source="hyperliquid-carry-realised-nav",
        )

    def _funding_pnl(
        self,
        db: Session,
        position: HyperliquidCarryPosition,
        through: datetime,
        *,
        max_oracle_age_minutes: int,
    ) -> Decimal:
        through = _aware(through)
        funding_rows = db.scalars(
            select(HyperliquidFundingSnapshot)
            .where(
                HyperliquidFundingSnapshot.coin == position.coin,
                HyperliquidFundingSnapshot.funding_time > _aware(position.opened_at),
                HyperliquidFundingSnapshot.funding_time <= through,
            )
            .order_by(HyperliquidFundingSnapshot.funding_time.asc())
        ).all()
        if not funding_rows:
            return ZERO
        max_age = timedelta(minutes=max_oracle_age_minutes)
        price_rows = db.scalars(
            select(HyperliquidPerpSnapshot)
            .where(
                HyperliquidPerpSnapshot.coin == position.coin,
                HyperliquidPerpSnapshot.captured_at
                >= _aware(position.opened_at) - max_age,
                HyperliquidPerpSnapshot.captured_at <= through,
            )
            .order_by(HyperliquidPerpSnapshot.captured_at.asc())
        ).all()
        quantity = Decimal(position.quantity)
        total = ZERO
        index = 0
        last_snapshot: HyperliquidPerpSnapshot | None = None
        for funding in funding_rows:
            funding_time = _aware(funding.funding_time)
            while index < len(price_rows) and _aware(price_rows[index].captured_at) <= funding_time:
                last_snapshot = price_rows[index]
                index += 1
            if last_snapshot is None:
                raise CarryRunnerError(
                    f"missing oracle snapshot for funding at {funding_time.isoformat()}"
                )
            oracle_time = _aware(last_snapshot.captured_at)
            if funding_time - oracle_time > max_age:
                raise CarryRunnerError(
                    f"oracle snapshot too old for funding at {funding_time.isoformat()}"
                )
            total += (
                quantity
                * Decimal(last_snapshot.oracle_px)
                * Decimal(funding.funding_rate)
            )
        return total

    @staticmethod
    def _quantity_for(perp: PerpContext, notional: Decimal, spot_mid: Decimal) -> Decimal:
        quantum = Decimal("1").scaleb(-max(0, int(perp.sz_decimals)))
        return (notional / spot_mid).quantize(quantum, rounding=ROUND_DOWN)

    @staticmethod
    def _execution_attempt_exists(db: Session, study_id: str, attempt_key: str) -> bool:
        rows = db.scalars(
            select(ForwardExecutionRecord.external_key).where(
                ForwardExecutionRecord.study_id == study_id,
                ForwardExecutionRecord.external_key.in_(
                    [f"{attempt_key}:spot", f"{attempt_key}:perp"]
                ),
            )
        ).all()
        if len(rows) == 1:
            raise CarryRunnerError(
                f"partial persisted execution attempt detected for {attempt_key}"
            )
        return len(rows) == 2

    @staticmethod
    def _nav_exists_for_hour(
        db: Session, study_id: str, observed_at: datetime
    ) -> bool:
        bucket = _hour_bucket(observed_at)
        return db.scalar(
            select(ForwardNavObservation.id).where(
                ForwardNavObservation.study_id == study_id,
                ForwardNavObservation.observed_at >= bucket,
                ForwardNavObservation.observed_at < bucket + timedelta(hours=1),
            )
        ) is not None

    @staticmethod
    def _realised_pnl(db: Session, study_id: str) -> Decimal:
        value = db.scalar(
            select(func.coalesce(func.sum(ForwardTradeRecord.net_pnl_usd), ZERO)).where(
                ForwardTradeRecord.study_id == study_id
            )
        )
        return Decimal(str(value or ZERO))

    @staticmethod
    def _record_runner_incident(
        db: Session,
        study: ForwardStudy,
        now: datetime,
        *,
        severity: str,
        code: str,
        message: str,
        data_integrity: bool,
    ) -> None:
        bucket = _hour_bucket(now)
        key = f"hlcarry:{code}:{bucket.isoformat()}"
        try:
            ForwardResearchService.record_incident(
                db,
                study_id=study.id,
                external_key=key,
                severity=severity,
                code=code,
                message=message[:2000],
                opened_at=now,
                data_integrity=data_integrity,
            )
        except ForwardResearchError as exc:
            if "conflicting retry" not in str(exc):
                raise
