from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Sequence

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
EPS = Decimal("0.000000001")
PNL_TOLERANCE = Decimal("0.000001")


class EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class NavObservation:
    observed_at: datetime
    nav_usd: Decimal


@dataclass(frozen=True)
class TradeOutcome:
    closed_at: datetime
    gross_pnl_usd: Decimal
    net_pnl_usd: Decimal
    fees_usd: Decimal
    slippage_usd: Decimal
    allocated_capital_usd: Decimal
    planned_loss_usd: Decimal


@dataclass(frozen=True)
class ExecutionComparison:
    observed_at: datetime
    side: Literal["buy", "sell"]
    intended_quantity: Decimal
    paper_filled_quantity: Decimal
    shadow_filled_quantity: Decimal
    paper_average_price: Decimal | None
    shadow_average_price: Decimal | None
    paper_cost_usd: Decimal = ZERO
    shadow_cost_usd: Decimal = ZERO


@dataclass(frozen=True)
class ForecastOutcome:
    resolved_at: datetime
    probability: Decimal
    outcome: int
    market_probability: Decimal | None = None


@dataclass(frozen=True)
class EvaluationInput:
    strategy_slug: str
    strategy_version: str
    family: Literal["funding", "prediction", "directional", "meme", "other"]
    forward_started_at: datetime
    evaluated_at: datetime
    nav_series: tuple[NavObservation, ...] = ()
    trades: tuple[TradeOutcome, ...] = ()
    executions: tuple[ExecutionComparison, ...] = ()
    forecasts: tuple[ForecastOutcome, ...] = ()
    unresolved_critical_incidents: int = 0
    data_integrity_failures: int = 0


@dataclass(frozen=True)
class EvaluationPolicy:
    min_forward_days: int = 90
    min_nav_observations: int = 60
    min_shadow_observations: int = 30
    min_trades_default: int = 100
    min_trades_funding: int = 60
    min_trades_directional: int = 100
    min_trades_meme: int = 300
    min_forecasts_prediction: int = 50
    max_drawdown_pct: Decimal = Decimal("0.15")
    min_profit_factor: Decimal = Decimal("1.30")
    max_top3_profit_concentration: Decimal = Decimal("0.50")
    cost_stress_multiplier: Decimal = Decimal("2")
    min_shadow_fill_ratio: Decimal = Decimal("0.90")
    max_shadow_p90_price_divergence_bps: Decimal = Decimal("50")
    max_prediction_calibration_error: Decimal = Decimal("0.10")

    def min_trade_count(self, family: str) -> int:
        if family == "funding":
            return self.min_trades_funding
        if family == "directional":
            return self.min_trades_directional
        if family == "meme":
            return self.min_trades_meme
        return self.min_trades_default

    def validate(self) -> None:
        for value in (
            self.min_forward_days,
            self.min_nav_observations,
            self.min_shadow_observations,
            self.min_trades_default,
            self.min_trades_funding,
            self.min_trades_directional,
            self.min_trades_meme,
            self.min_forecasts_prediction,
        ):
            if value < 1:
                raise EvaluationError("minimum evidence counts must be positive")
        for name, value in (
            ("max_drawdown_pct", self.max_drawdown_pct),
            ("max_top3_profit_concentration", self.max_top3_profit_concentration),
            ("min_shadow_fill_ratio", self.min_shadow_fill_ratio),
            ("max_prediction_calibration_error", self.max_prediction_calibration_error),
        ):
            if value < ZERO or value > ONE:
                raise EvaluationError(f"{name} must be between zero and one")
        if self.min_profit_factor <= ZERO:
            raise EvaluationError("min_profit_factor must be positive")
        if self.cost_stress_multiplier < ONE:
            raise EvaluationError("cost_stress_multiplier must be at least one")
        if self.max_shadow_p90_price_divergence_bps < ZERO:
            raise EvaluationError("max shadow price divergence cannot be negative")


