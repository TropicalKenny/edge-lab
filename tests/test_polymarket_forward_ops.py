from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.forward_models import ForwardNavObservation
from app.forward_research import ForwardResearchService
from app.models import Base
from app.polymarket_forward_operational import OperationalPolymarketForwardBootstrap
from app.polymarket_forward_ops import study_statuses

D = Decimal


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def settings(**updates) -> Settings:
    base = Settings(
        _env_file=None,
        polymarket_forward_study_external_id="pm-status-v1",
        polymarket_forward_initial_capital_usd=1000,
        polymarket_forward_shadow_delay_ms=0,
        polymarket_forward_health_max_nav_age_seconds=7200,
    )
    return base.model_copy(update=updates)


def test_status_ready_for_frozen_study_with_fresh_nav():
    db = db_session()
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    cfg = settings()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=started,
    )

    report = study_statuses(
        db,
        settings=cfg,
        external_id=study.external_id,
        now=started + timedelta(minutes=1),
    )[0]

    assert report["operational_state"] == "ready"
    assert report["hard_reasons"] == []
    assert report["warnings"] == []
    assert report["strategy_status"] == "red"
    assert report["trade_count"] == 0
    assert report["execution_observation_count"] == 0
    db.close()


def test_status_waits_when_runner_nav_heartbeat_is_stale():
    db = db_session()
    started = datetime.now(timezone.utc) - timedelta(hours=3)
    cfg = settings(polymarket_forward_health_max_nav_age_seconds=3600)
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=started,
    )

    report = study_statuses(
        db,
        settings=cfg,
        external_id=study.external_id,
        now=started + timedelta(hours=2),
    )[0]

    assert report["operational_state"] == "waiting"
    assert report["hard_reasons"] == []
    assert report["warnings"] == ["FORWARD_RUNNER_NAV_STALE"]
    db.close()


def test_status_blocks_integrity_contamination_even_if_incident_is_resolved():
    db = db_session()
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    cfg = settings()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=started,
    )
    opened = started + timedelta(minutes=1)
    ForwardResearchService.record_incident(
        db,
        study_id=study.id,
        external_key="status-integrity",
        severity="critical",
        code="STATUS_INTEGRITY",
        message="synthetic contamination",
        opened_at=opened,
        data_integrity=True,
    )
    ForwardResearchService.resolve_incident(
        db,
        study_id=study.id,
        external_key="status-integrity",
        resolved_at=opened + timedelta(seconds=1),
    )

    report = study_statuses(
        db,
        settings=cfg,
        external_id=study.external_id,
        now=started + timedelta(minutes=2),
    )[0]

    assert report["operational_state"] == "blocked"
    assert "DATA_INTEGRITY_CONTAMINATED" in report["hard_reasons"]
    assert report["data_integrity_failure_count"] == 1
    assert report["unresolved_critical_incident_count"] == 0
    db.close()


def test_status_blocks_initial_nav_mismatch():
    db = db_session()
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    cfg = settings()
    study = OperationalPolymarketForwardBootstrap.bootstrap(
        db,
        settings=cfg,
        now=started,
    )
    nav = db.scalar(
        select(ForwardNavObservation).where(ForwardNavObservation.study_id == study.id)
    )
    assert nav is not None
    nav.nav_usd = D("999")
    db.commit()

    report = study_statuses(
        db,
        settings=cfg,
        external_id=study.external_id,
        now=started + timedelta(minutes=1),
    )[0]

    assert report["operational_state"] == "blocked"
    assert "INITIAL_NAV_MISMATCH" in report["hard_reasons"]
    db.close()
