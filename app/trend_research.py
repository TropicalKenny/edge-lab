"""Locked, unlevered spot replay. No account, order, signer or portfolio integration."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def protocol() -> dict:
    return json.loads(Path(__file__).with_name("trend_protocol.json").read_text())


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self):
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("nonfinite candle")
        if self.low <= 0 or not self.low <= min(self.open, self.close):
            raise ValueError("invalid candle low")
        if self.high < max(self.open, self.close) or self.volume < 0:
            raise ValueError("invalid candle high/volume")


def validate_history(bars: list[Bar], start: date, end: date):
    expected = (end - start).days
    if len(bars) != expected or expected <= 0:
        raise ValueError("incomplete daily coverage")
    for i, bar in enumerate(bars):
        bar.validate()
        if bar.day != start + timedelta(days=i):
            raise ValueError("missing, duplicate or unordered candle")


def replay(
    bars: list[Bar],
    start: date,
    end: date,
    lookback: int | None,
    fee_bps: float,
    slip_bps: float,
    lag_days: int = 1,
    capital: float = 500,
) -> dict:
    """End exclusive. Signal uses day i-lag-1, hence a full-day delay by default.

    Liquidate at the last close for comparable net terminal cash. This is a
    boundary valuation convention, not a deployable same-close signal fill.
    Every window starts in cash; earlier bars are warmup features only.
    """
    if lag_days < 1 or (lookback is not None and lookback < 1):
        raise ValueError("invalid signal timing")
    if not all(math.isfinite(v) for v in (fee_bps, slip_bps, capital)):
        raise ValueError("invalid cost/capital")
    if not 0 <= fee_bps < 10000 or not 0 <= slip_bps < 10000 or capital <= 0:
        raise ValueError("invalid cost/capital")
    validate_history(
        bars, bars[0].day if bars else start, bars[-1].day + timedelta(days=1) if bars else end
    )
    indices = [i for i, b in enumerate(bars) if start <= b.day < end]
    if len(indices) != (end - start).days or not indices:
        raise ValueError("window coverage missing")
    if lookback and indices[0] - lag_days < lookback:
        raise ValueError("insufficient warmup")
    cash, units, fees, slippage = capital, 0.0, 0.0, 0.0
    entry_cash = 0.0
    trades, navs = [], []
    fee, slip = fee_bps / 10000, slip_bps / 10000

    def sell(price, day, reason):
        nonlocal cash, units, fees, slippage
        notional = units * price * (1 - slip)
        fees += notional * fee
        slippage += units * price * slip
        cash = notional * (1 - fee)
        trades.append({"exit_day": str(day), "reason": reason, "net_pnl_usd": cash - entry_cash})
        units = 0.0

    for i in indices:
        b = bars[i]
        signal = i - lag_days - 1
        want_long = lookback is None or bars[signal].close > fmean(
            v.close for v in bars[signal - lookback + 1 : signal + 1]
        )
        if want_long and units == 0:
            entry_cash = cash
            units = cash / ((b.open * (1 + slip)) * (1 + fee))
            fees += units * b.open * (1 + slip) * fee
            slippage += units * b.open * slip
            cash = 0.0
        elif not want_long and units > 0:
            sell(b.open, b.day, "signal")
        if i == indices[-1] and units > 0:
            sell(b.close, b.day, "window_end_valuation")
        # Net liquidation NAV includes hypothetical exit cost without booking it.
        navs.append(cash + units * b.close * (1 - slip) * (1 - fee))
    return {
        "daily_nav": navs,
        "trades": trades,
        "fees_usd": fees,
        "slippage_usd": slippage,
        "final_cash_usd": cash,
    }


def combined(legs: list[dict], capital: float) -> dict:
    nav = [sum(v) for v in zip(*(leg["daily_nav"] for leg in legs), strict=True)]
    peak, drawdown = capital, 0.0
    for value in nav:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    pnl = nav[-1] - capital
    profits = [t["net_pnl_usd"] for leg in legs for t in leg["trades"]]
    return {
        "net_pnl_usd": pnl,
        "return_fraction": pnl / capital,
        "max_drawdown_fraction": drawdown,
        "closed_round_trips": len(profits),
        "fees_usd": sum(x["fees_usd"] for x in legs),
        "slippage_usd": sum(x["slippage_usd"] for x in legs),
        "pnl_less_largest_winning_trade_usd": pnl - max([0.0] + profits),
        "winner_removal_method": "attribution subtraction; no path resimulation",
    }


def evaluate(histories: dict[str, list[Bar]], config: dict) -> dict:
    output = {}
    for name, (start, end) in config["windows"].items():
        results = {}
        for lookback in [*config["lookbacks"], None]:
            label = f"sma_{lookback}" if lookback else "buy_hold"
            for stress, multiplier, delay in [
                ("base", 1, 1),
                ("double_cost", 2, 1),
                ("extra_day_delay", 1, 2),
            ]:
                legs = [
                    replay(
                        histories[p],
                        date.fromisoformat(start),
                        date.fromisoformat(end),
                        lookback,
                        config["fee_bps_per_side"] * multiplier,
                        config["slippage_bps_per_side"] * multiplier,
                        delay,
                        config["initial_capital_usd"] / len(config["products"]),
                    )
                    for p in config["products"]
                ]
                results[f"{label}/{stress}"] = combined(legs, config["initial_capital_usd"])
        results["cash"] = {"net_pnl_usd": 0, "return_fraction": 0, "max_drawdown_fraction": 0}
        output[name] = results
    return {
        "protocol_hash": digest(config),
        "windows": output,
        "kind": "historical_bar_replay_not_forward_profit",
        "promoted": False,
        "live_capital_usd": 0,
    }
