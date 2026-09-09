import json

import pytest

from app.carry_shadow import (
    HOUR,
    advance,
    database,
    forecast,
    funding_cashflow,
    protocol,
    rates_between,
    save_funding,
    valuation,
    walk,
)

NOW = 1000 * HOUR + 600000


def setup(tmp_path):
    db = database(tmp_path / "carry.db")
    save_funding(
        db, [{"coin": "BTC", "time": i * HOUR, "fundingRate": "0.0001"} for i in range(280, 1001)]
    )
    return db


def market(now=NOW):
    return {
        "spot_coin": "@1",
        "oracle": 100,
        "captured_ms": now - 10,
        "quantity_decimals": 4,
        "identity": {"base": "UBTC", "quote": "USDC", "index": 1},
    }


def book(coin="@1", now=NOW):
    return {
        "coin": coin,
        "time": now - 10,
        "levels": [[{"px": "99.99", "sz": "100"}], [{"px": "100.01", "sz": "100"}]],
    }


def tick(db, now=NOW):
    return advance(db, now, market(now), book(now=now), book("BTC", now))


def test_forecast_uses_minimum_trailing_means_and_rejects_gap(tmp_path):
    db = setup(tmp_path)
    assert forecast(db, NOW, 336) == pytest.approx(0.0336)
    with db:
        db.execute("UPDATE funding SET rate=-.0001 WHERE time>?", (832 * HOUR,))
    assert forecast(db, NOW, 336) == pytest.approx(-0.0336)
    with db:
        db.execute("DELETE FROM funding WHERE time=?", (999 * HOUR,))
    with pytest.raises(ValueError, match="missing"):
        forecast(db, NOW, 336)


def test_realized_funding_uses_prior_oracle_never_later_price(tmp_path):
    db = setup(tmp_path)
    with db:
        db.execute("INSERT INTO oracle VALUES (?, ?)", (1000 * HOUR - 10000, 100))
        db.execute("INSERT INTO oracle VALUES (?, ?)", (1000 * HOUR + 1, 999999))
    p = {"opened_ms": 999 * HOUR + 1, "quantity": 4}
    assert funding_cashflow(db, p, 1000 * HOUR) == pytest.approx(0.04)
    with db:
        db.execute("DELETE FROM oracle WHERE time<?", (1000 * HOUR,))
    with pytest.raises(ValueError, match="oracle"):
        funding_cashflow(db, p, 1000 * HOUR)


def test_exact_two_leg_fees_and_adverse_prices():
    p = {"quantity": 4, "spot_quote": 100, "perp_quote": 100}
    result = valuation(p, 100, 100, 2, protocol())
    assert result["hedge_price_pnl_usd"] == pytest.approx(-0.32)
    assert result["fees_usd"] == pytest.approx(0.92)
    assert result["net_pnl_usd"] == pytest.approx(0.76)
    assert valuation(p, 100, 100, 2, protocol(), 2)["net_pnl_usd"] < 0


def test_restart_does_not_duplicate_entries_and_full_capital_is_reserved(tmp_path):
    db = setup(tmp_path)
    first = tick(db)
    assert all(b["status"] == "opened_conditional_shadow" for b in first["books"])
    for b in first["books"]:
        assert b["position"]["reserve"] > 190
        assert b["position"]["margin"] == pytest.approx(399.880008)
        assert (
            b["decision"]["projected_return_on_full_book"] < b["decision"]["net_edge_bps"] / 10000
        )
    db.close()
    db = database(tmp_path / "carry.db")
    tick(db, NOW + 60000)
    tick(db, NOW + 60000)
    assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_monitoring_gap_closes_and_freezes_reentry(tmp_path):
    db = setup(tmp_path)
    tick(db)
    result = tick(db, NOW + 240000)
    assert all(b["contaminated"] and b["closed"] == 1 for b in result["books"])
    assert all(b["last_close"]["reason"] == "monitoring_gap_exit" for b in result["books"])
    assert all(b["status"] == "frozen" for b in tick(db, NOW + 300000)["books"])


def test_unpriceable_exit_keeps_position_and_unknown_nav(tmp_path):
    db = setup(tmp_path)
    tick(db)
    empty = book("BTC", NOW + 60000)
    empty["levels"] = [[], []]
    result = advance(db, NOW + 60000, market(NOW + 60000), book(now=NOW + 60000), empty)
    assert all(b["position"] and b["marked_nav_usd"] is None for b in result["books"])
    assert all(b["closed"] == 0 for b in result["books"])


@pytest.mark.parametrize("fault", ["stale", "future", "crossed", "depth", "nan"])
def test_invalid_book_rejected(fault):
    b = book()
    if fault == "stale":
        b["time"] = NOW - 10001
    elif fault == "future":
        b["time"] = NOW + 1
    elif fault == "crossed":
        b["levels"][0][0]["px"] = "101"
    elif fault == "depth":
        b["levels"][1][0]["sz"] = "0.1"
    else:
        b["levels"][1][0]["px"] = "nan"
    with pytest.raises(ValueError):
        walk(b, "buy", 4, NOW)


def test_identity_revision_rejected(tmp_path):
    db = setup(tmp_path)
    tick(db)
    changed = market(NOW + 60000)
    changed["identity"]["index"] = 99
    with pytest.raises(ValueError, match="identity"):
        advance(db, NOW + 60000, changed, book(now=NOW + 60000), book("BTC", NOW + 60000))


def test_funding_revision_and_missing_hour_rejected(tmp_path):
    db = setup(tmp_path)
    with pytest.raises(ValueError, match="revision"):
        save_funding(db, [{"coin": "BTC", "time": 1000 * HOUR, "fundingRate": "0.001"}])
    with pytest.raises(ValueError, match="missing"):
        rates_between(db, 1000 * HOUR, 1001 * HOUR)


def test_horizon_close_charges_costs_once(tmp_path):
    db = setup(tmp_path)
    tick(db)
    with db:
        for horizon, body in db.execute("SELECT horizon,body FROM books").fetchall():
            b = json.loads(body)
            b["position"]["target_ms"] = NOW + 60000
            db.execute("UPDATE books SET body=? WHERE horizon=?", (json.dumps(b), horizon))
    result = tick(db, NOW + 60000)
    assert all(b["closed"] == 1 and b["capital"] < 1000 for b in result["books"])
    tick(db, NOW + 60000)
    assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 6


def test_missing_oracle_cannot_close_as_zero_funding_profit(tmp_path):
    db = setup(tmp_path)
    tick(db)
    next_hour = 1001*HOUR+60000
    save_funding(db, [{"coin": "BTC", "time": 1001*HOUR, "fundingRate": "-.0001"}])
    result = tick(db, next_hour)
    for b in result["books"]:
        assert b["contaminated"]
        assert b["closed"] == 0
        assert b["status"] == "closed_pending_funding_accounting"
        assert b["marked_nav_usd"] is None


def test_perp_price_spike_triggers_margin_exit(tmp_path):
    db = setup(tmp_path)
    tick(db)
    now = NOW+60000
    perp = book("BTC", now)
    perp["levels"] = [[{"px": "159.99", "sz": "100"}], [{"px": "160.01", "sz": "100"}]]
    result = advance(db, now, market(now), book(now=now), perp)
    assert all(b["last_close"]["reason"] == "margin_guard" for b in result["books"])
    assert all(b["last_close"]["net_pnl_usd"] < -200 for b in result["books"])
