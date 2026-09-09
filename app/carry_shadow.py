"""Independent conditional-quote carry books with no exchange execution capability."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

HOUR = 3600000


def protocol():
    return json.loads(Path(__file__).with_name("carry_protocol.json").read_text())


def finite(value, positive=False):
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("invalid market number")
    return number


def database(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, body TEXT);
      CREATE TABLE IF NOT EXISTS funding (time INTEGER PRIMARY KEY, rate REAL);
      CREATE TABLE IF NOT EXISTS oracle (time INTEGER PRIMARY KEY, price REAL);
      CREATE TABLE IF NOT EXISTS books (horizon INTEGER PRIMARY KEY, body TEXT);
      CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time INTEGER, body TEXT);
    """)
    encoded = json.dumps(protocol(), sort_keys=True)
    prior = db.execute("SELECT body FROM meta WHERE key='protocol'").fetchone()
    if prior and prior[0] != encoded:
        raise ValueError("carry protocol changed; use a new volume")
    with db:
        db.execute("INSERT OR IGNORE INTO meta VALUES ('protocol', ?)", (encoded,))
    return db


def save_funding(db, rows):
    with db:
        for row in rows:
            if row["coin"] != "BTC":
                raise ValueError("funding asset mismatch")
            stamp = int(row["time"])
            bucket = stamp // HOUR * HOUR
            same_hour = db.execute(
                "SELECT time FROM funding WHERE time>=? AND time<?", (bucket, bucket + HOUR)
            ).fetchone()
            if same_hour and same_hour[0] != stamp:
                raise ValueError("conflicting funding records in one hour")
            rate = finite(row["fundingRate"])
            if abs(rate) > 0.04:
                raise ValueError("funding outside documented cap")
            prior = db.execute("SELECT rate FROM funding WHERE time=?", (stamp,)).fetchone()
            if prior and prior[0] != rate:
                raise ValueError("historical funding revision")
            db.execute("INSERT OR IGNORE INTO funding VALUES (?, ?)", (stamp, rate))


