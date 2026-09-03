from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.forward_models
from app.forward_models import ForwardStudy
from app.models import Base
from app.research_snapshot import render_research_snapshot_text
from app.scan_telemetry import record_scan_observation, scan_activity_summary

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        ForwardStudy(
            id="study-1", external_id="scan-test", strategy_version_id="version-1",
            experiment_id="experiment-1", family="meme", venue="solana",
            instrument="PUMP_LAUNCH_BASELINE", status="active", initial_capital_usd=1000,
            evaluation_policy_json="{}", study_config_json="{}", started_at=NOW - timedelta(hours=2),
        )
    )
    db.commit()
    return db


def test_scan_observations_are_idempotent_and_summarized():
    db = db_session()
    first = record_scan_observation(
        db, study_id="study-1", external_key="candidate:a", observation_kind="candidate",
        observed_at=NOW - timedelta(minutes=2), examined_count=1, rejected_count=1,
        rejection_reasons={"MINT_AUTHORITY_NOT_REVOKED": 1}, metadata={"stage": "safety"},
    )
    again = record_scan_observation(
        db, study_id="study-1", external_key="candidate:a", observation_kind="candidate",
        observed_at=NOW, examined_count=1, rejected_count=1,
        rejection_reasons={"MINT_AUTHORITY_NOT_REVOKED": 1}, metadata={"stage": "safety"},
    )
    assert again.id == first.id
    record_scan_observation(
        db, study_id="study-1", external_key="candidate:b", observation_kind="candidate",
        observed_at=NOW - timedelta(minutes=1), examined_count=1, accepted_count=1,
    )
    record_scan_observation(
        db, study_id="study-1", external_key="cycle:1", observation_kind="cycle",
        observed_at=NOW, metadata={"launches_in_window": 17, "features_ready": 2, "quote_attempts": 1},
    )
    activity = scan_activity_summary(db, study_id="study-1", now=NOW)
    assert activity["cycles"] == 1
    assert activity["examined"] == 2
    assert activity["accepted"] == 1
    assert activity["rejected"] == 1
    assert activity["top_rejection_reasons"] == [{"reason": "MINT_AUTHORITY_NOT_REVOKED", "count": 1}]
    assert activity["metadata_totals"]["launches_in_window"] == 17


def test_research_text_explains_zero_trade_scan_activity():
    text = render_research_snapshot_text(
        {
            "captured_at": NOW,
            "portfolio": {"simulated_latest_nav_usd": 1000, "net_pnl_usd": 0, "return_pct": 0, "unresolved_incidents": 0},
            "studies": [{
                "venue": "solana", "strategy_name": "Solana Pump Safety Baseline", "study_status": "active",
                "latest_nav_usd": 1000, "net_pnl_usd": 0, "return_pct": 0, "closed_trades": 0,
                "operational": {"state": "ready", "hard_reasons": [], "warnings": []},
                "latest_evaluation": {},
                "activity": {
                    "tracking": True, "cycles": 12, "examined": 7, "accepted": 0, "rejected": 7,
                    "metadata_totals": {"launches_in_window": 42, "features_ready": 7, "quote_attempts": 0},
                    "top_rejection_reasons": [{"reason": "MINT_AUTHORITY_NOT_REVOKED", "count": 5}],
                },
            }],
        }
    )
    assert "Activity 24h: scans 12 | examined 7 | passed 0 | rejected 7" in text
    assert "launch-window observations 42" in text
    assert "MINT_AUTHORITY_NOT_REVOKED 5" in text


def test_duplicate_cycle_bucket_is_non_blocking_even_if_detail_changes():
    db = db_session()
    first = record_scan_observation(
        db, study_id="study-1", external_key="cycle:same", observation_kind="cycle",
        observed_at=NOW, metadata={"launches_in_window": 10},
    )
    again = record_scan_observation(
        db, study_id="study-1", external_key="cycle:same", observation_kind="cycle",
        observed_at=NOW, metadata={"launches_in_window": 11},
    )
    assert again.id == first.id
    activity = scan_activity_summary(db, study_id="study-1", now=NOW)
    assert activity["cycles"] == 1
    assert activity["metadata_totals"]["launches_in_window"] == 10
