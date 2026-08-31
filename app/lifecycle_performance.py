from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lifecycle_models import (
    LifecycleObservation,
    LifecyclePerformanceSnapshot,
    LifecyclePolicyCycle,
    LifecyclePolicyDecision,
)

ZERO = Decimal(0)
ONE = Decimal(1)
BPS = Decimal(10000)
ACCOUNTING_VERSION = "m6h-performance-v1"
MIN_POLICY_POSITIONS = 300
MIN_COMPLETED_CYCLES = 300


class LifecyclePerformanceError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _decimal(value: Any) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _return(value: Decimal | None, starting_value: Decimal) -> Decimal | None:
    if value is None or starting_value <= ZERO:
        return None
    return value / starting_value - ONE


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(Decimal(len(ordered) - 1) * percentile)
    return ordered[index]


@dataclass(frozen=True)
class LifecycleCostModel:
    """Frozen extra-cost stress applied on top of executable quote outputs."""

    version: str = ACCOUNTING_VERSION
    additional_slippage_bps: Decimal = Decimal(20)
    fixed_leg_cost_usd: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if self.version != ACCOUNTING_VERSION:
            raise LifecyclePerformanceError("cost model version must match accounting version")
        if self.additional_slippage_bps < ZERO or self.additional_slippage_bps > Decimal(500):
            raise LifecyclePerformanceError("additional slippage must be between 0 and 500 bps")
        if self.fixed_leg_cost_usd < ZERO or self.fixed_leg_cost_usd > Decimal(5):
            raise LifecyclePerformanceError("fixed leg cost must be between $0 and $5")

    @property
    def reserve_rate(self) -> Decimal:
        return self.additional_slippage_bps / BPS

    def extra_leg_cost(self, notional_usd: Decimal) -> Decimal:
        if notional_usd <= ZERO:
            return ZERO
        return min(
            notional_usd,
            notional_usd * self.reserve_rate + self.fixed_leg_cost_usd,
        )

    def public_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "additional_slippage_bps": str(self.additional_slippage_bps),
            "fixed_leg_cost_usd": str(self.fixed_leg_cost_usd),
            "quote_output_already_includes_quote_deterioration": "true",
        }


@dataclass
class _ReplayState:
    state: str
    token_units: Decimal
    cash_balance_usd: Decimal | None
    starting_value_usd: Decimal
    last_at: datetime
    cumulative_cost_usd: Decimal
    round_trip_count: int
    time_invested_seconds: int
    time_in_cash_seconds: int
    max_favorable_return_pct: Decimal | None
    max_adverse_return_pct: Decimal | None
    hold_max_favorable_return_pct: Decimal | None
    hold_max_adverse_return_pct: Decimal | None
    cycle_index: int
    cycle_entry_decision_id: str | None
    cycle_entry_at: datetime | None
    cycle_entry_value_usd: Decimal | None
    cycle_cost_usd: Decimal
    cycle_mfe_pct: Decimal | None
    cycle_mae_pct: Decimal | None
    cycle_invested_seconds: int
    failed_reentry_count: int
    missed_recovery_count: int
    cash_reference_hold_value_usd: Decimal | None
    cash_max_hold_value_usd: Decimal | None
    cash_interval_missed_recovery: bool
    complete: bool


@dataclass(frozen=True)
class LifecyclePolicySummary:
    study_id: str
    policy_name: str
    policy_version: str
    accounting_version: str
    position_count: int
    complete_position_count: int
    completed_cycle_count: int
    round_trip_count: int
    failed_reentry_count: int
    missed_recovery_count: int
    mean_net_return_pct: Decimal | None
    mean_hold_return_pct: Decimal | None
    mean_excess_return_pct: Decimal | None
    tail_loss_p05_pct: Decimal | None
    worst_return_pct: Decimal | None
    cost_drag_pct: Decimal | None
    invested_time_ratio: Decimal | None
    sample_sufficient: bool
    selection_status: str
    can_promote: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
        }


