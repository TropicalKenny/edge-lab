from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy, ForwardTradeRecord
from app.forward_research import ForwardResearchError
from app.hyperliquid_forward import (
    CarryRunnerConfigError,
    CarryRunnerError,
    CarryStudyConfig,
    HyperliquidCarryForwardRunner,
    TickResult,
    _adverse_slippage,
    _aware,
    _fee,
    _full,
    _hour_bucket,
    _json,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.services import PaperBroker
from app.venues.hyperliquid import PerpContext, SpotContext, l2_book_to_paper_order
from app.venues.hyperliquid_models import HyperliquidFundingSnapshot

ZERO = Decimal("0")


class CarryDataIntegrityError(CarryRunnerError):
    """Forward evidence cannot be valued honestly from the persisted public data."""


class HardenedHyperliquidCarryForwardRunner(HyperliquidCarryForwardRunner):
    """Adds equity-aware entry sizing, funding refresh and planned-loss exits."""

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
            except CarryDataIntegrityError as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="critical",
                    code="HL_CARRY_DATA_INTEGRITY",
                    message=str(exc),
                    data_integrity=True,
                )
                results.append(TickResult(study.id, "blocked", str(exc)))
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
        now = _aware(now)
        if study.status != "active" or study.venue != "hyperliquid" or study.family != "funding":
            raise CarryRunnerError("study is not an active Hyperliquid funding study")
        config = CarryStudyConfig.from_study(study)
        coin = study.instrument.strip().upper()
        if not coin:
            raise CarryRunnerConfigError("study instrument is required")
        self._ensure_initial_nav(db, study)

        perps, spots = await self.research.market_state(db, persist=True)
        perp, spot = self._resolve_markets(coin, perps, spots)

        positions = db.scalars(
            select(HyperliquidCarryPosition).where(
                HyperliquidCarryPosition.study_id == study.id,
                HyperliquidCarryPosition.status == "open",
            )
        ).all()
        if len(positions) > 1:
            raise CarryRunnerError("multiple open carry positions found for one study")
        position = positions[0] if positions else None

        if position is not None:
            await self._refresh_funding(db, position, through=now)
            close_reason: str | None = None
            if now >= _aware(position.target_close_at):
                close_reason = "horizon_elapsed"
            elif await self._planned_loss_triggered(
                db, study, position, perp, spot, config, now
            ):
                close_reason = "planned_loss"

            if close_reason is not None:
                close_result = await self._attempt_close_reasoned(
                    db,
                    study,
                    position,
                    perp,
                    spot,
                    config,
                    now,
                    close_reason=close_reason,
                )
                if close_result.action == "closed":
                    self._record_flat_nav_if_due(
                        db,
                        study,
                        _aware(position.closed_at or datetime.now(timezone.utc)),
                    )
                else:
                    await self._record_open_nav_if_due(
                        db, study, position, perp, spot, config, now
                    )
                return close_result

            await self._record_open_nav_if_due(
                db, study, position, perp, spot, config, now
            )
            return TickResult(study.id, "holding", f"{coin} carry position remains open")

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

    @staticmethod
    def _resolve_markets(
        coin: str, perps: list[PerpContext], spots: list[SpotContext]
    ) -> tuple[PerpContext, SpotContext]:
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
        return perp, spot

    async def _attempt_entry(
        self,
        db: Session,
        study: ForwardStudy,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
    ) -> TickResult:
        result = await super()._attempt_entry(db, study, perp, spot, config, now)
        if result.action != "opened":
            return result

        position = db.scalar(
            select(HyperliquidCarryPosition).where(
                HyperliquidCarryPosition.study_id == study.id,
                HyperliquidCarryPosition.status == "open",
            )
        )
        if position is None:
            raise CarryRunnerError("entry reported open but no open position was persisted")

        quantity = Decimal(position.quantity)
        actual_required = (
            quantity * Decimal(position.entry_spot_price)
            + quantity * Decimal(position.entry_perp_price)
            + Decimal(position.entry_spot_fee_usd)
            + Decimal(position.entry_perp_fee_usd)
        )
        flat_equity = Decimal(study.initial_capital_usd) + self._realised_pnl(db, study.id)
        position.allocated_capital_usd = actual_required
        position.planned_loss_usd = actual_required * config.planned_loss_pct
        if actual_required > flat_equity:
            position.status = "rejected"
            position.close_reason = "entry_capital_exceeded"
            db.commit()
            self._record_runner_incident(
                db,
                study,
                now,
                severity="warning",
                code="HL_CARRY_ENTRY_CAPITAL_EXCEEDED",
                message=(
                    f"actual fully-collateralized entry requirement {actual_required} "
                    f"exceeded available simulated equity {flat_equity}"
                ),
                data_integrity=False,
            )
            return TickResult(
                study.id,
                "entry_rejected_capital",
                "actual executable notionals plus fees exceed simulated study equity",
            )
        db.commit()
        return result

    async def _refresh_funding(
        self,
        db: Session,
        position: HyperliquidCarryPosition,
        *,
        through: datetime,
    ) -> None:
        through = _aware(through)
        elapsed = through - _aware(position.opened_at)
        if elapsed < timedelta(hours=1):
            return
        hours = max(2, math.ceil(elapsed.total_seconds() / 3600) + 2)
        await self.research.funding_history(
            db,
            coin=position.coin,
            hours=min(hours, 24 * 90),
            persist=True,
            now=through,
        )
        if elapsed >= timedelta(hours=2):
            settlements = db.scalar(
                select(func.count())
                .select_from(HyperliquidFundingSnapshot)
                .where(
                    HyperliquidFundingSnapshot.coin == position.coin,
                    HyperliquidFundingSnapshot.funding_time > _aware(position.opened_at),
                    HyperliquidFundingSnapshot.funding_time <= through,
                )
            )
            if int(settlements or 0) == 0:
                raise CarryDataIntegrityError(
                    "no settled funding rows found after two hours of carry exposure"
                )

    def _funding_pnl_checked(
        self,
        db: Session,
        position: HyperliquidCarryPosition,
        through: datetime,
        *,
        config: CarryStudyConfig,
    ) -> Decimal:
        try:
            return self._funding_pnl(
                db,
                position,
                through,
                max_oracle_age_minutes=config.max_funding_oracle_age_minutes,
            )
        except CarryRunnerError as exc:
            raise CarryDataIntegrityError(str(exc)) from exc

    async def _planned_loss_triggered(
        self,
        db: Session,
        study: ForwardStudy,
        position: HyperliquidCarryPosition,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
    ) -> bool:
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
        preview_now = datetime.now(timezone.utc)
        spot_exit = PaperBroker.simulate(spot_order, now=preview_now)
        perp_exit = PaperBroker.simulate(perp_order, now=preview_now)
        if not _full(spot_exit, quantity) or not _full(perp_exit, quantity):
            self._record_runner_incident(
                db,
                study,
                now,
                severity="warning",
                code="HL_CARRY_RISK_EXIT_NOT_EXECUTABLE",
                message=(
                    f"full executable liquidation was unavailable while checking "
                    f"planned loss for position {position.id}"
                ),
                data_integrity=False,
            )
            return False

        observed_at = max(
            _aware(spot_order.market_data_at), _aware(perp_order.market_data_at)
        )
        funding = self._funding_pnl_checked(
            db, position, observed_at, config=config
        )
        current_perp_mid = perp.mid_px or perp.mark_px
        gross = (
            quantity * (spot.mid_px - Decimal(position.entry_spot_mid))
            + quantity * (Decimal(position.entry_perp_mid) - current_perp_mid)
            + funding
        )
        exit_slippage = _adverse_slippage(
            "sell",
            mid=spot.mid_px,
            fill=Decimal(spot_exit.average_price),
            quantity=quantity,
        ) + _adverse_slippage(
            "buy",
            mid=current_perp_mid,
            fill=Decimal(perp_exit.average_price),
            quantity=quantity,
        )
        fees = (
            Decimal(position.entry_spot_fee_usd)
            + Decimal(position.entry_perp_fee_usd)
            + _fee(spot_exit)
            + _fee(perp_exit)
        )
        slippage = (
            Decimal(position.entry_spot_slippage_usd)
            + Decimal(position.entry_perp_slippage_usd)
            + exit_slippage
        )
        net = gross - fees - slippage
        return net <= -Decimal(position.planned_loss_usd)

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
        await self._refresh_funding(db, position, through=now)
        try:
            await super()._record_open_nav_if_due(
                db, study, position, perp, spot, config, now
            )
        except CarryRunnerError as exc:
            if "oracle snapshot" in str(exc):
                raise CarryDataIntegrityError(str(exc)) from exc
            raise

    async def _attempt_close_reasoned(
        self,
        db: Session,
        study: ForwardStudy,
        position: HyperliquidCarryPosition,
        perp: PerpContext,
        spot: SpotContext,
        config: CarryStudyConfig,
        now: datetime,
        *,
        close_reason: str,
    ) -> TickResult:
        bucket = _hour_bucket(now)
        attempt_key = f"hlcarry:exit:{position.id}:{bucket.isoformat()}"
        if self._execution_attempt_exists(db, study.id, attempt_key):
            return TickResult(study.id, "exit_already_attempted", attempt_key)

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
        await self._refresh_funding(db, position, through=close_at)
        exit_spot_price = Decimal(capture.spot.paper.average_price)
        exit_perp_price = Decimal(capture.perp.paper.average_price)
        exit_spot_mid = spot.mid_px
        exit_perp_mid = perp.mid_px or perp.mark_px
        funding_pnl = self._funding_pnl_checked(
            db, position, close_at, config=config
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
                    "close_reason": close_reason,
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
        position.exit_spot_fee_usd = _fee(capture.spot.paper)
        position.exit_perp_fee_usd = _fee(capture.perp.paper)
        position.exit_spot_slippage_usd = exit_spot_slippage
        position.exit_perp_slippage_usd = exit_perp_slippage
        position.funding_pnl_usd = funding_pnl
        position.gross_pnl_usd = gross_pnl
        position.fees_usd = fees
        position.slippage_usd = slippage
        position.net_pnl_usd = net_pnl
        position.close_reason = close_reason
        db.commit()
        return TickResult(
            study.id,
            "closed",
            f"closed {position.coin} carry reason={close_reason} net_pnl={net_pnl}",
        )
