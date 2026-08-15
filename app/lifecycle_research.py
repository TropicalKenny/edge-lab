from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lifecycle_models import (
    LifecycleDecisionOutcome,
    LifecycleObservation,
    LifecyclePolicyDecision,
    LifecyclePolicyState,
)

ZERO = Decimal("0")
ONE = Decimal("1")
POLICY_VERSION = "m6h-v1"
OUTCOME_HORIZONS_MINUTES = (5, 15, 30, 60, 180)


class LifecycleResearchError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class LifecyclePolicy:
    name: str
    take_profit_pct: Decimal
    trailing_drawdown_pct: Decimal
    abandon_loss_pct: Decimal
    reentry_retracement_pct: Decimal
    reentry_min_momentum: Decimal
    reentry_min_volume_acceleration: Decimal
    reentry_max_sell_ratio: Decimal
    reentry_min_liquidity_ratio: Decimal
    max_quote_price_impact_pct: Decimal
    max_reentry_age_minutes: int

    def public_dict(self) -> dict[str, Any]:
        return {"version": POLICY_VERSION, **asdict(self)}


CANDIDATE_POLICIES = (
    LifecyclePolicy(
        name="tp30-rebuy15",
        take_profit_pct=Decimal("0.30"),
        trailing_drawdown_pct=Decimal("0.18"),
        abandon_loss_pct=Decimal("0.35"),
        reentry_retracement_pct=Decimal("0.15"),
        reentry_min_momentum=ZERO,
        reentry_min_volume_acceleration=Decimal("1.00"),
        reentry_max_sell_ratio=Decimal("0.60"),
        reentry_min_liquidity_ratio=Decimal("0.70"),
        max_quote_price_impact_pct=Decimal("0.05"),
        max_reentry_age_minutes=360,
    ),
    LifecyclePolicy(
        name="tp50-rebuy20",
        take_profit_pct=Decimal("0.50"),
        trailing_drawdown_pct=Decimal("0.20"),
        abandon_loss_pct=Decimal("0.40"),
        reentry_retracement_pct=Decimal("0.20"),
        reentry_min_momentum=ZERO,
        reentry_min_volume_acceleration=Decimal("1.00"),
        reentry_max_sell_ratio=Decimal("0.55"),
        reentry_min_liquidity_ratio=Decimal("0.75"),
        max_quote_price_impact_pct=Decimal("0.05"),
        max_reentry_age_minutes=360,
    ),
    LifecyclePolicy(
        name="tp80-rebuy25",
        take_profit_pct=Decimal("0.80"),
        trailing_drawdown_pct=Decimal("0.25"),
        abandon_loss_pct=Decimal("0.45"),
        reentry_retracement_pct=Decimal("0.25"),
        reentry_min_momentum=ZERO,
        reentry_min_volume_acceleration=Decimal("1.00"),
        reentry_max_sell_ratio=Decimal("0.55"),
        reentry_min_liquidity_ratio=Decimal("0.80"),
        max_quote_price_impact_pct=Decimal("0.05"),
        max_reentry_age_minutes=360,
    ),
)


@dataclass(frozen=True)
class LifecycleSnapshot:
    state: str
    observed_at: datetime
    current_value_usd: Decimal | None
    virtual_entry_value_usd: Decimal | None
    virtual_exit_value_usd: Decimal | None
    virtual_exit_at: datetime | None
    peak_return_pct: Decimal
    mark_quote_available: bool
    mark_price_impact_pct: Decimal | None
    reentry_quote_available: bool
    reentry_price_impact_pct: Decimal | None
    liquidity_usd: Decimal | None
    baseline_entry_liquidity_usd: Decimal | None
    momentum_score: Decimal | None
    volume_acceleration: Decimal | None
    sell_ratio_5m: Decimal | None
    security_clean: bool | None

    @property
    def return_from_entry_pct(self) -> Decimal | None:
        if (
            self.current_value_usd is None
            or self.virtual_entry_value_usd is None
            or self.virtual_entry_value_usd <= ZERO
        ):
            return None
        return self.current_value_usd / self.virtual_entry_value_usd - ONE

    @property
    def drawdown_from_peak_pct(self) -> Decimal | None:
        current = self.return_from_entry_pct
        if current is None:
            return None
        peak_value = ONE + max(self.peak_return_pct, current)
        current_value = ONE + current
        if peak_value <= ZERO:
            return None
        return max(ZERO, (peak_value - current_value) / peak_value)

    @property
    def retracement_from_exit_pct(self) -> Decimal | None:
        if (
            self.current_value_usd is None
            or self.virtual_exit_value_usd is None
            or self.virtual_exit_value_usd <= ZERO
        ):
            return None
        return (self.virtual_exit_value_usd - self.current_value_usd) / self.virtual_exit_value_usd

    @property
    def liquidity_ratio(self) -> Decimal | None:
        if (
            self.liquidity_usd is None
            or self.baseline_entry_liquidity_usd is None
            or self.baseline_entry_liquidity_usd <= ZERO
        ):
            return None
        return self.liquidity_usd / self.baseline_entry_liquidity_usd


