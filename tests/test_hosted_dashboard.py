from pathlib import Path

from fastapi.testclient import TestClient

from app.dashboard_server import app


ROOT = Path(__file__).resolve().parents[1]


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_dashboard_server_exposes_only_dashboard_surface():
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/signer/status").status_code == 404
    assert client.get("/venues/hyperliquid/status").status_code == 404
    assert client.post("/risk/evaluate", json={}).status_code == 404
    assert client.post("/venues/polymarket/scan").status_code == 404


def test_hosted_compose_uses_isolated_dashboard_and_no_host_ports():
    text = (ROOT / "deploy" / "compose.hosted.yml").read_text()
    dashboard = _section(text, "  dashboard:\n", "\n  cloudflared:\n")
    cloudflared = _section(text, "  cloudflared:\n", "\nnetworks:\n")

    assert "app.dashboard_server:app" in dashboard
    assert 'SIGNER_ENABLED: "false"' in dashboard
    assert "postgresql+psycopg://edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in dashboard
    assert "ports: []" in dashboard
    assert "cap_drop:\n      - ALL" in dashboard
    assert "no-new-privileges:true" in dashboard

    assert "cloudflare/cloudflared:2026.7.3" in cloudflared
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}" in cloudflared
    assert "--token" not in cloudflared
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in _section(
        cloudflared, "    command:\n", "    depends_on:\n"
    )
    assert "ports: []" in cloudflared
    assert "cap_drop:\n      - ALL" in cloudflared
    assert "no-new-privileges:true" in cloudflared

    assert "JUPITER_API_KEY" not in text
    assert "HELIUS_API_KEY" not in text
    assert "GOPLUS_ACCESS_TOKEN" not in text


def test_hosted_networks_separate_tunnel_database_and_internal_api():
    text = (ROOT / "deploy" / "compose.hosted.yml").read_text()
    postgres = _section(text, "  postgres:\n", "\n  dashboard-db-role:\n")
    role = _section(text, "  dashboard-db-role:\n", "\n  dashboard:\n")
    dashboard = _section(text, "  dashboard:\n", "\n  cloudflared:\n")
    cloudflared = _section(text, "  cloudflared:\n", "\nnetworks:\n")
    network_defs = text.split("\nnetworks:\n", 1)[1]

    assert "- default" in postgres
    assert "- dashboard_data" in postgres
    assert "networks:\n      - dashboard_data" in role
    assert "networks:\n      - dashboard_data\n      - dashboard_edge" in dashboard
    assert "networks:\n      - dashboard_edge" in cloudflared
    assert "dashboard_data" not in cloudflared
    assert "      - default" not in cloudflared
    assert "      - default" not in dashboard
    assert "dashboard_data:\n    internal: true" in network_defs


def test_dashboard_db_role_is_select_only_and_password_is_not_a_psql_argument():
    text = (ROOT / "deploy" / "compose.hosted.yml").read_text()
    role = _section(text, "  dashboard-db-role:\n", "\n  dashboard:\n")

    assert "DASHBOARD_DB_PASSWORD: ${DASHBOARD_DB_PASSWORD:?set DASHBOARD_DB_PASSWORD}" in role
    assert "\\getenv dashboard_password DASHBOARD_DB_PASSWORD" in role
    assert "-v dashboard_password" not in role
    assert "GRANT CONNECT ON DATABASE edge TO edge_dashboard" in role
    assert "GRANT USAGE ON SCHEMA public TO edge_dashboard" in role
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO edge_dashboard" in role
    assert "GRANT INSERT" not in role
    assert "GRANT UPDATE" not in role
    assert "GRANT DELETE" not in role


def test_hosted_launcher_keeps_internal_api_private_and_routes_tunnel_to_dashboard():
    hosted = (ROOT / "deploy" / "start-hosted.sh").read_text()
    forward = (ROOT / "deploy" / "compose.forward.yml").read_text()

    assert "DASHBOARD_DB_PASSWORD is required" in hosted
    assert "at least 24 characters" in hosted
    assert "URL-safe A-Z, a-z, 0-9, _ and -" in hosted
    assert "CLOUDFLARE_TUNNEL_TOKEN is required" in hosted
    assert "Refusing to start with an example Cloudflare Tunnel token" in hosted
    assert "SIGNER_ENABLED != false" in hosted
    assert "export SIGNER_ENABLED=false" in hosted
    assert "http://dashboard:8080" in hosted
    assert "http://api:8000" not in hosted
    assert "up -d --build dashboard-db-role dashboard cloudflared" in hosted
    assert '"127.0.0.1:8000:8000"' in forward


def test_example_env_never_contains_real_hosted_secrets_and_pins_cloudflared():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    tunnel_line = next(
        line for line in text.splitlines() if line.startswith("CLOUDFLARE_TUNNEL_TOKEN=")
    )
    dashboard_db_line = next(
        line for line in text.splitlines() if line.startswith("DASHBOARD_DB_PASSWORD=")
    )

    assert tunnel_line == "CLOUDFLARE_TUNNEL_TOKEN="
    assert dashboard_db_line == "DASHBOARD_DB_PASSWORD="
    assert "CLOUDFLARED_IMAGE=cloudflare/cloudflared:2026.7.3" in text
    assert "Never commit the real file" in text