def rates_between(db, start, end):
    expected = set(range((start // HOUR + 1) * HOUR, end // HOUR * HOUR + 1, HOUR))
    rows = db.execute(
        "SELECT time,rate FROM funding WHERE time>? AND time<=? ORDER BY time", (start, end)
    ).fetchall()
    # Preserve actual payment timestamps: an entry just before a payment in the
    # same hour earns it; an exit before a known later payment does not.
    if rows and rows[0][0] // HOUR == start // HOUR:
        expected.add(start // HOUR * HOUR)
    last_bucket = end // HOUR * HOUR
    known_last = db.execute(
        "SELECT time FROM funding WHERE time>=? AND time<?", (last_bucket, last_bucket + HOUR)
    ).fetchone()
    if known_last and known_last[0] > end:
        expected.discard(last_bucket)
    if [r[0] // HOUR * HOUR for r in rows] != sorted(expected):
        raise ValueError("missing settled funding hour")
    return rows


def forecast(db, now, horizon):
    # Five-minute publication buffer; never use the unsettled current rate.
    end = (now - 300000) // HOUR * HOUR
    cutoff = now - 300000
    rows = db.execute(
        "SELECT time,rate FROM funding WHERE time>=? AND time<=? ORDER BY time",
        (end - 719 * HOUR, cutoff),
    ).fetchall()
    if [t // HOUR * HOUR for t, _ in rows] != list(range(end - 719 * HOUR, end + 1, HOUR)):
        raise ValueError("missing settled funding hour")
    return min(sum(r for _, r in rows[-168:]) / 168, sum(r for _, r in rows) / 720) * horizon


def funding_cashflow(db, position, through, max_age_seconds=120):
    total = 0.0
    for stamp, rate in rates_between(db, position["opened_ms"], through):
        row = db.execute(
            "SELECT time,price FROM oracle WHERE time<=? ORDER BY time DESC LIMIT 1", (stamp,)
        ).fetchone()
        if not row or stamp - row[0] > max_age_seconds * 1000:
            raise ValueError("missing decision-time oracle proxy")
        total += position["quantity"] * row[1] * rate
    return total


def walk(book, side, quantity, now):
    if not 0 <= now - int(book["time"]) <= 10000:
        raise ValueError("stale or future book")
    bids, asks = book["levels"]
    if not bids or not asks:
        raise ValueError("empty book")
    if finite(bids[0]["px"], True) >= finite(asks[0]["px"], True):
        raise ValueError("crossed book")
    levels = asks if side == "buy" else bids
    remaining, notional, previous = quantity, 0.0, None
    for level in levels:
        price, size = finite(level["px"], True), finite(level["sz"], True)
        if previous is not None and (
            (side == "buy" and price < previous) or (side == "sell" and price > previous)
        ):
            raise ValueError("unordered book")
        previous = price
        fill = min(size, remaining)
        notional += fill * price
        remaining -= fill
        if remaining <= quantity * 1e-12:
            return notional / quantity
    raise ValueError("insufficient full-leg depth")


def quotes(spot, perp, quantity, now, entry):
    if abs(int(spot["time"]) - int(perp["time"])) > 2000:
        raise ValueError("pair timestamp skew")
    return (
        walk(spot, "buy" if entry else "sell", quantity, now),
        walk(perp, "sell" if entry else "buy", quantity, now),
    )


def valuation(p, spot, perp, funding, config, multiplier=1):
    slip = config["adverse_bps_per_leg"] * multiplier / 10000
    s_exit, p_exit = spot * (1 - slip), perp * (1 + slip)
    # For the stress book reconstruct the same entry quantities at stressed prices.
    s_entry = p["spot_quote"] * (1 + slip)
    p_entry = p["perp_quote"] * (1 - slip)
    q = p["quantity"]
    fees = (
        q
        * (
            (s_entry + s_exit) * config["spot_fee_bps"]
            + (p_entry + p_exit) * config["perp_fee_bps"]
        )
        * multiplier
        / 10000
    )
    basis_pnl = q * ((s_exit - s_entry) + (p_entry - p_exit))
    return {
        "funding_usd": funding,
        "hedge_price_pnl_usd": basis_pnl,
        "fees_usd": fees,
        "net_pnl_usd": basis_pnl + funding - fees,
    }


def event(db, now, value):
    db.execute(
        "INSERT INTO events(time,body) VALUES (?, ?)",
        (now, json.dumps(value, sort_keys=True, allow_nan=False)),
    )


def advance(db, now, market, spot_book, perp_book, config=None):
    """One atomic bookkeeping cycle, with already captured public market evidence.

    Full-pair shadow fills are conditional on execution of BOTH legs. No queue,
    settlement or true liquidation simulation is claimed. Unpriceable exits remain
    open and block new entries. Incomplete funding can never become zero income.
    """
    cfg = config or protocol()
    if spot_book.get("coin") != market["spot_coin"] or perp_book.get("coin") != "BTC":
        raise ValueError("book identity mismatch")
    identity = json.dumps(market["identity"], sort_keys=True)
    prior = db.execute("SELECT body FROM meta WHERE key='identity'").fetchone()
    if prior and prior[0] != identity:
        raise ValueError("pinned spot token identity changed")
    with db:
        db.execute("INSERT OR IGNORE INTO meta VALUES ('identity', ?)", (identity,))
        db.execute(
            "INSERT OR IGNORE INTO oracle VALUES (?, ?)",
            (market["captured_ms"], finite(market["oracle"], True)),
        )
        output = []
        for horizon in cfg["horizons_hours"]:
            row = db.execute("SELECT body FROM books WHERE horizon=?", (horizon,)).fetchone()
            b = (
                json.loads(row[0])
                if row
                else {
                    "capital": cfg["capital_per_book_usd"],
                    "closed": 0,
                    "position": None,
                    "net_pnl_usd": 0.0,
                    "contaminated": False,
                }
            )
            if now <= b.get("last_ms", 0):
                output.append(b)
                continue
            p = b["position"]
            b["horizon_hours"] = horizon
            b["status"] = "flat"
            if not p:
                b["marked_nav_usd"] = b["capital"]
            if p:
                if now - b["last_ms"] > cfg["max_monitoring_gap_seconds"] * 1000:
                    b["contaminated"] = True
                    b["integrity_reason"] = "monitoring_gap_margin_path_unknown"
                funding = None
                try:
                    funding = funding_cashflow(
                        db, p, p.get("closed_ms", now), cfg["max_oracle_age_seconds"]
                    )
                except ValueError as exc:
                    b["funding_error"] = str(exc)
                    if "oracle" in str(exc) or now % HOUR > 600000:
                        b["contaminated"] = True
                        b["integrity_reason"] = "funding_valuation_gap"
                else:
                    b.pop("funding_error", None)
                if "closed_ms" not in p:
                    try:
                        s_exit, p_exit = quotes(spot_book, perp_book, p["quantity"], now, False)
                        b.pop("exit_error", None)
                    except ValueError as exc:
                        b["status"] = "exit_depth_unavailable"
                        b["exit_error"] = str(exc)
                        b["marked_nav_usd"] = None
                    else:
                        mark = valuation(p, s_exit, p_exit, funding or 0.0, cfg)
                        margin_equity = p["margin"] + p["quantity"] * (p["perp_fill"] - p_exit)
                        # Do not credit uncertain funding to the collateral check.
                        margin_equity += min(funding or 0.0, 0.0) - mark["fees_usd"]
                        margin_ratio = margin_equity / (p["quantity"] * p_exit)
                        b["margin_ratio_conservative"] = margin_ratio
                        b["marked_nav_usd"] = (
                            b["capital"] + mark["net_pnl_usd"] if funding is not None else None
                        )
                        b["status"] = "holding" if funding is not None else "funding_pending"
                        reason = "horizon" if now >= p["target_ms"] else None
                        if mark["net_pnl_usd"] <= -cfg["stop_loss_fraction_of_book"] * b["capital"]:
                            reason = "loss_guard"
                        if margin_ratio <= cfg["margin_exit_ratio"]:
                            reason = "margin_guard"
                        if b["contaminated"]:
                            reason = "monitoring_gap_exit"
                        if reason:
                            p.update(
                                closed_ms=now,
                                exit_spot_quote=s_exit,
                                exit_perp_quote=p_exit,
                                close_reason=reason,
                            )
                            event(db, now, {"horizon": horizon, "event": "conditional_exit", **p})
                if "closed_ms" in p:
                    if funding is None:
                        b["status"] = "closed_pending_funding_accounting"
                    else:
                        result = valuation(
                            p, p["exit_spot_quote"], p["exit_perp_quote"], funding, cfg
                        )
                        stress = valuation(
                            p, p["exit_spot_quote"], p["exit_perp_quote"], funding, cfg, 2
                        )
                        result.update(
                            horizon_hours=horizon,
                            opened_ms=p["opened_ms"],
                            closed_ms=p["closed_ms"],
                            reason=p["close_reason"],
                            return_on_full_book=result["net_pnl_usd"] / b["capital"],
                            double_cost_net_usd=stress["net_pnl_usd"],
                            contaminated=b["contaminated"],
                        )
                        event(db, now, {"event": "accounted_close", **result})
                        b["last_close"] = result
                        b["net_pnl_usd"] += result["net_pnl_usd"]
                        b["capital"] += result["net_pnl_usd"]
                        b["closed"] += 1
                        b["position"] = None
                        b["status"] = "closed"
                        b["marked_nav_usd"] = b["capital"]
            elif not b["contaminated"] and b["capital"] > 0:
                try:
                    projected = forecast(db, now, horizon)
                    b.pop("entry_error", None)
                    q = (
                        math.floor(
                            b["capital"]
                            * cfg["notional_fraction"]
                            / market["oracle"]
                            * 10 ** market["quantity_decimals"]
                        )
                        / 10 ** market["quantity_decimals"]
                    )
                    if q <= 0:
                        raise ValueError("quantity below precision")
                    s_quote, p_quote = quotes(spot_book, perp_book, q, now, True)
                    # Opposite-side depth also gives the CURRENT round-trip spread/impact.
                    s_exit, p_exit = quotes(spot_book, perp_book, q, now, False)
                    candidate = {"quantity": q, "spot_quote": s_quote, "perp_quote": p_quote}
                    round_trip = valuation(candidate, s_exit, p_exit, 0, cfg)
                    notional = q * market["oracle"]
                    cost_bps = -round_trip["net_pnl_usd"] / notional * 10000
                    basis_bps = (p_quote / s_quote - 1) * 10000
                    edge = projected * 10000 - cost_bps
                    b["decision"] = {
                        "projected_funding_bps": projected * 10000,
                        "round_trip_cost_bps": cost_bps,
                        "net_edge_bps": edge,
                        "projected_net_usd": notional * edge / 10000,
                        "projected_return_on_full_book": notional * edge / 10000 / b["capital"],
                        "entry_basis_bps": basis_bps,
                    }
                    # Failed second leg: unwind the first at current opposing depth,
                    # then stress a further 100 bps adverse move. No invented probability.
                    spot_unwind = (
                        q * (s_quote - s_exit)
                        + q * (s_quote + s_exit) * cfg["spot_fee_bps"] / 10000
                    )
                    perp_unwind = (
                        q * (p_exit - p_quote)
                        + q * (p_quote + p_exit) * cfg["perp_fee_bps"] / 10000
                    )
                    b["decision"]["one_leg_failure_100bps_stress_loss_usd"] = (
                        max(spot_unwind, perp_unwind) + notional * 0.01
                    )
                    b["status"] = "no_entry"
                    if (
                        edge > cfg["minimum_edge_bps"]
                        and abs(basis_bps) <= cfg["maximum_entry_basis_bps"]
                    ):
                        slip = cfg["adverse_bps_per_leg"] / 10000
                        s_fill, p_fill = s_quote * (1 + slip), p_quote * (1 - slip)
                        fees = (
                            q
                            * (s_fill * cfg["spot_fee_bps"] + p_fill * cfg["perp_fee_bps"])
                            / 10000
                        )
                        required = q * (s_fill + p_fill) + fees
                        reserve = b["capital"] - required
                        if reserve < b["capital"] * 0.19:
                            raise ValueError("insufficient spot, full short collateral and reserve")
                        b["position"] = {
                            **candidate,
                            "spot_fill": s_fill,
                            "perp_fill": p_fill,
                            "margin": q * p_fill,
                            "reserve": reserve,
                            "opened_ms": now,
                            "target_ms": now + horizon * HOUR,
                            "identity": market["identity"],
                        }
                        b["status"] = "opened_conditional_shadow"
                        b["marked_nav_usd"] = b["capital"] + round_trip["net_pnl_usd"]
                        event(
                            db,
                            now,
                            {
                                "event": "conditional_entry",
                                "horizon": horizon,
                                **b["position"],
                                "decision": b["decision"],
                            },
                        )
                except ValueError as exc:
                    b["status"] = "entry_blocked"
                    b["entry_error"] = str(exc)
            else:
                b["status"] = "frozen"
            b["last_ms"] = now
            if b.get("marked_nav_usd") is not None:
                b["peak_nav_usd"] = max(
                    b.get("peak_nav_usd", cfg["capital_per_book_usd"]), b["marked_nav_usd"]
                )
                b["max_observed_drawdown_fraction"] = max(
                    b.get("max_observed_drawdown_fraction", 0),
                    1 - b["marked_nav_usd"] / b["peak_nav_usd"],
                )
            db.execute(
                "INSERT OR REPLACE INTO books VALUES (?, ?)",
                (horizon, json.dumps(b, sort_keys=True, allow_nan=False)),
            )
            output.append(b)
    return {
        "books": output,
        "protocol_hash": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        "can_trade_live": False,
        "mode": cfg["mode"],
        "automatic_promotion": False,
        "funding_valuation": "realized_rates_times_prior_sampled_oracle_proxy",
        "execution_assumption": "both_legs_execute_at_observed_depth_plus_adverse_reserve",
        "stranded_leg_risk": "failed_second_leg_unwind_plus_100bps_scenario; no_fill_probability_model",
        "liquidation": "conservative_margin_guard; not_exact_venue_liquidation",
    }
