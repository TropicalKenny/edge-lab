from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import dashboard
from app.config import Settings
from app.database import get_db
from app.forward_models import ForwardNavObservation, ForwardStudy, ForwardStudyIncident
from app.main import app
from app.models import Base, Experiment, Strategy, StrategyVersion


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _auth_settings() -> Settings:
    return Settings(
        dashboard_username="researcher",
        dashboard_password="correct-horse-battery-staple",
    )


def _seed_study(
    db: Session,
    *,
    slug: str,
    venue: str,
    family: str,
    instrument: str,
    initial_nav: Decimal,
    latest_nav: Decimal,
    started_at: datetime,
) -> ForwardStudy:
    strategy = Strategy(slug=slug, name=slug, status="red")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        config_json="{}",
        code_sha=f"{slug}-sha",
        immutable=True,
    )
    db.add(version)
    db.flush()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="dashboard regression",
        data_version="test",
        train_window="forward-only",
        validation_window="forward-only",
        holdout_window="forward-only",
        search_space_json="{}",
        status="running",
    )
    db.add(experiment)
    db.flush()
    study = ForwardStudy(
        external_id=f"{slug}-study",
        strategy_version_id=version.id,
        experiment_id=experiment.id,
        family=family,
        venue=venue,
        instrument=instrument,
        status="active",
        initial_capital_usd=initial_nav,
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=started_at,
    )
    db.add(study)
    db.flush()
    db.add_all(
        [
            ForwardNavObservation(
                study_id=study.id,
                observed_at=started_at,
                nav_usd=initial_nav,
                source="study-initial-capital",
            ),
            ForwardNavObservation(
                study_id=study.id,
                observed_at=started_at + timedelta(hours=1),
                nav_usd=latest_nav,
                source="test-forward-nav",
            ),
        ]
    )
    db.commit()
    return study


def test_dashboard_fails_closed_when_credentials_are_unset(monkeypatch):
    monkeypatch.setattr(dashboard, "get_settings", lambda: Settings())
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_dashboard_requires_auth_and_sets_browser_security_headers(monkeypatch):
    settings = _auth_settings()
    monkeypatch.setattr(dashboard, "get_settings", lambda: settings)
    client = TestClient(app)

    unauthenticated = client.get("/dashboard")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == 'Basic realm="Edge Lab"'

    rejected = client.get("/dashboard", auth=("researcher", "wrong"))
    assert rejected.status_code == 401

    response = client.get(
        "/dashboard",
        auth=("researcher", "correct-horse-battery-staple"),
    )
    assert response.status_code == 200
    assert "Forward Research Observatory" in response.text
    assert "no live orders" in response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "correct-horse-battery-staple" not in response.text


def test_dashboard_snapshot_is_authenticated_and_never_exposes_credentials(monkeypatch):
    settings = _auth_settings()
    monkeypatch.setattr(dashboard, "get_settings", lambda: settings)
    monkeypatch.setattr(
        dashboard.DashboardService,
        "snapshot",
        staticmethod(
            lambda db, settings: {
                "mode": "read-only-forward-research-observatory",
                "safety": {
                    "can_trade_live": False,
                    "can_sign": False,
                    "can_move_funds": False,
                    "can_promote_strategy": False,
                },
                "engines": [],
            }
        ),
    )

    def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        assert client.get("/dashboard/api/snapshot").status_code == 401
        response = client.get(
            "/dashboard/api/snapshot",
            auth=("researcher", "correct-horse-battery-staple"),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["safety"]["can_trade_live"] is False
        serialized = response.text
        assert "correct-horse-battery-staple" not in serialized
        assert "researcher" not in serialized
        assert response.headers["cache-control"].startswith("no-store")
    finally:
        app.dependency_overrides.clear()


def test_dashboard_aggregates_all_three_frozen_status_engines(monkeypatch):
    db = _session()
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    hyper = _seed_study(
        db,
        slug="dashboard-hyper",
        venue="hyperliquid",
        family="funding",
        instrument="BTC",
        initial_nav=Decimal("1000"),
        latest_nav=Decimal("1010"),
        started_at=now - timedelta(days=2),
    )
    poly = _seed_study(
        db,
        slug="dashboard-poly",
        venue="polymarket",
        family="other",
        instrument="STRUCTURAL_COMPLETE_SET",
        initial_nav=Decimal("1000"),
        latest_nav=Decimal("1005"),
        started_at=now - timedelta(days=2),
    )
    solana = _seed_study(
        db,
        slug="dashboard-solana",
        venue="solana",
        family="meme",
        instrument="PUMP_LAUNCH_BASELINE",
        initial_nav=Decimal("1000"),
        latest_nav=Decimal("990"),
        started_at=now - timedelta(days=2),
    )
    db.add(
        ForwardStudyIncident(
            study_id=solana.id,
            external_key="dashboard-test-warning",
            severity="warning",
            code="TEST_WARNING",
            message="test incident",
            data_integrity=False,
            resolved=False,
            opened_at=now - timedelta(minutes=5),
        )
    )
    db.commit()

    def report(study: ForwardStudy, nav: str, state: str, trades: int):
        return {
            "study_id": study.id,
            "external_id": study.external_id,
            "status": "active",
            "operational_state": state,
            "hard_reasons": [],
            "warnings": ["TEST_WAIT"] if state == "waiting" else [],
            "instrument": study.instrument,
            "started_at": study.started_at,
            "forward_age_days": 2,
            "strategy_slug": f"{study.venue}-strategy",
            "strategy_status": "red",
            "strategy_version": "v1",
            "initial_capital_usd": Decimal("1000"),
            "last_nav_usd": Decimal(nav),
            "open_position_count": 0,
            "trade_count": trades,
            "execution_observation_count": trades * 2,
            "incident_count": 0,
            "data_integrity_failure_count": 0,
            "unresolved_critical_incident_count": 0,
        }

    monkeypatch.setattr(
        dashboard.ForwardOperationsService,
        "study_statuses",
        staticmethod(lambda db, settings, now: [report(hyper, "1010", "ready", 3)]),
    )
    monkeypatch.setattr(
        dashboard,
        "polymarket_study_statuses",
        lambda db, settings, now: [report(poly, "1005", "ready", 4)],
    )
    monkeypatch.setattr(
        dashboard,
        "solana_study_statuses",
        lambda db, settings, now: [report(solana, "990", "waiting", 5)],
    )

    try:
        payload = dashboard.DashboardService.snapshot(
            db,
            settings=Settings(),
            now=now,
        )
        assert {row["venue"] for row in payload["engines"]} == {
            "hyperliquid",
            "polymarket",
            "solana",
        }
        assert payload["overall_state"] == "waiting"
        assert payload["totals"]["active_studies"] == 3
        assert payload["totals"]["ready_studies"] == 2
        assert payload["totals"]["waiting_studies"] == 1
        assert payload["totals"]["initial_nav_usd"] == Decimal("3000")
        assert payload["totals"]["current_nav_usd"] == Decimal("3005")
        assert payload["totals"]["pnl_usd"] == Decimal("5")
        assert payload["totals"]["closed_trades"] == 12
        assert len(payload["nav_series"]) == 3
        assert payload["incidents"][0]["code"] == "TEST_WARNING"
        assert payload["safety"] == {
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "can_promote_strategy": False,
        }
    finally:
        db.close()


def test_dashboard_surface_has_no_write_routes():
    schema = app.openapi()
    paths = {
        path: methods
        for path, methods in schema["paths"].items()
        if path.startswith("/dashboard")
    }
    assert paths
    assert all(set(methods).issubset({"get", "parameters"}) for methods in paths.values())
