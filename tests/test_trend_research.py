import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.trend_research import Bar, combined, replay, validate_history
from app.trend_snapshot import trend_snapshot
from app.workers.trend_research import database, history, observe


def bars(n=210):
    return [Bar(date(2025, 1, 1) + timedelta(days=i), 100, 100, 100, 100, 1) for i in range(n)]


def test_flat_buy_hold_loses_exact_two_sided_cost_and_reconciles():
    b = bars()
    r = replay(b, b[190].day, b[-1].day + timedelta(days=1), None, 60, 5)
    expected = 500 * (1 - 0.0005) * (1 - 0.006) / ((1 + 0.0005) * (1 + 0.006))
    assert r["final_cash_usd"] == pytest.approx(expected)
    assert sum(t["net_pnl_usd"] for t in r["trades"]) == pytest.approx(expected - 500)
    assert r["fees_usd"] + r["slippage_usd"] == pytest.approx(500 - expected)
    assert combined([r, r], 1000)["net_pnl_usd"] == pytest.approx(2 * expected - 1000)
    stressed = replay(b, b[190].day, b[-1].day + timedelta(days=1), None, 120, 10)
    assert stressed["final_cash_usd"] < expected


def test_signal_cannot_fill_same_or_next_midnight_open():
    b = bars()
    b[190] = Bar(b[190].day, 100, 200, 100, 200, 1)
    # Day 190 close is known at 191 00:00. Default delayed fill is 192 00:00.
    r = replay(b, b[190].day, b[192].day, 90, 0, 0)
    assert r["trades"] == []
    r = replay(b, b[190].day, b[193].day, 90, 0, 0)
    assert len(r["trades"]) == 1
    assert r["trades"][0]["exit_day"] == str(b[192].day)
    delayed = replay(b, b[190].day, b[193].day, 90, 0, 0, lag_days=2)
    assert delayed["trades"] == []


def test_future_bars_do_not_change_earlier_window():
    b = bars()
    baseline = replay(b, b[190].day, b[200].day, 90, 60, 5)
    for i in range(200, len(b)):
        b[i] = Bar(b[i].day, 10000, 10000, 10000, 10000, 1)
    assert baseline == replay(b, b[190].day, b[200].day, 90, 60, 5)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "nan", "negative", "order"])
def test_bad_history_fails_closed(fault):
    b = bars()
    if fault == "missing":
        del b[5]
    elif fault == "duplicate":
        b[5] = b[4]
    elif fault == "nan":
        b[5] = replace(b[5], close=float("nan"))
    elif fault == "negative":
        b[5] = replace(b[5], low=-1)
    else:
        b[5], b[6] = b[6], b[5]
    with pytest.raises(ValueError):
        validate_history(b, date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=210))


def fake_fetch(product, resource, params):
    start = date.fromisoformat(params["start"][:10])
    end = date.fromisoformat(params["end"][:10])
    return [
        [
            int(datetime.combine(start + timedelta(days=i), datetime.min.time(), UTC).timestamp()),
            100,
            100,
            100,
            100,
            1,
        ]
        for i in range(-1, (end - start).days)
    ]


def test_history_cache_and_restart_observation_idempotency(tmp_path):
    path = tmp_path / "test.db"
    db = database(path)
    now = datetime(2026, 9, 9, 0, 5, tzinfo=UTC)
    cfg = {"products": ["BTC-USD", "ETH-USD"], "lookbacks": [90, 180]}
    observe(db, cfg, now, fake_fetch)
    db.close()
    db = database(path)

    def fail(*args):
        raise AssertionError("already recorded or cached data should not be fetched")

    observe(db, cfg, now + timedelta(hours=3), fail)
    assert db.execute("SELECT count(*) FROM observation").fetchone()[0] == 1
    observation = json.loads(db.execute("SELECT body FROM observation").fetchone()[0])
    assert observation["observed_at"] == now.isoformat()
    assert observation["kind"] == "observation_only_no_simulated_fill"
    history(db, "BTC-USD", now.date() - timedelta(days=180), now.date(), fail)


def test_missing_provider_data_never_becomes_zero_profit(tmp_path):
    db = database(tmp_path / "missing.db")
    with pytest.raises(ValueError, match="incomplete Coinbase coverage"):
        history(db, "BTC-USD", date(2025, 1, 1), date(2025, 1, 5), lambda *a: [])
    assert db.execute("SELECT count(*) FROM candles").fetchone()[0] == 0


def test_changed_protocol_rejected(tmp_path):
    path = tmp_path / "locked.db"
    db = database(path)
    with db:
        db.execute("UPDATE protocol SET body='changed'")
    db.close()
    with pytest.raises(ValueError, match="protocol changed"):
        database(path)


def test_snapshot_marks_stale_and_missing(tmp_path):
    p = tmp_path / "summary.json"
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    assert trend_snapshot(now, p)["status"] == "not_available_in_this_reader"
    p.write_text(json.dumps({"checked_at": now.isoformat(), "status": "observing"}))
    assert trend_snapshot(now, p)["stale"] is False
    assert trend_snapshot(now + timedelta(minutes=16), p)["status"] == "stale"
    assert trend_snapshot(now - timedelta(seconds=1), p)["status"] == "stale"
    p.write_text("corrupt")
    assert trend_snapshot(now, p)["status"] == "invalid_summary"
