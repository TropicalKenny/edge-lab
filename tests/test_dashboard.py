from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.forward_models import ForwardNavObservation, ForwardStudy, ForwardStudyIncident, ForwardTradeRecord
from app.main import app
from app.models import Base, Experiment, Strategy, StrategyVersion

ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session):
    strategy = Strategy(slug="dashboard-test", name="Dashboard Test", status="red")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        config_json="{}",
        code_sha="dashboard-test",
        immutable=True,
    )
    db.add(version)
    db.flush()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="dashboard observability",
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
        external_id="dashboard-study",
        strategy_version_id=version.id,
        experiment_id=experiment.id,
        family="other",
        venue="test-venue",
        instrument="TEST",
        status="active",
        initial_capital_usd=Decimal("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    db.add(study)
    db.flush()
    db.add_all(
        [
            ForwardNavObservation(
                study_id=study.id,
                observed_at=datetime(2026, 8, 12, 12, tzinfo=timezone.utc),
                nav_usd=Decimal("1000"),
                source="test",
            ),
            ForwardNavObservation(
                study_id=study.id,
                observed_at=datetime(2026, 8, 13, 6, tzinfo=timezone.utc),
                nav_usd=Decimal("1012"),
                source="test",
            ),
            ForwardTradeRecord(
                study_id=study.id,
                external_key="dashboard-trade",
                opened_at=datetime(2026, 8, 13, 4, tzinfo=timezone.utc),
                closed_at=datetime(2026, 8, 13, 5, tzinfo=timezone.utc),
                gross_pnl_usd=Decimal("12"),
                net_pnl_usd=Decimal("10"),
                fees_usd=Decimal("1"),
                slippage_usd=Decimal("1"),
                allocated_capital_usd=Decimal("100"),
                planned_loss_usd=Decimal("2"),
                metadata_json="{}",
            ),
            ForwardStudyIncident(
                study_id=study.id,
                external_key="dashboard-warning",
                severity="warning",
                code="DASHBOARD_WARNING",
                message="test warning",
                data_integrity=False,
                resolved=False,
                opened_at=datetime(2026, 8, 13, 5, tzinfo=timezone.utc),
            ),
            # Data-integrity contamination is permanent evidence state even when the
            # operational incident itself is later marked resolved.
            ForwardStudyIncident(
                study_id=study.id,
                external_key="dashboard-integrity",
                severity="critical",
                code="DASHBOARD_INTEGRITY",
                message="resolved operationally but permanently contaminates the frozen study",
                data_integrity=True,
                resolved=True,
                opened_at=datetime(2026, 8, 12, 18, tzinfo=timezone.utc),
                resolved_at=datetime(2026, 8, 12, 19, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()
    return study


def test_dashboard_summary_is_read_only_and_aggregates_research_state():
    db = _session()
    study = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/dashboard/api/summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "read-only-dashboard"
        assert payload["capital_scope"] == "independent-simulated-forward-study-bankrolls"
        assert payload["safety"] == {
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "vault_accessible": False,
            "signer_enabled": False,
            "live_capital_usd": "0",
        }
        assert payload["portfolio"]["label"] == "aggregate simulated research capital"
        assert payload["portfolio"]["study_count"] == 1
        assert Decimal(payload["portfolio"]["simulated_latest_nav_usd"]) == Decimal("1012")
        assert Decimal(payload["portfolio"]["latest_nav_usd"]) == Decimal("1012")
        assert Decimal(payload["portfolio"]["net_pnl_usd"]) == Decimal("10")
        assert payload["portfolio"]["closed_trades"] == 1
        assert payload["portfolio"]["unresolved_incidents"] == 1
        assert payload["portfolio"]["permanent_data_integrity_incidents"] == 1
        assert payload["portfolio"]["contaminated_study_count"] == 1
        assert Decimal(payload["portfolio"]["worst_observed_study_drawdown_pct"]) == Decimal("0")
        assert payload["studies"][0]["study_id"] == study.id
        assert payload["studies"][0]["strategy_name"] == "Dashboard Test"
        assert payload["studies"][0]["contaminated"] is True
        assert payload["studies"][0]["data_integrity_incidents"] == 1
        assert len(payload["studies"][0]["nav_history"]) == 2
        assert payload["recent_trades"][0]["strategy_name"] == "Dashboard Test"
        assert payload["incidents"][0]["code"] == "DASHBOARD_WARNING"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_dashboard_page_and_assets_are_local_mobile_ready_and_explicitly_simulated():
    client = TestClient(app)
    page = client.get("/dashboard")
    css = client.get("/dashboard/assets/dashboard.css")
    js = client.get("/dashboard/assets/dashboard.js")
    assert page.status_code == css.status_code == js.status_code == 200
    assert 'name="viewport"' in page.text
    assert "/dashboard/assets/dashboard.css" in page.text
    assert "/dashboard/assets/dashboard.js" in page.text
    assert "https://" not in page.text
    assert "http://" not in page.text
    assert "Aggregate simulated NAV" in page.text
    assert "Live capital" in page.text
    assert "Every dollar shown as NAV" in page.text
    assert "@media(max-width:760px)" in css.text
    assert "fetch('/dashboard/api/summary'" in js.text
    assert "live_capital_usd" in js.text
    assert "/execute" not in js.text
    assert "method:'POST'" not in js.text


def test_dashboard_api_exposes_get_only_routes():
    schema = app.openapi()
    paths = {
        path: methods
        for path, methods in schema["paths"].items()
        if path.startswith("/dashboard")
    }
    assert paths
    assert all(set(methods).issubset({"get", "parameters"}) for methods in paths.values())


def test_dashboard_static_assets_are_repository_local():
    html = (ROOT / "app" / "static" / "dashboard" / "index.html").read_text()
    assert "cdn" not in html.lower()
    assert "unpkg" not in html.lower()
    assert "jsdelivr" not in html.lower()
