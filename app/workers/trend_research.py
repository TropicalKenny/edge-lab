"""Public-data trend research worker; persistent replay plus daily signal observations."""

import json
import os
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.trend_research import Bar, digest, evaluate, protocol, validate_history

DAY = timedelta(days=1)


def public_get(product, resource, params=None):
    if product not in ("BTC-USD", "ETH-USD") or resource not in ("candles", "ticker"):
        raise ValueError("unsupported public resource")
    url = f"https://api.exchange.coinbase.com/products/{product}/{resource}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "EdgeLab-PaperResearch/1"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def database(path):
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS protocol (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
        CREATE TABLE IF NOT EXISTS candles (
          product TEXT, day TEXT, body TEXT, captured_at TEXT,
          PRIMARY KEY(product, day));
        CREATE TABLE IF NOT EXISTS report (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT);
        CREATE TABLE IF NOT EXISTS observation (day TEXT PRIMARY KEY, body TEXT);
    """)
    body = json.dumps(protocol(), sort_keys=True)
    with db:
        row = db.execute("SELECT body FROM protocol WHERE id=1").fetchone()
        if row and row[0] != body:
            raise ValueError("protocol changed: register a separate research volume")
        db.execute("INSERT OR IGNORE INTO protocol VALUES (1, ?)", (body,))
    return db


def history(db, product, start, end, fetch=public_get):
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=250), end)
        rows = db.execute(
            "SELECT day FROM candles WHERE product=? AND day>=? AND day<?",
            (product, str(cursor), str(stop)),
        ).fetchall()
        if len(rows) != (stop - cursor).days:
            raw = fetch(
                product,
                "candles",
                {"granularity": 86400, "start": f"{cursor}T00:00:00Z", "end": f"{stop}T00:00:00Z"},
            )
            candles = {}
            for row in raw:
                if not isinstance(row, list) or len(row) != 6:
                    raise ValueError("invalid Coinbase candle schema")
                stamp = datetime.fromtimestamp(row[0], UTC)
                day = stamp.date()
                if not cursor <= day < stop:
                    continue  # Coinbase may return bars preceding the requested range.
                if stamp.time() != datetime.min.time() or day in candles:
                    raise ValueError("misaligned or duplicate candle")
                bar = Bar(
                    day, float(row[3]), float(row[2]), float(row[1]), float(row[4]), float(row[5])
                )
                bar.validate()
                candles[day] = row
            if len(candles) != (stop - cursor).days:
                raise ValueError(f"incomplete Coinbase coverage: {product} {cursor} {stop}")
            with db:
                for day, raw in candles.items():
                    body = json.dumps(raw)
                    prior = db.execute(
                        "SELECT body FROM candles WHERE product=? AND day=?", (product, str(day))
                    ).fetchone()
                    if prior and prior[0] != body:
                        raise ValueError("historical candle revision; preserve first capture")
                    db.execute(
                        "INSERT OR IGNORE INTO candles VALUES (?, ?, ?, ?)",
                        (product, str(day), body, datetime.now(UTC).isoformat()),
                    )
        cursor = stop
    rows = db.execute(
        "SELECT day, body FROM candles WHERE product=? AND day>=? AND day<? ORDER BY day",
        (product, str(start), str(end)),
    ).fetchall()
    bars = []
    for day, body in rows:
        row = json.loads(body)
        bars.append(
            Bar(
                date.fromisoformat(day),
                float(row[3]),
                float(row[2]),
                float(row[1]),
                float(row[4]),
                float(row[5]),
            )
        )
    validate_history(bars, start, end)
    return bars


def observe(db, config, now, fetch=public_get):
    """No backfilled signals/fills: capture only the current date after 00:05 UTC."""
    today = now.date()
    if now.hour == 0 and now.minute < 5:
        return
    if db.execute("SELECT 1 FROM observation WHERE day=?", (str(today),)).fetchone():
        return
    signals = {}
    for product in config["products"]:
        bars = history(db, product, today - timedelta(days=180), today, fetch)
        signals[product] = {
            str(n): {
                "signal": "long"
                if bars[-1].close > sum(b.close for b in bars[-n:]) / n
                else "cash",
                "signal_close": bars[-1].close,
                "sma": sum(b.close for b in bars[-n:]) / n,
            }
            for n in config["lookbacks"]
        }
    body = {
        "observed_at": now.isoformat(),
        "completed_candle_day": str(today - DAY),
        "signals": signals,
        "kind": "observation_only_no_simulated_fill",
    }
    with db:
        db.execute(
            "INSERT OR IGNORE INTO observation VALUES (?, ?)",
            (str(today), json.dumps(body, sort_keys=True)),
        )


def cycle(db, now, fetch=public_get):
    config = protocol()
    stored = db.execute("SELECT body FROM report WHERE id=1").fetchone()
    if not stored:
        histories = {
            p: history(
                db,
                p,
                date.fromisoformat(config["history_start"]),
                date.fromisoformat(config["windows"]["holdout"][1]),
                fetch,
            )
            for p in config["products"]
        }
        report = evaluate(histories, config)
        report["data_hash"] = digest(
            {
                p: [[str(b.day), b.open, b.high, b.low, b.close, b.volume] for b in bars]
                for p, bars in histories.items()
            }
        )
        report["computed_at"] = now.isoformat()
        with db:
            db.execute("INSERT INTO report VALUES (1, ?)", (json.dumps(report),))
    else:
        report = json.loads(stored[0])
    observe(db, config, now, fetch)
    last = db.execute("SELECT body FROM observation ORDER BY day DESC LIMIT 1").fetchone()
    return {
        "status": "observing",
        "checked_at": now.isoformat(),
        "replay": report,
        "observation_days": db.execute("SELECT count(*) FROM observation").fetchone()[0],
        "latest_observation": json.loads(last[0]) if last else None,
        "forward_trades": 0,
        "can_trade_live": False,
    }


def write_summary(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as file:
        json.dump(value, file, sort_keys=True, allow_nan=False)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def main():
    if os.environ.get("SIGNER_ENABLED", "false").lower() != "false":
        raise RuntimeError("paper-only worker requires signing disabled")
    root = Path(os.environ.get("TREND_RESEARCH_DIR", "/data/trend"))
    root.mkdir(parents=True, exist_ok=True)
    db = database(root / "research.sqlite3")
    while True:
        now = datetime.now(UTC)
        try:
            summary = cycle(db, now)
        except Exception as exc:  # noqa: BLE001 - daemon boundary records blocked readiness
            # Provider failures never become an empty successful replay.
            summary = {
                "status": "blocked",
                "checked_at": now.isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc)[:250],
                "can_trade_live": False,
            }
        write_summary(root / "summary.json", summary)
        print(json.dumps(summary), flush=True)
        time.sleep(300)


if __name__ == "__main__":
    main()
