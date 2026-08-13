from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.dashboard_server import app
from app.database import get_db
from app.models import Base


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_dashboard_gateway_mounts_only_dashboard_and_health_surface():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/" in paths
    assert "/healthz" in paths
    assert "/dashboard" in paths
    assert "/dashboard/api/summary" in paths
    assert "/risk/evaluate" not in paths
    assert "/paper/simulate" not in paths
    assert "/venues/hyperliquid/refresh" not in paths
    assert "/venues/polymarket/scan" not in paths
    assert not any(path.startswith("/forward/") for path in paths)
    assert not any(path.startswith("/portfolio/") for path in paths)


def test_dashboard_gateway_has_no_docs_or_openapi_surface():
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_dashboard_gateway_root_redirects_to_dashboard():
    client = TestClient(app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


def test_dashboard_gateway_health_checks_db_and_safety_state():
    db = _session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/healthz")
        assert response.status_code == 200
        payload = response.json()
        assert payload == {
            "status": "ok",
            "mode": "dashboard-read-only",
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "vault_accessible": False,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_dashboard_gateway_sets_strict_browser_headers():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-store"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_internal_research_routes_are_404_on_hosted_gateway():
    client = TestClient(app)
    for path in (
        "/signer/status",
        "/venues/hyperliquid/status",
        "/venues/polymarket/status",
        "/venues/solana/status",
        "/forward/ops/studies",
    ):
        assert client.get(path).status_code == 404