@dataclass(frozen=True)
class PerformanceMetrics:
    forward_days: int
    nav_observation_count: int
    trade_count: int
    gross_pnl_usd: Decimal
    net_pnl_usd: Decimal
    observed_costs_usd: Decimal
    stressed_net_pnl_usd: Decimal
    profit_factor: Decimal | None
    win_rate: Decimal | None
    expectancy_usd: Decimal | None
    average_win_usd: Decimal | None
    average_loss_usd: Decimal | None
    max_drawdown_pct: Decimal | None
    sharpe_annualized: Decimal | None
    sortino_annualized: Decimal | None
    top3_profit_concentration: Decimal | None


@dataclass(frozen=True)
class ExecutionMetrics:
    observation_count: int
    mean_shadow_fill_ratio: Decimal | None
    p90_absolute_price_divergence_bps: Decimal | None
    mean_cost_underestimate_usd: Decimal | None


@dataclass(frozen=True)
class PredictionMetrics:
    forecast_count: int
    brier_score: Decimal | None
    log_loss: Decimal | None
    calibration_error: Decimal | None
    market_brier_score: Decimal | None
    brier_improvement_vs_market: Decimal | None


@dataclass(frozen=True)
class EvaluationResult:
    recommendation: Literal["RED", "AMBER", "GREEN-1_CANDIDATE"]
    reasons: tuple[str, ...]
    performance: PerformanceMetrics
    execution: ExecutionMetrics
    prediction: PredictionMetrics
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _to_decimal(value: float) -> Decimal:
    if math.isnan(value) or math.isinf(value):
        raise EvaluationError("non-finite metric")
    return Decimal(str(value))