@dataclass(frozen=True)
class LifecycleDecision:
    action: str
    reasons: tuple[str, ...]


class LifecycleDecisionEngine:
    @staticmethod
    def evaluate(snapshot: LifecycleSnapshot, policy: LifecyclePolicy) -> LifecycleDecision:
        reasons: list[str] = []
        if snapshot.state == "abandoned":
            return LifecycleDecision("ABANDON", ("POLICY_ALREADY_ABANDONED",))

        if snapshot.security_clean is False:
            return LifecycleDecision("ABANDON", ("SECURITY_DETERIORATED",))

        if snapshot.state == "invested":
            current_return = snapshot.return_from_entry_pct
            if (
                not snapshot.mark_quote_available
                or snapshot.current_value_usd is None
                or current_return is None
            ):
                return LifecycleDecision("HOLD", ("EXECUTABLE_EXIT_MARK_UNAVAILABLE",))
            if (
                snapshot.mark_price_impact_pct is None
                or abs(snapshot.mark_price_impact_pct) > policy.max_quote_price_impact_pct
            ):
                return LifecycleDecision("HOLD", ("EXIT_PRICE_IMPACT_TOO_HIGH_OR_UNKNOWN",))
            if current_return <= -policy.abandon_loss_pct:
                return LifecycleDecision("ABANDON", ("LOSS_INVALIDATION_REACHED",))
            if current_return >= policy.take_profit_pct:
                return LifecycleDecision("TAKE_PROFIT", ("TAKE_PROFIT_THRESHOLD_REACHED",))
            drawdown = snapshot.drawdown_from_peak_pct
            if (
                snapshot.peak_return_pct > ZERO
                and drawdown is not None
                and drawdown >= policy.trailing_drawdown_pct
            ):
                return LifecycleDecision("TAKE_PROFIT", ("TRAILING_DRAWDOWN_THRESHOLD_REACHED",))
            return LifecycleDecision("HOLD", ("POSITION_EDGE_NOT_INVALIDATED",))

        if snapshot.state != "cash":
            raise LifecycleResearchError(f"unsupported lifecycle policy state: {snapshot.state}")

        if snapshot.virtual_exit_at is None:
            return LifecycleDecision("WAIT", ("EXIT_TIMESTAMP_UNAVAILABLE",))
        exit_age = _aware(snapshot.observed_at) - _aware(snapshot.virtual_exit_at)
        if exit_age > timedelta(minutes=policy.max_reentry_age_minutes):
            return LifecycleDecision("ABANDON", ("REENTRY_WINDOW_EXPIRED",))
        if (
            not snapshot.mark_quote_available
            or not snapshot.reentry_quote_available
            or snapshot.current_value_usd is None
        ):
            return LifecycleDecision("WAIT", ("REENTRY_QUOTES_UNAVAILABLE",))
        if (
            snapshot.reentry_price_impact_pct is None
            or abs(snapshot.reentry_price_impact_pct) > policy.max_quote_price_impact_pct
        ):
            return LifecycleDecision("WAIT", ("REENTRY_PRICE_IMPACT_TOO_HIGH_OR_UNKNOWN",))

        retracement = snapshot.retracement_from_exit_pct
        if retracement is None or retracement < policy.reentry_retracement_pct:
            return LifecycleDecision("WAIT", ("PULLBACK_NOT_DEEP_ENOUGH",))

        if snapshot.security_clean is not True:
            reasons.append("SECURITY_CONFIRMATION_MISSING")

        liquidity_ratio = snapshot.liquidity_ratio
        if (
            liquidity_ratio is None
            or liquidity_ratio < policy.reentry_min_liquidity_ratio
        ):
            reasons.append("LIQUIDITY_CONFIRMATION_FAILED")
        if (
            snapshot.momentum_score is None
            or snapshot.momentum_score < policy.reentry_min_momentum
        ):
            reasons.append("MOMENTUM_CONFIRMATION_FAILED")
        if (
            snapshot.volume_acceleration is None
            or snapshot.volume_acceleration < policy.reentry_min_volume_acceleration
        ):
            reasons.append("VOLUME_CONFIRMATION_FAILED")
        if (
            snapshot.sell_ratio_5m is None
            or snapshot.sell_ratio_5m > policy.reentry_max_sell_ratio
        ):
            reasons.append("SELL_PRESSURE_CONFIRMATION_FAILED")
        if reasons:
            return LifecycleDecision("WAIT", tuple(reasons))
        return LifecycleDecision("REENTER", ("PULLBACK_AND_STRUCTURE_CONFIRMED",))


