from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _line_with(text: str, needle: str) -> str:
    return next(line for line in text.splitlines() if needle in line)


def test_cloudflared_uses_environment_token_and_publishes_no_host_port():
    text = (ROOT / "deploy" / "compose.dashboard-tunnel.yml").read_text()
    assert "cloudflare/cloudflared:latest" in text
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?set CLOUDFLARE_TUNNEL_TOKEN}" in text
    assert 'profiles: ["dashboard"]' in text
    assert "ports: []" in text
    assert "http://api:8000" not in text  # remotely managed route belongs in Cloudflare control plane

    command = _line_with(text, "command:")
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in command
    assert "TUNNEL_TOKEN" not in command
    assert "--token" not in command
    assert "--no-autoupdate" in command


def test_dashboard_tunnel_launcher_fails_closed_and_keeps_signer_disabled():
    text = (ROOT / "deploy" / "start-dashboard-tunnel.sh").read_text()
    assert "CLOUDFLARE_TUNNEL_TOKEN is required" in text
    assert "Refusing to start with an example Cloudflare Tunnel token" in text
    assert "SIGNER_ENABLED != false" in text
    assert "export SIGNER_ENABLED=false" in text
    assert "deploy/compose.forward.yml" in text
    assert "deploy/compose.solana-forward.yml" in text
    assert "deploy/compose.dashboard-tunnel.yml" in text
    assert "--profile dashboard" in text
    assert "up -d cloudflared" in text
    assert "http://api:8000" in text

    # The secret must be consumed by Compose through the env file, not put on cloudflared's CLI.
    assert "--token $CLOUDFLARE_TUNNEL_TOKEN" not in text
    assert "--token ${CLOUDFLARE_TUNNEL_TOKEN}" not in text


def test_hardened_forward_network_exposes_only_api_loopback():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in text

    # Both data services are explicitly stripped of inherited host ports.
    postgres = text.split("  postgres:\n", 1)[1].split("\n  redis:\n", 1)[0]
    redis = text.split("  redis:\n", 1)[1].split("\n  migrate:\n", 1)[0]
    assert "ports: []" in postgres
    assert "ports: []" in redis


def test_dashboard_hosting_runbook_requires_access_before_public_hostname():
    text = (ROOT / "docs" / "DASHBOARD_V1.md").read_text()
    assert "Create the Cloudflare Access application before publishing the tunnel hostname" in text
    assert "owner-only Allow policy" in text
    assert "Protect with Access" in text
    assert "http://api:8000" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "Do not publish `/dashboard` directly on an unrestricted VPS port" in text


def test_example_env_contains_only_placeholder_for_tunnel_token():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in text
    assert "Never commit the real token" in text
    token_line = _line_with(text, "CLOUDFLARE_TUNNEL_TOKEN=")
    assert token_line == "CLOUDFLARE_TUNNEL_TOKEN="
