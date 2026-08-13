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


def test_gateway_mounts_dashboard_but_not_internal_research_routes():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {"/", "/healthz", "/dashboard", "/dashboard/api/summary"}.issubset(paths)
    assert "/risk/evaluate" not in paths
    assert "/paper/simulate" not in paths
    assert not any(path.startswith("/venues/") for path in paths)
    assert not any(path.startswith("/forward/") for path in paths)
    assert not any(path.startswith("/portfolio/") for path in paths)


def test_gateway_disables_docs_and_openapi():
    client = TestClient(app)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_gateway_health_uses_database_and_reports_read_only_safety():
    db = _session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/healthz")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "mode": "dashboard-read-only",
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "vault_accessible": False,
            "signer_enabled": False,
            "live_capital_usd": 0,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_gateway_sets_strict_browser_headers():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    assert response.headers["cache-control"] == "no-store"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'none'" in csp


def test_gateway_rejects_internal_paths():
    client = TestClient(app)
    for path in (
        "/signer/status",
        "/risk/evaluate",
        "/paper/simulate",
        "/venues/hyperliquid/status",
        "/venues/polymarket/status",
        "/venues/solana/status",
        "/forward/ops/studies",
        "/portfolio/allocate",
    ):
        assert client.get(path).status_code == 404
