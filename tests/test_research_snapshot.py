from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.control_models
import app.evaluation_models
import app.forward_models
import app.hyperliquid_forward_models
import app.lifecycle_models
import app.venues.hyperliquid_models
from app.config import Settings
from app.models import Base
from app.research_snapshot import SNAPSHOT_SCHEMA, build_research_snapshot

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 3, 10, 30, tzinfo=timezone.utc)


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_empty_snapshot_is_bounded_and_explicitly_non_executable():
    db = db_session()
    snapshot = build_research_snapshot(db, settings=Settings(signer_enabled=False), now=NOW)
    assert snapshot["schema"] == SNAPSHOT_SCHEMA
    assert snapshot["captured_at"] == NOW
    assert snapshot["mode"] == "paper-shadow-research-only"
    assert snapshot["studies"] == []
    assert snapshot["incidents"] == []
    assert snapshot["recent_trades"] == []
    assert snapshot["portfolio"]["study_count"] == 0
    assert snapshot["safety"] == {
        "can_trade_live": False,
        "can_sign": False,
        "can_move_funds": False,
        "shell_access": False,
        "wallet_access": False,
        "signer_enabled": False,
        "live_capital_usd": 0,
    }


def test_snapshot_refuses_signer_enabled_configuration():
    db = db_session()
    with pytest.raises(RuntimeError, match="SIGNER_ENABLED=true"):
        build_research_snapshot(db, settings=Settings(signer_enabled=True), now=NOW)


def test_snapshot_reader_roles_receive_only_specific_required_hyperliquid_tables():
    files = [
        ROOT / "deploy" / "compose.dashboard-local.yml",
        ROOT / "deploy" / "compose.dashboard-tunnel.yml",
        ROOT / "deploy" / "compose.controls.yml",
    ]
    required = {
        "hyperliquid_carry_positions",
        "hyperliquid_perp_snapshots",
        "hyperliquid_funding_snapshots",
    }
    for path in files:
        text = path.read_text()
        for table in required:
            assert table in text
        assert "GRANT SELECT ON ALL TABLES" not in text
        assert "GRANT ALL" not in text
