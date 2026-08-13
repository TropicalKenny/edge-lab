from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text()


def test_dashboard_compose_uses_separate_loopback_port_and_read_only_db_role():
    text = _text("deploy/compose.dashboard.yml")
    assert '"127.0.0.1:8080:8080"' in text
    assert "app.dashboard_server:app" in text
    assert "edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO edge_dashboard" in text
    assert "GRANT INSERT" not in text
    assert "GRANT UPDATE" not in text
    assert "GRANT DELETE" not in text


def test_hardened_research_api_remains_loopback_only():
    text = _text("deploy/compose.forward.yml")
    assert '"127.0.0.1:8000:8000"' in text
    assert 'SIGNER_ENABLED: "false"' in text


def test_forward_launcher_includes_dashboard_overlay_and_refuses_example_secret():
    text = _text("deploy/start-forward.sh")
    assert "deploy/compose.dashboard.yml" in text
    assert "DASHBOARD_DB_PASSWORD is required" in text
    assert "replace-with-a-third-long-random-password" in text
    assert "dashboard-db-role dashboard" in text
    assert "127.0.0.1:8080/dashboard" in text
    assert "127.0.0.1:8000 (do not use as a public tunnel origin)" in text


def test_dashboard_env_example_contains_no_real_secret_or_tunnel_token():
    text = _text("deploy/.env.forward.example")
    assert "DASHBOARD_DB_PASSWORD=replace-with-a-third-long-random-password" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in text
    assert "PRIVATE_KEY" not in text
    assert "SEED_PHRASE" not in text


def test_dashboard_runbook_points_cloudflare_only_at_gateway_port():
    text = _text("docs/DASHBOARD_V1.md")
    assert "Cloudflare Tunnel must target `http://127.0.0.1:8080`" in text
    assert "never port 8000" in text
    assert "SELECT-only" in text
