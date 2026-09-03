from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.dashboard_server import app, auth, settings
from app.database import get_db
from app.models import Base


ROOT = Path(__file__).resolve().parents[1]


def _line_with(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_hosted_asgi_requires_owner_session_and_keeps_internal_routes_absent(monkeypatch):
    db = _session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok",
            "surface": "dashboard-only",
            "mode": "dashboard-read-only",
            "can_trade_live": False,
            "can_sign": False,
            "can_move_funds": False,
            "vault_accessible": False,
            "signer_enabled": False,
            "live_capital_usd": 0,
        }
        assert client.get("/login").status_code == 200
        unauth = client.get("/dashboard", follow_redirects=False)
        assert unauth.status_code == 303
        assert unauth.headers["location"] == "/login"
        assert client.get("/dashboard/api/summary").status_code == 401

        monkeypatch.setattr(settings, "dashboard_auth_secret", "test-owner-session-secret")
        token = auth.create_session()
        client.cookies.set(auth.cookie_name, token)
        assert client.get("/dashboard").status_code == 200
        for path in (
            "/signer/status",
            "/venues/hyperliquid/status",
            "/forward/ops/studies",
            "/portfolio/allocate",
            "/openapi.json",
            "/docs",
        ):
            assert client.get(path).status_code == 404
        assert client.post("/risk/evaluate", json={}).status_code == 404
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_hosted_asgi_sets_strict_browser_headers():
    response = TestClient(app).get("/login")
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


def test_local_dashboard_compose_is_loopback_only_and_select_only():
    text = (ROOT / "deploy" / "compose.dashboard-local.yml").read_text()
    assert "CREATE ROLE edge_dashboard LOGIN PASSWORD" in text
    assert "default_transaction_read_only = on" in text
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edge_dashboard" in text
    assert "GRANT SELECT ON ALL TABLES" not in text
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE edge IN SCHEMA public REVOKE SELECT ON TABLES FROM edge_dashboard" in text
    for table in (
        "strategies",
        "strategy_versions",
        "strategy_evaluation_runs",
        "forward_studies",
        "forward_nav_observations",
        "forward_study_incidents",
        "forward_trade_records",
        "forward_execution_records",
        "forward_scan_observations",
    ):
        assert table in text
    assert "postgresql+psycopg://edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert "app.dashboard_server:app" in text
    assert '"127.0.0.1:8080:8080"' in text
    assert "DASHBOARD_AUTH_SECRET" in text
    assert "DASHBOARD_RESEND_API_KEY" in text
    assert "DASHBOARD_AUTH_FROM_EMAIL" in text
    assert "cap_drop: [ALL]" in text
    assert "no-new-privileges:true" in text
    assert "JUPITER_API_KEY" not in text
    assert "HELIUS_API_KEY" not in text
    assert "GOPLUS_ACCESS_TOKEN" not in text


def test_hardened_forward_network_exposes_only_internal_api_loopback():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in text
    postgres = text.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis = text.split("  redis:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "ports: []" in postgres
    assert "ports: []" in redis


def test_dashboard_runbook_matches_shared_vps_hosting_and_exact_port():
    text = (ROOT / "docs" / "DASHBOARD_V1.md").read_text()
    assert "Edge Lab is hosted on the VPS" in text
    assert "Authentication belongs to Edge Lab, not Cloudflare Access" in text
    assert "127.0.0.1:8080" in text
    assert "Never route the public dashboard hostname to `8000` or `8090`" in text
    assert "edge_dashboard" in text
    assert "SELECT-only" in text
    assert "DASHBOARD_AUTH_SECRET" in text
    assert "DASHBOARD_RESEND_API_KEY" in text


def test_example_env_contains_blank_dashboard_secrets():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert _line_with(text, "DASHBOARD_DB_PASSWORD=") == "DASHBOARD_DB_PASSWORD="
    assert _line_with(text, "DASHBOARD_AUTH_SECRET=") == "DASHBOARD_AUTH_SECRET="
    assert _line_with(text, "DASHBOARD_RESEND_API_KEY=") == "DASHBOARD_RESEND_API_KEY="
    assert _line_with(text, "DASHBOARD_AUTH_FROM_EMAIL=") == "DASHBOARD_AUTH_FROM_EMAIL="
    assert _line_with(text, "DASHBOARD_OWNER_EMAIL=") == "DASHBOARD_OWNER_EMAIL=fafikennedy20@gmail.com"


def test_scan_telemetry_table_is_explicitly_granted_to_reader_roles():
    for name in ("compose.dashboard-local.yml", "compose.dashboard-tunnel.yml", "compose.controls.yml"):
        assert "forward_scan_observations" in (ROOT / "deploy" / name).read_text()
