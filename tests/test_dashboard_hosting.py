from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard_server import app


ROOT = Path(__file__).resolve().parents[1]


def _line_with(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def test_hosted_asgi_exposes_dashboard_only():
    client = TestClient(app)
    assert client.get('/healthz').status_code == 200
    assert client.get('/dashboard').status_code == 200
    assert client.get('/signer/status').status_code == 404
    assert client.get('/venues/hyperliquid/status').status_code == 404
    assert client.post('/risk/evaluate', json={}).status_code == 404
    assert client.post('/venues/polymarket/scan').status_code == 404


def test_cloudflared_reaches_isolated_dashboard_with_readonly_db_role():
    text = (ROOT / "deploy" / "compose.dashboard-tunnel.yml").read_text()
    assert "cloudflare/cloudflared" in text
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}" in text
    assert 'profiles: ["dashboard"]' in text
    assert "CREATE ROLE edge_dashboard LOGIN PASSWORD" in text
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO edge_dashboard" in text
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE edge" in text
    assert "postgresql+psycopg://edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert "app.dashboard_server:app" in text
    assert text.count("ports: []") >= 2
    assert "dashboard_edge:" in text
    assert "cap_drop:" in text
    assert "no-new-privileges:true" in text
    assert "JUPITER_API_KEY" not in text
    assert "HELIUS_API_KEY" not in text
    assert "GOPLUS_ACCESS_TOKEN" not in text
    command = _line_with(text, "command: [\"tunnel\"")
    assert "--token" not in command


def test_dashboard_tunnel_launcher_fails_closed_and_targets_dashboard_only():
    text = (ROOT / "deploy" / "start-dashboard-tunnel.sh").read_text()
    assert "DASHBOARD_DB_PASSWORD is required" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN is required" in text
    assert "Dashboard DB password must be separate" in text
    assert "Refusing to start with an example Cloudflare Tunnel token" in text
    assert "SIGNER_ENABLED != false" in text
    assert "export SIGNER_ENABLED=false" in text
    assert "dashboard-db-role dashboard cloudflared" in text
    assert "http://dashboard:8080" in text
    assert "http://api:8000" not in text


def test_hardened_forward_network_exposes_only_internal_api_loopback():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in text
    postgres = text.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis = text.split("  redis:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "ports: []" in postgres
    assert "ports: []" in redis


def test_dashboard_hosting_runbook_routes_public_hostname_only_to_dashboard_service():
    text = (ROOT / "docs" / "DASHBOARD_V1.md").read_text()
    assert "Create the Cloudflare Access application before publishing the tunnel hostname" in text
    assert "owner-only Allow policy" in text
    assert "Protect with Access" in text
    assert "http://dashboard:8080" in text
    assert "Do not point the tunnel at `api:8000`" in text
    assert "edge_dashboard" in text
    assert "SELECT-only" in text


def test_example_env_contains_blank_hosting_secrets_only():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert _line_with(text, "CLOUDFLARE_TUNNEL_TOKEN=") == "CLOUDFLARE_TUNNEL_TOKEN="
    assert _line_with(text, "DASHBOARD_DB_PASSWORD=") == "DASHBOARD_DB_PASSWORD="
