"""Bounded read-only projection of isolated research, never counted as portfolio P&L."""

import json
from datetime import UTC, datetime
from pathlib import Path


def trend_snapshot(now=None, path=Path("/data/trend/summary.json")):
    now = now or datetime.now(UTC)
    try:
        with path.open() as file:
            raw = file.read(100001)
        if len(raw) > 100000:
            raise ValueError("oversized research summary")
        value = json.loads(raw)
        checked = datetime.fromisoformat(value["checked_at"])
        age = (now - checked).total_seconds()
        value["stale"] = not 0 <= age < 900
        if value["stale"]:
            value["status"] = "stale"
        return value
    except FileNotFoundError:
        return {"status": "not_available_in_this_reader", "can_trade_live": False}
    except (ValueError, KeyError, TypeError, OSError):
        return {"status": "invalid_summary", "can_trade_live": False}
