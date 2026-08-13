from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.forward_models import ForwardNavObservation, ForwardStudy, ForwardStudyIncident
from app.main import app
from app.models import Base, Experiment, Strategy, StrategyVersion
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session):
    strategy = Strategy(slug="ops-test", name="Ops Test", family="funding", status="RED")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        config_json="{}",
        code_ref="test",
        immutable=True,
    )
    db.add(version)
    db.flush()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="ops",
        status="running",
        data_version="test",
        parameter_space_json="{}",
        cost_assumptions_json="{}",
    )
    db.add(experiment)
    db.flush()
    study = ForwardStudy(
        external_id="ops-study",
        strategy_version_id=version.id,
        experiment_id=experiment.id,
        family="funding",
        venue="hyperliquid",
        instrument="BTC",
        status="active",
        initial_capital_usd=Decimal("1000"),
        evaluation_policy_json="{}",
        study_config_json='{"runner":"hyperliquid_carry_v1"}',
        started_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    )
    db.add(study)
    db.flush()
    db.add(
        ForwardNavObservation(
            study_id=study.id,
            observed_at=datetime.now(timezone.utc),
            nav_usd=Decimal("1005"),
            source="test",
        )
    )
    db.add(
        ForwardStudyIncident(
            study_id=study.id,
            external_key="integrity-test",
            severity="error",
            code="TEST_INTEGRITY",
            message="test contamination",
            data_integrity=True,
            resolved=False,
            opened_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return study


def test_forward_ops_summary_is_read_only_and_surfaces_contamination():
    db = _session()
    study = _seed(db)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/forward/ops/summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "read-only-forward-observability"
        assert payload["can_trade_live"] is False
        assert payload["can_sign"] is False
        assert payload["can_move_funds"] is False
        assert len(payload["studies"]) == 1
        row = payload["studies"][0]
        assert row["study_id"] == study.id
        assert row["latest_nav_usd"] == "1005.0000000000"
        assert row["unresolved_data_integrity_incidents"] == 1
        assert row["contaminated"] is True
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_forward_ops_incidents_defaults_to_unresolved_only():
    db = _session()
    study = _seed(db)
    db.add(
        ForwardStudyIncident(
            study_id=study.id,
            external_key="resolved-test",
            severity="warning",
            code="RESOLVED",
            message="old",
            data_integrity=False,
            resolved=True,
            opened_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/forward/ops/incidents")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["external_key"] == "integrity-test"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_forward_ops_has_no_write_routes():
    schema = app.openapi()
    ops_paths = {path: methods for path, methods in schema["paths"].items() if path.startswith("/forward/ops")}
    assert ops_paths
    assert all(set(methods).issubset({"get", "parameters"}) for methods in ops_paths.values())
