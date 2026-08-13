from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy
from app.hyperliquid_forward import (
    CarryStudyConfig,
    HyperliquidCarryForwardRunner,
    HyperliquidForwardError,
    _aware,
    _fee,
    _filled,
    _slippage,
)
from app.hyperliquid_forward_models import HyperliquidCarryPosition
from app.hyperliquid_forward_safe import SafeHyperliquidCarryForwardRunner

ZERO = Decimal("0")


class StrictHyperliquidCarryForwardRunner(SafeHyperliquidCarryForwardRunner):
    """Capital-safe carry runner with fail-closed funding NAV and planned-loss exits."""

    async def _refresh_funding_for_position(
        self,
        db: Session,
        position: HyperliquidCarryPosition,
        *,
        cutoff: datetime,
        config: CarryStudyConfig,
    ):
        cutoff = _aware(cutoff)
        elapsed = cutoff - _aware(position.opened_at)
        # Refresh settled funding whenever the position has crossed an hourly
        # boundary. Two hours is the conservative point at which at least one
        # settlement should exist regardless of the entry minute.
        if elapsed >= timedelta(hours=1):
            hours = max(2, int(elapsed.total_seconds() // 3600) + 2)
            await self.service.funding_history(db, coin=position.coin, hours=hours, persist=True)
        funding = self._funding(db, position, cutoff, config)
        if funding.missing_mark_times:
            self._integrity_incident(
                db,
                position,
                "FUNDING_MARK_MISSING",
                f"{len(funding.missing_mark_times)} settled funding rows lack a nearby persisted mark",
                cutoff,
            )
            return None
        if elapsed >= timedelta(hours=2) and funding.settlement_count == 0:
            self._integrity_incident(
                db,
                position,
                "FUNDING_HISTORY_MISSING",
                "no settled funding rows found after two hours of carry exposure",
                cutoff,
            )
            return None
        return funding

    async def maybe_nav(
        self,
        db: Session,
        study: ForwardStudy,
        config: CarryStudyConfig,
        now: datetime,
    ) -> bool:
        position = self._open_position(db, study.id)
        if position is not None:
            # Persist a current mark before funding reconstruction and explicitly
            # refresh funding. The base NAV path then uses the same persisted facts.
            await self._state(db, study, config)
            funding = await self._refresh_funding_for_position(
                db,
                position,
                cutoff=now,
                config=config,
            )
            if funding is None:
                return False
        return await super().maybe_nav(db, study, config, now)

    async def maybe_planned_loss_close(
        self,
        db: Session,
        study: ForwardStudy,
        position: HyperliquidCarryPosition,
        config: CarryStudyConfig,
        now: datetime,
    ) -> bool:
        if position.status != "open":
            return False
        await self._state(db, study, config)
        funding = await self._refresh_funding_for_position(
            db,
            position,
            cutoff=now,
            config=config,
        )
        if funding is None:
            return False

        state = await self._state(db, study, config)
        spot, perp = await self._exit_books(position, config)
        quantity = Decimal(position.quantity)
        if not _filled(spot, quantity) or not _filled(perp, quantity):
            self._integrity_incident(
                db,
                position,
                "RISK_EXIT_LIQUIDITY_UNAVAILABLE",
                "full executable liquidation was unavailable while evaluating the planned-loss limit",
                now,
            )
            return False

        exit_spot_price = Decimal(spot.average_price)
        exit_perp_price = Decimal(perp.average_price)
        spot_gross = (state.spot_mark - Decimal(position.entry_spot_mid)) * quantity
        perp_gross = (Decimal(position.entry_perp_mid) - state.perp_mark) * quantity
        gross = spot_gross + perp_gross + funding.pnl_usd
        exit_spot_slippage = _slippage("sell", exit_spot_price, state.spot_mark, quantity)
        exit_perp_slippage = _slippage("buy", exit_perp_price, state.perp_mark, quantity)
        fees = (
            Decimal(position.entry_spot_fee_usd)
            + Decimal(position.entry_perp_fee_usd)
            + _fee(spot)
            + _fee(perp)
        )
        slippage = (
            Decimal(position.entry_spot_slippage_usd)
            + Decimal(position.entry_perp_slippage_usd)
            + exit_spot_slippage
            + exit_perp_slippage
        )
        net = gross - fees - slippage
        if net > -Decimal(position.planned_loss_usd):
            return False

        position.exit_spot_mid = state.spot_mark
        position.exit_perp_mid = state.perp_mark
        position.exit_spot_price = exit_spot_price
        position.exit_perp_price = exit_perp_price
        position.exit_spot_fee_usd = _fee(spot)
        position.exit_perp_fee_usd = _fee(perp)
        position.exit_spot_slippage_usd = exit_spot_slippage
        position.exit_perp_slippage_usd = exit_perp_slippage
        position.funding_pnl_usd = funding.pnl_usd
        position.gross_pnl_usd = gross
        position.fees_usd = fees
        position.slippage_usd = slippage
        position.net_pnl_usd = net
        position.closed_at = _aware(now)
        position.status = "closed"
        position.close_reason = "planned-loss"
        db.commit()

        await self._exit_shadow(db, position, config)
        self._ensure_closed_evidence(db, position)
        return True

    async def run_study_cycle(
        self,
        db: Session,
        study: ForwardStudy,
        *,
        now: datetime | None = None,
    ) -> dict[str, bool]:
        now = _aware(now or datetime.now(timezone.utc))
        if study.status != "active" or study.family != "funding" or study.venue != "hyperliquid":
            raise HyperliquidForwardError("study is not an active Hyperliquid funding study")
        config = CarryStudyConfig.from_json(study.study_config_json)
        self.validate_study_capital(study, config)

        position = self._open_position(db, study.id)
        opened = False
        closed = False
        if position is None:
            position = await self.maybe_open(db, study, config, now)
            opened = position is not None
        elif position.entry_shadow_observed_at is None:
            await self._entry_shadow(db, position, config)
        else:
            self._ensure_entry_evidence(db, position)

        if position is not None and position.status == "open":
            closed = await self.maybe_planned_loss_close(db, study, position, config, now)
            if not closed and position.status == "open":
                closed = await self.maybe_close(db, study, position, config, now)

        nav_recorded = await self.maybe_nav(db, study, config, now)
        return {"opened": opened, "closed": closed, "nav_recorded": nav_recorded}
