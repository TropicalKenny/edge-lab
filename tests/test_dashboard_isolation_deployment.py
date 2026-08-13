from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text()


def test_dashboard_service_is_loopback_and_select_only():
    text = _text("deploy/compose.dashboard.yml")
    assert '"127.0.0.1:8080:8080"' in text
    assert "app.dashboard_server:app" in text
    assert "edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO edge_dashboard" in text
    for write_grant in ("GRANT INSERT", "GRANT UPDATE", "GRANT DELETE"):
        assert write_grant not in text


def test_cloudflared_depends_on_dashboard_not_research_api():
    text = _text("deploy/compose.dashboard-tunnel.yml")
    assert "dashboard:" in text
    assert "condition: service_healthy" in text
    assert "api:" not in text
    assert "ports: []" in text


def test_tunnel_launcher_requires_isolated_origin():
    text = _text("deploy/start-dashboard-tunnel.sh")
    assert "deploy/compose.dashboard.yml" in text
    assert "http://dashboard:8080" in text
    assert "Do NOT configure the public hostname to target api:8000" in text
    assert "dashboard-db-role dashboard cloudflared" in text


def test_forward_launcher_starts_gateway_but_keeps_research_api_private():
    launcher = _text("deploy/start-forward.sh")
    hardened = _text("deploy/compose.forward.yml")
    assert "deploy/compose.dashboard.yml" in launcher
    assert "dashboard-db-role dashboard" in launcher
    assert "127.0.0.1:8080/dashboard" in launcher
    assert "never use as the Cloudflare origin" in launcher
    assert '"127.0.0.1:8000:8000"' in hardened


def test_dashboard_has_separate_secret_and_no_wallet_material():
    text = _text("deploy/.env.forward.example")
    assert "DASHBOARD_DB_PASSWORD=replace-with-a-third-long-random-password" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in text
    assert "PRIVATE_KEY" not in text
    assert "SEED_PHRASE" not in text
