from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.dashboard_server import app
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


def test_hosted_asgi_exposes_dashboard_only_with_db_backed_health():
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


def test_tunnel_compose_isolates_cloudflare_and_uses_exact_select_only_db_role():
    text = (ROOT / "deploy" / "compose.dashboard-tunnel.yml").read_text()
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
    ):
        assert table in text
    assert "postgresql+psycopg://edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert "app.dashboard_server:app" in text
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}" in text
    assert text.count("ports: []") >= 2
    assert "dashboard_edge:" in text
    assert "cap_drop: [ALL]" in text
    assert "no-new-privileges:true" in text
    assert "JUPITER_API_KEY" not in text
    assert "HELIUS_API_KEY" not in text
    assert "GOPLUS_ACCESS_TOKEN" not in text
    command = _line_with(text, 'command: ["tunnel"')
    assert "--token" not in command


def test_launchers_enforce_preflight_and_dashboard_only_origin():
    dashboard = (ROOT / "deploy" / "start-dashboard-tunnel.sh").read_text()
    forward = (ROOT / "deploy" / "start-forward.sh").read_text()
    assert "sh deploy/preflight-forward.sh" in dashboard
    assert "sh deploy/preflight-forward.sh --research-only" in forward
    assert "export SIGNER_ENABLED=false" in dashboard
    assert "dashboard-db-role dashboard cloudflared" in dashboard
    assert "http://dashboard:8080" in dashboard
    assert "http://api:8000" not in dashboard


def test_hardened_forward_network_exposes_only_internal_api_loopback():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in text
    postgres = text.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis = text.split("  redis:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "ports: []" in postgres
    assert "ports: []" in redis


def test_dashboard_hosting_runbook_routes_public_hostname_to_dashboard_service():
    text = (ROOT / "docs" / "DASHBOARD_V1.md").read_text()
    assert "Create the Cloudflare Access application before publishing the tunnel hostname" in text
    assert "owner-only Allow policy" in text
    assert "Protect with Access" in text
    assert "http://dashboard:8080" in text
    assert "Do not point the tunnel at `api:8000`" in text
    assert "edge_dashboard" in text
    assert "exact table" in text.lower()
    assert "future tables" in text.lower()
    assert "SELECT-only" in text


def test_example_env_contains_blank_hosting_secrets():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert _line_with(text, "CLOUDFLARE_TUNNEL_TOKEN=") == "CLOUDFLARE_TUNNEL_TOKEN="
    assert _line_with(text, "DASHBOARD_DB_PASSWORD=") == "DASHBOARD_DB_PASSWORD="
