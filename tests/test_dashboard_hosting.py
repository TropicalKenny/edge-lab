from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _line_with(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def test_cloudflared_uses_environment_token_publishes_no_port_and_is_gateway_only():
    text = (ROOT / "deploy" / "compose.dashboard-tunnel.yml").read_text()
    assert "cloudflare/cloudflared:latest" in text
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}" in text
    assert 'profiles: ["dashboard"]' in text
    assert "ports: []" in text
    assert "dashboard:" in text
    assert "condition: service_healthy" in text
    assert "- dashboard_gateway" in text
    assert "api:" not in text

    command = _line_with(text, "command:")
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in command
    assert "TUNNEL_TOKEN" not in command
    assert "--token" not in command
    assert "--no-autoupdate" in command


def test_dashboard_tunnel_launcher_fails_closed_and_uses_isolated_origin():
    text = (ROOT / "deploy" / "start-dashboard-tunnel.sh").read_text()
    assert "CLOUDFLARE_TUNNEL_TOKEN is required" in text
    assert "DASHBOARD_DB_PASSWORD is required" in text
    assert "Refusing to start with an example Cloudflare Tunnel token" in text
    assert "SIGNER_ENABLED != false" in text
    assert "export SIGNER_ENABLED=false" in text
    assert "deploy/compose.dashboard.yml" in text
    assert "deploy/compose.dashboard-tunnel.yml" in text
    assert "--profile dashboard" in text
    assert "dashboard-db-role dashboard cloudflared" in text
    assert "http://dashboard:8080" in text
    assert "Do NOT configure the public hostname to target api:8000" in text

    # The secret must be consumed by Compose through the env file, not put on cloudflared's CLI.
    assert "--token $CLOUDFLARE_TUNNEL_TOKEN" not in text
    assert "--token ${CLOUDFLARE_TUNNEL_TOKEN}" not in text


def test_hardened_forward_network_exposes_only_api_and_dashboard_loopback():
    research = (ROOT / "deploy" / "compose.forward.yml").read_text()
    dashboard = (ROOT / "deploy" / "compose.dashboard.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in research
    assert '"127.0.0.1:8080:8080"' in dashboard

    # Both data services are explicitly stripped of inherited host ports.
    postgres = research.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis = research.split("  redis:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "ports: []" in postgres
    assert "ports: []" in redis


def test_dashboard_hosting_runbook_requires_access_and_isolated_gateway():
    text = (ROOT / "docs" / "DASHBOARD_V1.md").read_text()
    assert "owner-only" in text
    assert "Protect with Access" in text
    assert "http://dashboard:8080" in text
    assert "Never target `http://api:8000`" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "dashboard_gateway" in text
    assert "independent simulated" in text.lower()


def test_example_env_contains_separate_dashboard_secret_and_tunnel_placeholder():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert "DASHBOARD_DB_PASSWORD=replace-with-a-third-long-random-password" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in text
    assert "Never commit the real token" in text
    token_line = _line_with(text, "CLOUDFLARE_TUNNEL_TOKEN=")
    assert token_line == "CLOUDFLARE_TUNNEL_TOKEN="