class LifecyclePerformanceService:
    """Versioned, deterministic replay accounting for non-executable M6H policies."""

    @staticmethod
    def _initial_state(
        observation: LifecycleObservation,
        decision: LifecyclePolicyDecision,
    ) -> _ReplayState:
        starting_value = Decimal(observation.baseline_entry_value_usd)
        if starting_value <= ZERO:
            raise LifecyclePerformanceError("lifecycle starting value must be positive")
        if decision.state_before != "invested":
            raise LifecyclePerformanceError("first lifecycle decision must begin invested")
        baseline_entry_at = _aware(observation.baseline_entry_at)
        if baseline_entry_at > _aware(observation.observed_at):
            raise LifecyclePerformanceError("baseline entry cannot be after observation")
        return _ReplayState(
            state="invested",
            token_units=ONE,
            cash_balance_usd=None,
            starting_value_usd=starting_value,
            last_at=baseline_entry_at,
            cumulative_cost_usd=ZERO,
            round_trip_count=0,
            time_invested_seconds=0,
            time_in_cash_seconds=0,
            max_favorable_return_pct=ZERO,
            max_adverse_return_pct=ZERO,
            hold_max_favorable_return_pct=ZERO,
            hold_max_adverse_return_pct=ZERO,
            cycle_index=0,
            cycle_entry_decision_id=None,
            cycle_entry_at=baseline_entry_at,
            cycle_entry_value_usd=starting_value,
            cycle_cost_usd=ZERO,
            cycle_mfe_pct=ZERO,
            cycle_mae_pct=ZERO,
            cycle_invested_seconds=0,
            failed_reentry_count=0,
            missed_recovery_count=0,
            cash_reference_hold_value_usd=None,
            cash_max_hold_value_usd=None,
            cash_interval_missed_recovery=False,
            complete=True,
        )

    @staticmethod
    def _state_from_snapshot(row: LifecyclePerformanceSnapshot) -> _ReplayState:
        return _ReplayState(
            state=row.state_after,
            token_units=Decimal(row.token_units),
            cash_balance_usd=_decimal(row.cash_balance_usd),
            starting_value_usd=Decimal(row.starting_value_usd),
            last_at=_aware(row.observed_at),
            cumulative_cost_usd=Decimal(row.cumulative_cost_usd),
            round_trip_count=row.round_trip_count,
            time_invested_seconds=row.time_invested_seconds,
            time_in_cash_seconds=row.time_in_cash_seconds,
            max_favorable_return_pct=_decimal(row.max_favorable_return_pct),
            max_adverse_return_pct=_decimal(row.max_adverse_return_pct),
            hold_max_favorable_return_pct=_decimal(row.hold_max_favorable_return_pct),
            hold_max_adverse_return_pct=_decimal(row.hold_max_adverse_return_pct),
            cycle_index=row.cycle_index,
            cycle_entry_decision_id=row.cycle_entry_decision_id,
            cycle_entry_at=_aware(row.cycle_entry_at) if row.cycle_entry_at else None,
            cycle_entry_value_usd=_decimal(row.cycle_entry_value_usd),
            cycle_cost_usd=Decimal(row.cycle_cost_usd),
            cycle_mfe_pct=_decimal(row.cycle_mfe_pct),
            cycle_mae_pct=_decimal(row.cycle_mae_pct),
            cycle_invested_seconds=row.cycle_invested_seconds,
            failed_reentry_count=row.failed_reentry_count,
            missed_recovery_count=row.missed_recovery_count,
            cash_reference_hold_value_usd=_decimal(row.cash_reference_hold_value_usd),
            cash_max_hold_value_usd=_decimal(row.cash_max_hold_value_usd),
            cash_interval_missed_recovery=row.cash_interval_missed_recovery,
            complete=row.complete,
        )

    @staticmethod
    def _quote_deterioration(
        input_value_usd: Decimal | None,
        output_value_usd: Decimal | None,
        scale: Decimal,
    ) -> tuple[Decimal, bool]:
        if input_value_usd is None or output_value_usd is None:
            return ZERO, False
        if input_value_usd <= ZERO or output_value_usd <= ZERO or scale < ZERO:
            return ZERO, False
        return max(ZERO, input_value_usd - output_value_usd) * scale, True

    @staticmethod
    def _hold_mark(
        observation: LifecycleObservation,
        cost_model: LifecycleCostModel,
    ) -> tuple[Decimal | None, bool]:
        if not observation.mark_quote_available or observation.current_value_usd is None:
            return None, False
        gross = Decimal(observation.current_value_usd)
        if gross <= ZERO:
            return None, False
        complete = bool(
            observation.mark_input_amount_atomic
            and observation.mark_output_amount_atomic
            and observation.mark_input_value_usd is not None
            and observation.mark_output_value_usd is not None
        )
        return max(ZERO, gross - cost_model.extra_leg_cost(gross)), complete

    @staticmethod
    def _marked_policy_value(
        state: _ReplayState,
        observation: LifecycleObservation,
        cost_model: LifecycleCostModel,
    ) -> tuple[Decimal | None, Decimal | None]:
        if state.state == "invested":
            if not observation.mark_quote_available or observation.current_value_usd is None:
                return None, None
            gross = state.token_units * Decimal(observation.current_value_usd)
            return gross, max(ZERO, gross - cost_model.extra_leg_cost(gross))
        if state.cash_balance_usd is not None:
            return state.cash_balance_usd, state.cash_balance_usd
        return None, None

    @staticmethod
    def _advance_time(state: _ReplayState, observed_at: datetime) -> None:
        observed_at = _aware(observed_at)
        if observed_at < state.last_at:
            raise LifecyclePerformanceError("lifecycle observations must be chronological")
        elapsed = int((observed_at - state.last_at).total_seconds())
        if state.state == "invested":
            state.time_invested_seconds += elapsed
            state.cycle_invested_seconds += elapsed
        elif state.state == "cash":
            state.time_in_cash_seconds += elapsed
        state.last_at = observed_at

    @staticmethod
    def _update_extrema(
        current: Decimal | None,
        favorable: Decimal | None,
        adverse: Decimal | None,
    ) -> tuple[Decimal | None, Decimal | None]:
        if current is None:
            return favorable, adverse
        return (
            current if favorable is None else max(favorable, current),
            current if adverse is None else min(adverse, current),
        )

    @classmethod
    def _record_cycle(
        cls,
        db: Session,
        *,
        state: _ReplayState,
        decision: LifecyclePolicyDecision,
        exit_value_usd: Decimal,
        exit_transaction_cost_usd: Decimal,
    ) -> LifecyclePolicyCycle:
        if state.cycle_entry_at is None or state.cycle_entry_value_usd is None:
            raise LifecyclePerformanceError("cannot close a cycle without an entry")
        entry_value = state.cycle_entry_value_usd
        if entry_value <= ZERO:
            raise LifecyclePerformanceError("cycle entry value must be positive")
        existing = db.scalar(
            select(LifecyclePolicyCycle).where(
                LifecyclePolicyCycle.study_id == decision.study_id,
                LifecyclePolicyCycle.position_key == decision.position_key,
                LifecyclePolicyCycle.policy_name == decision.policy_name,
                LifecyclePolicyCycle.policy_version == decision.policy_version,
                LifecyclePolicyCycle.accounting_version == ACCOUNTING_VERSION,
                LifecyclePolicyCycle.cycle_index == state.cycle_index,
            )
        )
        if existing is not None:
            return existing
        net_pnl = exit_value_usd - entry_value
        net_return = net_pnl / entry_value
        failed_reentry = state.cycle_index > 0 and net_pnl < ZERO
        row = LifecyclePolicyCycle(
            study_id=decision.study_id,
            position_key=decision.position_key,
            policy_name=decision.policy_name,
            policy_version=decision.policy_version,
            accounting_version=ACCOUNTING_VERSION,
            cycle_index=state.cycle_index,
            entry_decision_id=state.cycle_entry_decision_id,
            exit_decision_id=decision.id,
            entered_at=state.cycle_entry_at,
            exited_at=decision.decided_at,
            entered_via="BASELINE" if state.cycle_index == 0 else "REENTER",
            exited_via=decision.action,
            entry_value_usd=entry_value,
            exit_value_usd=exit_value_usd,
            net_pnl_usd=net_pnl,
            net_return_pct=net_return,
            modeled_cost_usd=state.cycle_cost_usd + exit_transaction_cost_usd,
            max_favorable_return_pct=state.cycle_mfe_pct or ZERO,
            max_adverse_return_pct=state.cycle_mae_pct or ZERO,
            invested_seconds=state.cycle_invested_seconds,
            failed_reentry=failed_reentry,
            metadata_json=_json(
                {
                    "milestone": "M6H-performance",
                    "can_execute": False,
                    "lookahead_used_for_decision": False,
                    "hindsight_used_for_scoring": True,
                    "baseline_mutated": False,
                }
            ),
        )
        db.add(row)
        if failed_reentry:
            state.failed_reentry_count += 1
        return row

    @classmethod
    def _apply_decision(
        cls,
        db: Session,
        *,
        state: _ReplayState,
        observation: LifecycleObservation,
        decision: LifecyclePolicyDecision,
        cost_model: LifecycleCostModel,
    ) -> LifecyclePerformanceSnapshot:
        if decision.can_execute:
            raise LifecyclePerformanceError("performance accounting refuses executable decisions")
        if decision.state_before != state.state:
            raise LifecyclePerformanceError(
                f"accounting state {state.state} does not match decision {decision.state_before}"
            )

        cls._advance_time(state, observation.observed_at)
        hold_value, mark_detail_complete = cls._hold_mark(observation, cost_model)
        if state.cash_reference_hold_value_usd is not None and hold_value is not None:
            if state.cash_max_hold_value_usd is None:
                state.cash_max_hold_value_usd = hold_value
            else:
                state.cash_max_hold_value_usd = max(state.cash_max_hold_value_usd, hold_value)
            if (
                not state.cash_interval_missed_recovery
                and state.cash_max_hold_value_usd > state.cash_reference_hold_value_usd
            ):
                state.cash_interval_missed_recovery = True
                state.missed_recovery_count += 1

        gross_before, _ = cls._marked_policy_value(state, observation, cost_model)
        transaction_cost = ZERO
        valuation_method = "executable-quote-detail"
        action_complete = True

        if decision.action in {"TAKE_PROFIT", "ABANDON"} and state.state == "invested":
            if gross_before is None:
                action_complete = False
                valuation_method = "missing-executable-sell-quote"
                state.state = decision.state_after
            else:
                extra_cost = cost_model.extra_leg_cost(gross_before)
                scale = state.token_units
                quote_cost, quote_complete = cls._quote_deterioration(
                    _decimal(observation.mark_input_value_usd),
                    _decimal(observation.mark_output_value_usd),
                    scale,
                )
                transaction_cost = extra_cost + quote_cost
                cash = max(ZERO, gross_before - extra_cost)
                cycle_return = _return(cash, state.cycle_entry_value_usd or ZERO)
                state.cycle_mfe_pct, state.cycle_mae_pct = cls._update_extrema(
                    cycle_return,
                    state.cycle_mfe_pct,
                    state.cycle_mae_pct,
                )
                cls._record_cycle(
                    db,
                    state=state,
                    decision=decision,
                    exit_value_usd=cash,
                    exit_transaction_cost_usd=transaction_cost,
                )
                state.token_units = ZERO
                state.cash_balance_usd = cash
                state.state = decision.state_after
                state.cumulative_cost_usd += transaction_cost
                state.cash_reference_hold_value_usd = hold_value
                state.cash_max_hold_value_usd = hold_value
                state.cash_interval_missed_recovery = False
                state.cycle_entry_decision_id = None
                state.cycle_entry_at = None
                state.cycle_entry_value_usd = None
                state.cycle_cost_usd = ZERO
                state.cycle_mfe_pct = None
                state.cycle_mae_pct = None
                state.cycle_invested_seconds = 0
                action_complete = quote_complete

        elif decision.action == "REENTER" and state.state == "cash":
            cash_before = state.cash_balance_usd
            current_value = _decimal(observation.current_value_usd)
            if cash_before is None or cash_before <= ZERO or current_value is None:
                raise LifecyclePerformanceError("re-entry requires positive cash and a mark")
            extra_cost = cost_model.extra_leg_cost(cash_before)
            investable_cash = max(ZERO, cash_before - extra_cost)
            mark_input_amount = observation.mark_input_amount_atomic
            reentry_output_amount = observation.reentry_output_amount_atomic
            reentry_input_value = _decimal(observation.reentry_input_value_usd)
            reentry_output_value = _decimal(observation.reentry_output_value_usd)
            if (
                mark_input_amount
                and mark_input_amount > 0
                and reentry_output_amount
                and reentry_output_amount > 0
                and reentry_input_value is not None
                and reentry_input_value > ZERO
                and reentry_output_value is not None
                and reentry_output_value > ZERO
            ):
                quote_scale = investable_cash / reentry_input_value
                state.token_units = (
                    Decimal(reentry_output_amount) * quote_scale / Decimal(mark_input_amount)
                )
                quote_cost, quote_complete = cls._quote_deterioration(
                    reentry_input_value,
                    reentry_output_value,
                    quote_scale,
                )
            else:
                impact = abs(_decimal(observation.reentry_price_impact_pct) or ZERO)
                quote_cost = min(investable_cash, investable_cash * impact)
                effective_cash = max(ZERO, investable_cash - quote_cost)
                state.token_units = effective_cash / current_value
                quote_complete = False
                valuation_method = "normalized-value-fallback"
            transaction_cost = extra_cost + quote_cost
            state.cash_balance_usd = None
            state.state = decision.state_after
            state.cumulative_cost_usd += transaction_cost
            state.round_trip_count += 1
            state.cycle_index += 1
            state.cycle_entry_decision_id = decision.id
            state.cycle_entry_at = _aware(decision.decided_at)
            state.cycle_entry_value_usd = cash_before
            state.cycle_cost_usd = transaction_cost
            state.cycle_mfe_pct = ZERO
            state.cycle_mae_pct = ZERO
            state.cycle_invested_seconds = 0
            state.cash_reference_hold_value_usd = None
            state.cash_max_hold_value_usd = None
            state.cash_interval_missed_recovery = False
            action_complete = quote_complete

        else:
            state.state = decision.state_after

        gross_after, net_value = cls._marked_policy_value(state, observation, cost_model)
        if decision.action in {"TAKE_PROFIT", "ABANDON", "REENTER"}:
            gross_value = gross_before
        else:
            gross_value = gross_after

        net_return = _return(net_value, state.starting_value_usd)
        hold_return = _return(hold_value, state.starting_value_usd)
        excess_return = (
            net_return - hold_return if net_return is not None and hold_return is not None else None
        )
        state.max_favorable_return_pct, state.max_adverse_return_pct = cls._update_extrema(
            net_return,
            state.max_favorable_return_pct,
            state.max_adverse_return_pct,
        )
        (
            state.hold_max_favorable_return_pct,
            state.hold_max_adverse_return_pct,
        ) = cls._update_extrema(
            hold_return,
            state.hold_max_favorable_return_pct,
            state.hold_max_adverse_return_pct,
        )
        if state.state == "invested" and state.cycle_entry_value_usd is not None:
            cycle_return = _return(net_value, state.cycle_entry_value_usd)
            state.cycle_mfe_pct, state.cycle_mae_pct = cls._update_extrema(
                cycle_return,
                state.cycle_mfe_pct,
                state.cycle_mae_pct,
            )

        policy_downside = abs(min(ZERO, state.max_adverse_return_pct or ZERO))
        hold_downside = abs(min(ZERO, state.hold_max_adverse_return_pct or ZERO))
        downside_avoided = max(ZERO, hold_downside - policy_downside)
        downside_incurred = max(ZERO, policy_downside - hold_downside)
        mfe_capture = (
            net_return / state.max_favorable_return_pct
            if net_return is not None
            and state.max_favorable_return_pct is not None
            and state.max_favorable_return_pct > ZERO
            else None
        )
        state.complete = bool(
            state.complete
            and action_complete
            and mark_detail_complete
            and net_value is not None
            and hold_value is not None
        )

        row = LifecyclePerformanceSnapshot(
            observation_id=observation.id,
            decision_id=decision.id,
            study_id=decision.study_id,
            position_key=decision.position_key,
            policy_name=decision.policy_name,
            policy_version=decision.policy_version,
            accounting_version=ACCOUNTING_VERSION,
            observed_at=observation.observed_at,
            state_after=state.state,
            starting_value_usd=state.starting_value_usd,
            token_units=state.token_units,
            cash_balance_usd=state.cash_balance_usd,
            gross_value_usd=gross_value,
            net_value_usd=net_value,
            hold_value_usd=hold_value,
            net_return_pct=net_return,
            hold_return_pct=hold_return,
            excess_return_pct=excess_return,
            transaction_cost_usd=transaction_cost,
            cumulative_cost_usd=state.cumulative_cost_usd,
            cost_drag_pct=state.cumulative_cost_usd / state.starting_value_usd,
            round_trip_count=state.round_trip_count,
            time_invested_seconds=state.time_invested_seconds,
            time_in_cash_seconds=state.time_in_cash_seconds,
            max_favorable_return_pct=state.max_favorable_return_pct,
            max_adverse_return_pct=state.max_adverse_return_pct,
            hold_max_favorable_return_pct=state.hold_max_favorable_return_pct,
            hold_max_adverse_return_pct=state.hold_max_adverse_return_pct,
            mfe_capture_ratio=mfe_capture,
            downside_avoided_pct=downside_avoided,
            downside_incurred_pct=downside_incurred,
            cycle_index=state.cycle_index,
            cycle_entry_decision_id=state.cycle_entry_decision_id,
            cycle_entry_at=state.cycle_entry_at,
            cycle_entry_value_usd=state.cycle_entry_value_usd,
            cycle_cost_usd=state.cycle_cost_usd,
            cycle_mfe_pct=state.cycle_mfe_pct,
            cycle_mae_pct=state.cycle_mae_pct,
            cycle_invested_seconds=state.cycle_invested_seconds,
            failed_reentry_count=state.failed_reentry_count,
            missed_recovery_count=state.missed_recovery_count,
            cash_reference_hold_value_usd=state.cash_reference_hold_value_usd,
            cash_max_hold_value_usd=state.cash_max_hold_value_usd,
            cash_interval_missed_recovery=state.cash_interval_missed_recovery,
            complete=state.complete,
            metadata_json=_json(
                {
                    "milestone": "M6H-performance",
                    "cost_model": cost_model.public_dict(),
                    "valuation_method": valuation_method,
                    "quote_detail_complete": mark_detail_complete,
                    "action_detail_complete": action_complete,
                    "policy_action": decision.action,
                    "can_execute": False,
                    "baseline_mutated": False,
                    "lookahead_used_for_decision": False,
                    "hindsight_used_for_scoring": True,
                    "common_m6g_entry_cost_excluded": True,
                }
            ),
        )
        db.add(row)
        return row

    @classmethod
    def account_position_policy(
        cls,
        db: Session,
        *,
        study_id: str,
        position_key: str,
        policy_name: str,
        policy_version: str,
        cost_model: LifecycleCostModel | None = None,
    ) -> int:
        cost_model = cost_model or LifecycleCostModel()
        decisions = db.scalars(
            select(LifecyclePolicyDecision)
            .where(
                LifecyclePolicyDecision.study_id == study_id,
                LifecyclePolicyDecision.position_key == position_key,
                LifecyclePolicyDecision.policy_name == policy_name,
                LifecyclePolicyDecision.policy_version == policy_version,
            )
            .order_by(
                LifecyclePolicyDecision.decided_at.asc(),
                LifecyclePolicyDecision.created_at.asc(),
                LifecyclePolicyDecision.id.asc(),
            )
        ).all()
        if not decisions:
            return 0
        existing_rows = db.scalars(
            select(LifecyclePerformanceSnapshot).where(
                LifecyclePerformanceSnapshot.study_id == study_id,
                LifecyclePerformanceSnapshot.position_key == position_key,
                LifecyclePerformanceSnapshot.policy_name == policy_name,
                LifecyclePerformanceSnapshot.policy_version == policy_version,
                LifecyclePerformanceSnapshot.accounting_version == cost_model.version,
            )
        ).all()
        existing = {row.decision_id: row for row in existing_rows}
        state: _ReplayState | None = None
        created = 0
        encountered_gap = False
        for decision in decisions:
            persisted = existing.get(decision.id)
            if persisted is not None:
                if encountered_gap:
                    raise LifecyclePerformanceError(
                        "performance journal has a non-contiguous accounting gap"
                    )
                state = cls._state_from_snapshot(persisted)
                continue
            encountered_gap = True
            observation = db.get(LifecycleObservation, decision.observation_id)
            if observation is None:
                raise LifecyclePerformanceError("decision observation is missing")
            if state is None:
                state = cls._initial_state(observation, decision)
            cls._apply_decision(
                db,
                state=state,
                observation=observation,
                decision=decision,
                cost_model=cost_model,
            )
            created += 1
        if created:
            db.commit()
        return created

    @classmethod
    def account_observation(
        cls,
        db: Session,
        observation: LifecycleObservation,
        *,
        cost_model: LifecycleCostModel | None = None,
    ) -> int:
        decisions = db.scalars(
            select(LifecyclePolicyDecision).where(
                LifecyclePolicyDecision.observation_id == observation.id
            )
        ).all()
        created = 0
        for decision in decisions:
            created += cls.account_position_policy(
                db,
                study_id=decision.study_id,
                position_key=decision.position_key,
                policy_name=decision.policy_name,
                policy_version=decision.policy_version,
                cost_model=cost_model,
            )
        return created

    @staticmethod
    def summarize_policy(
        db: Session,
        *,
        study_id: str,
        policy_name: str,
        policy_version: str,
        accounting_version: str = ACCOUNTING_VERSION,
        min_positions: int = MIN_POLICY_POSITIONS,
        min_completed_cycles: int = MIN_COMPLETED_CYCLES,
    ) -> LifecyclePolicySummary:
        rows = db.scalars(
            select(LifecyclePerformanceSnapshot)
            .where(
                LifecyclePerformanceSnapshot.study_id == study_id,
                LifecyclePerformanceSnapshot.policy_name == policy_name,
                LifecyclePerformanceSnapshot.policy_version == policy_version,
                LifecyclePerformanceSnapshot.accounting_version == accounting_version,
            )
            .order_by(LifecyclePerformanceSnapshot.observed_at.asc())
        ).all()
        latest_by_position: dict[str, LifecyclePerformanceSnapshot] = {}
        for row in rows:
            latest_by_position[row.position_key] = row
        latest = list(latest_by_position.values())
        complete = [
            row
            for row in latest
            if row.complete
            and row.net_return_pct is not None
            and row.hold_return_pct is not None
            and row.excess_return_pct is not None
        ]
        cycles = db.scalars(
            select(LifecyclePolicyCycle).where(
                LifecyclePolicyCycle.study_id == study_id,
                LifecyclePolicyCycle.policy_name == policy_name,
                LifecyclePolicyCycle.policy_version == policy_version,
                LifecyclePolicyCycle.accounting_version == accounting_version,
            )
        ).all()
        net_returns = [Decimal(row.net_return_pct) for row in complete]
        hold_returns = [Decimal(row.hold_return_pct) for row in complete]
        excess_returns = [Decimal(row.excess_return_pct) for row in complete]
        total_starting = sum((Decimal(row.starting_value_usd) for row in complete), ZERO)
        total_cost = sum((Decimal(row.cumulative_cost_usd) for row in complete), ZERO)
        invested_seconds = sum(row.time_invested_seconds for row in complete)
        cash_seconds = sum(row.time_in_cash_seconds for row in complete)
        total_timed = invested_seconds + cash_seconds
        sample_sufficient = bool(
            len(complete) >= min_positions and len(cycles) >= min_completed_cycles
        )
        return LifecyclePolicySummary(
            study_id=study_id,
            policy_name=policy_name,
            policy_version=policy_version,
            accounting_version=accounting_version,
            position_count=len(latest),
            complete_position_count=len(complete),
            completed_cycle_count=len(cycles),
            round_trip_count=sum(row.round_trip_count for row in latest),
            failed_reentry_count=sum(1 for row in cycles if row.failed_reentry),
            missed_recovery_count=sum(row.missed_recovery_count for row in latest),
            mean_net_return_pct=_mean(net_returns),
            mean_hold_return_pct=_mean(hold_returns),
            mean_excess_return_pct=_mean(excess_returns),
            tail_loss_p05_pct=_percentile(net_returns, Decimal("0.05")),
            worst_return_pct=min(net_returns) if net_returns else None,
            cost_drag_pct=(total_cost / total_starting if total_starting > ZERO else None),
            invested_time_ratio=(
                Decimal(invested_seconds) / Decimal(total_timed) if total_timed > 0 else None
            ),
            sample_sufficient=sample_sufficient,
            selection_status=(
                "READY_FOR_REGISTERED_WALK_FORWARD" if sample_sufficient else "INSUFFICIENT_SAMPLE"
            ),
            can_promote=False,
        )