class LifecycleResearchService:
    @staticmethod
    def record_observation(
        db: Session,
        *,
        study_id: str,
        position_key: str,
        asset_id: str,
        venue: str,
        baseline_state: str,
        observed_at: datetime,
        baseline_entry_at: datetime,
        baseline_exit_at: datetime | None,
        baseline_entry_value_usd: Decimal,
        baseline_exit_value_usd: Decimal | None,
        current_value_usd: Decimal | None,
        mark_quote_available: bool,
        mark_price_impact_pct: Decimal | None,
        reentry_quote_available: bool,
        reentry_price_impact_pct: Decimal | None,
        liquidity_usd: Decimal | None,
        baseline_entry_liquidity_usd: Decimal | None,
        momentum_score: Decimal | None,
        sell_ratio_5m: Decimal | None,
        volume_acceleration: Decimal | None,
        security_clean: bool | None,
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleObservation:
        observed_at = _aware(observed_at)
        existing = db.scalar(
            select(LifecycleObservation).where(
                LifecycleObservation.study_id == study_id,
                LifecycleObservation.position_key == position_key,
                LifecycleObservation.observed_at == observed_at,
            )
        )
        if existing is not None:
            return existing
        if baseline_entry_value_usd <= ZERO:
            raise LifecycleResearchError("baseline entry value must be positive")
        row = LifecycleObservation(
            study_id=study_id,
            position_key=position_key,
            asset_id=asset_id,
            venue=venue,
            baseline_state=baseline_state,
            observed_at=observed_at,
            baseline_entry_at=_aware(baseline_entry_at),
            baseline_exit_at=_aware(baseline_exit_at) if baseline_exit_at else None,
            baseline_entry_value_usd=baseline_entry_value_usd,
            baseline_exit_value_usd=baseline_exit_value_usd,
            current_value_usd=current_value_usd,
            mark_quote_available=mark_quote_available,
            mark_price_impact_pct=mark_price_impact_pct,
            reentry_quote_available=reentry_quote_available,
            reentry_price_impact_pct=reentry_price_impact_pct,
            liquidity_usd=liquidity_usd,
            baseline_entry_liquidity_usd=baseline_entry_liquidity_usd,
            momentum_score=momentum_score,
            sell_ratio_5m=sell_ratio_5m,
            volume_acceleration=volume_acceleration,
            security_clean=security_clean,
            metadata_json=_json(metadata or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def _state_for_policy(
        db: Session,
        observation: LifecycleObservation,
        policy: LifecyclePolicy,
    ) -> LifecyclePolicyState | None:
        state = db.scalar(
            select(LifecyclePolicyState).where(
                LifecyclePolicyState.study_id == observation.study_id,
                LifecyclePolicyState.position_key == observation.position_key,
                LifecyclePolicyState.policy_name == policy.name,
                LifecyclePolicyState.policy_version == POLICY_VERSION,
            )
        )
        if state is not None:
            return state
        if observation.baseline_state != "invested":
            return None
        state = LifecyclePolicyState(
            study_id=observation.study_id,
            position_key=observation.position_key,
            policy_name=policy.name,
            policy_version=POLICY_VERSION,
            state="invested",
            virtual_entry_value_usd=observation.baseline_entry_value_usd,
            virtual_exit_value_usd=None,
            virtual_entry_at=observation.baseline_entry_at,
            virtual_exit_at=None,
            peak_return_pct=ZERO,
            cycle_count=0,
            last_action="ENTER",
            updated_at=observation.observed_at,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
        return state

    @staticmethod
    def _snapshot(
        observation: LifecycleObservation,
        state: LifecyclePolicyState,
    ) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            state=state.state,
            observed_at=observation.observed_at,
            current_value_usd=(
                Decimal(observation.current_value_usd)
                if observation.current_value_usd is not None
                else None
            ),
            virtual_entry_value_usd=(
                Decimal(state.virtual_entry_value_usd)
                if state.virtual_entry_value_usd is not None
                else None
            ),
            virtual_exit_value_usd=(
                Decimal(state.virtual_exit_value_usd)
                if state.virtual_exit_value_usd is not None
                else None
            ),
            virtual_exit_at=state.virtual_exit_at,
            peak_return_pct=Decimal(state.peak_return_pct or 0),
            mark_quote_available=bool(observation.mark_quote_available),
            mark_price_impact_pct=(
                Decimal(observation.mark_price_impact_pct)
                if observation.mark_price_impact_pct is not None
                else None
            ),
            reentry_quote_available=bool(observation.reentry_quote_available),
            reentry_price_impact_pct=(
                Decimal(observation.reentry_price_impact_pct)
                if observation.reentry_price_impact_pct is not None
                else None
            ),
            liquidity_usd=(
                Decimal(observation.liquidity_usd)
                if observation.liquidity_usd is not None
                else None
            ),
            baseline_entry_liquidity_usd=(
                Decimal(observation.baseline_entry_liquidity_usd)
                if observation.baseline_entry_liquidity_usd is not None
                else None
            ),
            momentum_score=(
                Decimal(observation.momentum_score)
                if observation.momentum_score is not None
                else None
            ),
            volume_acceleration=(
                Decimal(observation.volume_acceleration)
                if observation.volume_acceleration is not None
                else None
            ),
            sell_ratio_5m=(
                Decimal(observation.sell_ratio_5m)
                if observation.sell_ratio_5m is not None
                else None
            ),
            security_clean=observation.security_clean,
        )

    @classmethod
    def evaluate_observation(
        cls,
        db: Session,
        observation: LifecycleObservation,
    ) -> list[LifecyclePolicyDecision]:
        rows: list[LifecyclePolicyDecision] = []
        for policy in CANDIDATE_POLICIES:
            existing = db.scalar(
                select(LifecyclePolicyDecision).where(
                    LifecyclePolicyDecision.observation_id == observation.id,
                    LifecyclePolicyDecision.policy_name == policy.name,
                    LifecyclePolicyDecision.policy_version == POLICY_VERSION,
                )
            )
            if existing is not None:
                rows.append(existing)
                continue

            state = cls._state_for_policy(db, observation, policy)
            if state is None:
                continue

            snapshot = cls._snapshot(observation, state)
            current_return = snapshot.return_from_entry_pct
            if state.state == "invested" and current_return is not None:
                state.peak_return_pct = max(
                    Decimal(state.peak_return_pct or 0), current_return
                )
                snapshot = cls._snapshot(observation, state)

            decision = LifecycleDecisionEngine.evaluate(snapshot, policy)
            state_before = state.state
            state_after = state_before
            current_value = snapshot.current_value_usd

            if decision.action == "TAKE_PROFIT" and current_value is not None:
                state_after = "cash"
                state.state = state_after
                state.virtual_exit_value_usd = current_value
                state.virtual_exit_at = observation.observed_at
                state.last_action = decision.action
            elif decision.action == "REENTER" and current_value is not None:
                state_after = "invested"
                state.state = state_after
                state.virtual_entry_value_usd = current_value
                state.virtual_entry_at = observation.observed_at
                state.virtual_exit_value_usd = None
                state.virtual_exit_at = None
                state.peak_return_pct = ZERO
                state.cycle_count += 1
                state.last_action = decision.action
            elif decision.action == "ABANDON":
                state_after = "abandoned"
                state.state = state_after
                state.last_action = decision.action
            else:
                state.last_action = decision.action
            state.updated_at = observation.observed_at

            rationale = {
                "reasons": list(decision.reasons),
                "policy": policy.public_dict(),
                "baseline_state": observation.baseline_state,
                "virtual_state_before": state_before,
                "return_from_virtual_entry_pct": (
                    str(snapshot.return_from_entry_pct)
                    if snapshot.return_from_entry_pct is not None
                    else None
                ),
                "drawdown_from_virtual_peak_pct": (
                    str(snapshot.drawdown_from_peak_pct)
                    if snapshot.drawdown_from_peak_pct is not None
                    else None
                ),
                "retracement_from_virtual_exit_pct": (
                    str(snapshot.retracement_from_exit_pct)
                    if snapshot.retracement_from_exit_pct is not None
                    else None
                ),
                "liquidity_ratio_to_baseline_entry": (
                    str(snapshot.liquidity_ratio)
                    if snapshot.liquidity_ratio is not None
                    else None
                ),
                "lookahead_used": False,
                "baseline_mutated": False,
            }
            row = LifecyclePolicyDecision(
                observation_id=observation.id,
                study_id=observation.study_id,
                position_key=observation.position_key,
                policy_name=policy.name,
                policy_version=POLICY_VERSION,
                state_before=state_before,
                action=decision.action,
                state_after=state_after,
                rationale_json=_json(rationale),
                can_execute=False,
                decided_at=observation.observed_at,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            db.refresh(state)
            rows.append(row)
        return rows

    @staticmethod
    def resolve_outcomes(
        db: Session,
        *,
        now: datetime | None = None,
    ) -> int:
        now = _aware(now or datetime.now(timezone.utc))
        decisions = db.scalars(
            select(LifecyclePolicyDecision).order_by(
                LifecyclePolicyDecision.decided_at.asc()
            )
        ).all()
        created = 0
        for decision in decisions:
            origin = db.get(LifecycleObservation, decision.observation_id)
            if origin is None or origin.current_value_usd is None:
                continue
            origin_value = Decimal(origin.current_value_usd)
            if origin_value <= ZERO:
                continue
            for horizon in OUTCOME_HORIZONS_MINUTES:
                target_at = _aware(decision.decided_at) + timedelta(minutes=horizon)
                if target_at > now:
                    continue
                exists = db.scalar(
                    select(LifecycleDecisionOutcome.id).where(
                        LifecycleDecisionOutcome.decision_id == decision.id,
                        LifecycleDecisionOutcome.horizon_minutes == horizon,
                    )
                )
                if exists:
                    continue
                future = db.scalar(
                    select(LifecycleObservation)
                    .where(
                        LifecycleObservation.study_id == decision.study_id,
                        LifecycleObservation.position_key == decision.position_key,
                        LifecycleObservation.observed_at >= target_at,
                        LifecycleObservation.current_value_usd.is_not(None),
                    )
                    .order_by(LifecycleObservation.observed_at.asc())
                    .limit(1)
                )
                if future is None or future.current_value_usd is None:
                    continue
                path = db.scalars(
                    select(LifecycleObservation)
                    .where(
                        LifecycleObservation.study_id == decision.study_id,
                        LifecycleObservation.position_key == decision.position_key,
                        LifecycleObservation.observed_at > decision.decided_at,
                        LifecycleObservation.observed_at <= future.observed_at,
                        LifecycleObservation.current_value_usd.is_not(None),
                    )
                    .order_by(LifecycleObservation.observed_at.asc())
                ).all()
                path_returns = [
                    Decimal(item.current_value_usd) / origin_value - ONE
                    for item in path
                    if item.current_value_usd is not None
                ]
                future_return = Decimal(future.current_value_usd) / origin_value - ONE
                row = LifecycleDecisionOutcome(
                    decision_id=decision.id,
                    horizon_minutes=horizon,
                    resolved_at=future.observed_at,
                    future_value_usd=Decimal(future.current_value_usd),
                    future_return_pct=future_return,
                    max_favorable_move_pct=max(path_returns) if path_returns else future_return,
                    max_adverse_move_pct=min(path_returns) if path_returns else future_return,
                    metadata_json=_json(
                        {
                            "evaluation": "counterfactual-market-movement-only",
                            "lookahead_used_for_decision": False,
                            "policy_action": decision.action,
                        }
                    ),
                )
                db.add(row)
                db.commit()
                created += 1
        return created