def _percentile(values: Sequence[Decimal], q: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _daily_equivalent_returns(nav_series: tuple[NavObservation, ...]) -> list[Decimal]:
    ordered = sorted(nav_series, key=lambda item: _aware(item.observed_at))
    returns: list[Decimal] = []
    for previous, current in zip(ordered, ordered[1:]):
        elapsed_days = (_aware(current.observed_at) - _aware(previous.observed_at)).total_seconds() / 86400
        if elapsed_days <= 0:
            continue
        ratio = float(current.nav_usd / previous.nav_usd)
        returns.append(_to_decimal(math.pow(ratio, 1.0 / elapsed_days) - 1.0))
    return returns


def _risk_adjusted(returns: list[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    if len(returns) < 2:
        return None, None
    floats = [float(value) for value in returns]
    mean = sum(floats) / len(floats)
    variance = sum((value - mean) ** 2 for value in floats) / (len(floats) - 1)
    stdev = math.sqrt(variance)
    annualizer = math.sqrt(365)
    sharpe = mean / stdev * annualizer if stdev > 0 else None
    downside = [min(value, 0.0) for value in floats]
    downside_variance = sum(value * value for value in downside) / len(downside)
    downside_dev = math.sqrt(downside_variance)
    sortino = mean / downside_dev * annualizer if downside_dev > 0 else None
    return (_to_decimal(sharpe) if sharpe is not None else None, _to_decimal(sortino) if sortino is not None else None)


def _max_drawdown(nav_series: tuple[NavObservation, ...]) -> Decimal | None:
    if not nav_series:
        return None
    ordered = sorted(nav_series, key=lambda item: _aware(item.observed_at))
    peak = ordered[0].nav_usd
    max_drawdown = ZERO
    for observation in ordered:
        peak = max(peak, observation.nav_usd)
        drawdown = (peak - observation.nav_usd) / peak
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def performance_metrics(evaluation: EvaluationInput, policy: EvaluationPolicy) -> PerformanceMetrics:
    start = _aware(evaluation.forward_started_at)
    end = _aware(evaluation.evaluated_at)
    forward_days = max(0, int((end - start).total_seconds() // 86400))
    trades = sorted(evaluation.trades, key=lambda item: _aware(item.closed_at))
    gross = sum((trade.gross_pnl_usd for trade in trades), ZERO)
    net = sum((trade.net_pnl_usd for trade in trades), ZERO)
    observed_costs = sum((trade.fees_usd + trade.slippage_usd for trade in trades), ZERO)
    stressed_net = gross - observed_costs * policy.cost_stress_multiplier
    winners = [trade.net_pnl_usd for trade in trades if trade.net_pnl_usd > ZERO]
    losers = [trade.net_pnl_usd for trade in trades if trade.net_pnl_usd < ZERO]
    total_wins = sum(winners, ZERO)
    total_losses = abs(sum(losers, ZERO))
    profit_factor = total_wins / total_losses if total_losses > ZERO else (None if total_wins <= ZERO else Decimal("999"))
    win_rate = Decimal(len(winners)) / Decimal(len(trades)) if trades else None
    expectancy = net / Decimal(len(trades)) if trades else None
    average_win = total_wins / Decimal(len(winners)) if winners else None
    average_loss = sum(losers, ZERO) / Decimal(len(losers)) if losers else None
    concentration = sum(sorted(winners, reverse=True)[:3], ZERO) / total_wins if total_wins > ZERO else None
    sharpe, sortino = _risk_adjusted(_daily_equivalent_returns(evaluation.nav_series))
    return PerformanceMetrics(
        forward_days=forward_days,
        nav_observation_count=len(evaluation.nav_series),
        trade_count=len(trades),
        gross_pnl_usd=gross,
        net_pnl_usd=net,
        observed_costs_usd=observed_costs,
        stressed_net_pnl_usd=stressed_net,
        profit_factor=profit_factor,
        win_rate=win_rate,
        expectancy_usd=expectancy,
        average_win_usd=average_win,
        average_loss_usd=average_loss,
        max_drawdown_pct=_max_drawdown(evaluation.nav_series),
        sharpe_annualized=sharpe,
        sortino_annualized=sortino,
        top3_profit_concentration=concentration,
    )


def execution_metrics(evaluation: EvaluationInput) -> ExecutionMetrics:
    fill_ratios: list[Decimal] = []
    divergences: list[Decimal] = []
    cost_underestimates: list[Decimal] = []
    for item in evaluation.executions:
        fill_ratios.append(item.shadow_filled_quantity / item.intended_quantity)
        if item.paper_average_price is not None and item.shadow_average_price is not None:
            divergences.append(abs(item.shadow_average_price - item.paper_average_price) / item.paper_average_price * BPS)
        cost_underestimates.append(item.shadow_cost_usd - item.paper_cost_usd)
    return ExecutionMetrics(
        observation_count=len(evaluation.executions),
        mean_shadow_fill_ratio=(sum(fill_ratios, ZERO) / Decimal(len(fill_ratios))) if fill_ratios else None,
        p90_absolute_price_divergence_bps=_percentile(divergences, Decimal("0.90")),
        mean_cost_underestimate_usd=(sum(cost_underestimates, ZERO) / Decimal(len(cost_underestimates))) if cost_underestimates else None,
    )


def prediction_metrics(evaluation: EvaluationInput) -> PredictionMetrics:
    if not evaluation.forecasts:
        return PredictionMetrics(0, None, None, None, None, None)
    brier_values: list[Decimal] = []
    log_losses: list[Decimal] = []
    market_brier: list[Decimal] = []
    bins: dict[int, list[tuple[Decimal, int]]] = {}
    for forecast in evaluation.forecasts:
        p = forecast.probability
        outcome = Decimal(forecast.outcome)
        brier_values.append((p - outcome) ** 2)
        clipped = min(ONE - EPS, max(EPS, p))
        log_losses.append(_to_decimal(-math.log(float(clipped if forecast.outcome == 1 else ONE - clipped))))
        bin_index = min(9, int(p * Decimal("10")))
        bins.setdefault(bin_index, []).append((p, forecast.outcome))
        if forecast.market_probability is not None:
            market_brier.append((forecast.market_probability - outcome) ** 2)

    calibration = ZERO
    count = Decimal(len(brier_values))
    for values in bins.values():
        average_p = sum((value[0] for value in values), ZERO) / Decimal(len(values))
        actual_rate = Decimal(sum(value[1] for value in values)) / Decimal(len(values))
        calibration += abs(average_p - actual_rate) * Decimal(len(values)) / count
    brier = sum(brier_values, ZERO) / count
    market = sum(market_brier, ZERO) / Decimal(len(market_brier)) if len(market_brier) == len(brier_values) else None
    return PredictionMetrics(
        forecast_count=len(brier_values),
        brier_score=brier,
        log_loss=sum(log_losses, ZERO) / count,
        calibration_error=calibration,
        market_brier_score=market,
        brier_improvement_vs_market=(market - brier) if market is not None else None,
    )


class EvidenceEvaluator:
    """Produces research evidence only. It never mutates Strategy.status or enables signing."""

    def __init__(self, policy: EvaluationPolicy) -> None:
        policy.validate()
        self.policy = policy

    @staticmethod
    def _validate_input(evaluation: EvaluationInput) -> None:
        if not evaluation.strategy_slug.strip() or not evaluation.strategy_version.strip():
            raise EvaluationError("strategy slug and version are required")
        if evaluation.unresolved_critical_incidents < 0 or evaluation.data_integrity_failures < 0:
            raise EvaluationError("incident counters cannot be negative")
        start = _aware(evaluation.forward_started_at)
        end = _aware(evaluation.evaluated_at)
        if end < start:
            raise EvaluationError("evaluated_at cannot precede forward_started_at")
        timestamps = [item.observed_at for item in evaluation.nav_series]
        timestamps += [item.closed_at for item in evaluation.trades]
        timestamps += [item.observed_at for item in evaluation.executions]
        timestamps += [item.resolved_at for item in evaluation.forecasts]
        if any(_aware(value) < start or _aware(value) > end for value in timestamps):
            raise EvaluationError("all evidence observations must fall inside the declared forward window")
        nav_times = [_aware(item.observed_at) for item in evaluation.nav_series]
        if len(nav_times) != len(set(nav_times)):
            raise EvaluationError("NAV observations cannot share a timestamp")
        if any(item.nav_usd <= ZERO for item in evaluation.nav_series):
            raise EvaluationError("NAV observations must be positive")
        for trade in evaluation.trades:
            if trade.fees_usd < ZERO or trade.slippage_usd < ZERO:
                raise EvaluationError("trade costs cannot be negative")
            if trade.allocated_capital_usd <= ZERO or trade.planned_loss_usd <= ZERO:
                raise EvaluationError("trade allocated capital and planned loss must be positive")
            if trade.planned_loss_usd > trade.allocated_capital_usd:
                raise EvaluationError("planned loss cannot exceed allocated capital")
            expected_net = trade.gross_pnl_usd - trade.fees_usd - trade.slippage_usd
            if abs(trade.net_pnl_usd - expected_net) > PNL_TOLERANCE:
                raise EvaluationError("trade net PnL must reconcile to gross PnL minus costs")
        for item in evaluation.executions:
            if item.intended_quantity <= ZERO or item.paper_filled_quantity < ZERO or item.shadow_filled_quantity < ZERO:
                raise EvaluationError("execution quantities are invalid")
            if item.paper_filled_quantity > item.intended_quantity or item.shadow_filled_quantity > item.intended_quantity:
                raise EvaluationError("execution fill cannot exceed intended quantity")
            if item.paper_average_price is not None and item.paper_average_price <= ZERO:
                raise EvaluationError("paper average price must be positive")
            if item.shadow_average_price is not None and item.shadow_average_price <= ZERO:
                raise EvaluationError("shadow average price must be positive")
            if item.paper_cost_usd < ZERO or item.shadow_cost_usd < ZERO:
                raise EvaluationError("execution costs cannot be negative")
        for forecast in evaluation.forecasts:
            if forecast.probability < ZERO or forecast.probability > ONE or forecast.outcome not in (0, 1):
                raise EvaluationError("forecast probability/outcome is invalid")
            if forecast.market_probability is not None and (forecast.market_probability < ZERO or forecast.market_probability > ONE):
                raise EvaluationError("market probability is invalid")

    def evaluate(self, evaluation: EvaluationInput) -> EvaluationResult:
        self._validate_input(evaluation)
        performance = performance_metrics(evaluation, self.policy)
        execution = execution_metrics(evaluation)
        prediction = prediction_metrics(evaluation)
        red: list[str] = []
        amber: list[str] = []

        if evaluation.data_integrity_failures > 0:
            red.append("DATA_INTEGRITY_FAILURE")
        if evaluation.unresolved_critical_incidents > 0:
            red.append("UNRESOLVED_CRITICAL_INCIDENT")
        if performance.trade_count == 0:
            amber.append("NO_CLOSED_TRADES")
        elif performance.net_pnl_usd <= ZERO:
            red.append("NON_POSITIVE_NET_PNL")
        if performance.trade_count > 0 and performance.stressed_net_pnl_usd <= ZERO:
            red.append("FAILS_COST_STRESS")

        if performance.nav_observation_count < 2:
            amber.append("INSUFFICIENT_NAV_SERIES")
        else:
            if performance.nav_observation_count < self.policy.min_nav_observations:
                amber.append("INSUFFICIENT_NAV_OBSERVATIONS")
            if performance.max_drawdown_pct is not None and performance.max_drawdown_pct > self.policy.max_drawdown_pct:
                red.append("MAX_DRAWDOWN_EXCEEDED")
        if performance.forward_days < self.policy.min_forward_days:
            amber.append("INSUFFICIENT_FORWARD_DAYS")

        if performance.trade_count > 0:
            if performance.profit_factor is None or performance.profit_factor < self.policy.min_profit_factor:
                amber.append("PROFIT_FACTOR_BELOW_GATE")
            if performance.top3_profit_concentration is not None and performance.top3_profit_concentration > self.policy.max_top3_profit_concentration:
                amber.append("PROFIT_TOO_CONCENTRATED")

        if evaluation.family == "prediction":
            if prediction.forecast_count < self.policy.min_forecasts_prediction:
                amber.append("INSUFFICIENT_RESOLVED_FORECASTS")
            if prediction.calibration_error is None or prediction.calibration_error > self.policy.max_prediction_calibration_error:
                amber.append("PREDICTION_CALIBRATION_NOT_READY")
            if prediction.market_brier_score is None:
                amber.append("MISSING_MARKET_BRIER_BASELINE")
            elif prediction.brier_improvement_vs_market is None or prediction.brier_improvement_vs_market <= ZERO:
                amber.append("DOES_NOT_BEAT_MARKET_BRIER")
        elif performance.trade_count < self.policy.min_trade_count(evaluation.family):
            amber.append("INSUFFICIENT_TRADE_SAMPLE")

        if execution.observation_count == 0:
            amber.append("NO_SHADOW_EXECUTION_SAMPLE")
        else:
            if execution.observation_count < self.policy.min_shadow_observations:
                amber.append("INSUFFICIENT_SHADOW_SAMPLE")
            if execution.mean_shadow_fill_ratio is None or execution.mean_shadow_fill_ratio < self.policy.min_shadow_fill_ratio:
                amber.append("SHADOW_FILL_RATIO_BELOW_GATE")
            if execution.p90_absolute_price_divergence_bps is None or execution.p90_absolute_price_divergence_bps > self.policy.max_shadow_p90_price_divergence_bps:
                amber.append("PAPER_SHADOW_PRICE_DIVERGENCE")

        if red:
            recommendation: Literal["RED", "AMBER", "GREEN-1_CANDIDATE"] = "RED"
            reasons = tuple(dict.fromkeys(red + amber))
        elif amber:
            recommendation = "AMBER"
            reasons = tuple(dict.fromkeys(amber))
        else:
            recommendation = "GREEN-1_CANDIDATE"
            reasons = ("ALL_PRE_REGISTERED_FORWARD_GATES_PASSED",)
        return EvaluationResult(
            recommendation=recommendation,
            reasons=reasons,
            performance=performance,
            execution=execution,
            prediction=prediction,
        )
