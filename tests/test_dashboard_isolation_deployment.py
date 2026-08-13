from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text()


def test_dashboard_service_is_loopback_and_exact_table_select_only():
    text = _text("deploy/compose.dashboard.yml")
    assert '"127.0.0.1:8080:8080"' in text
    assert "app.dashboard_server:app" in text
    assert "edge_dashboard:${DASHBOARD_DB_PASSWORD}@postgres:5432/edge" in text
    assert 'SIGNER_ENABLED: "false"' in text
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS" in text
    assert "default_transaction_read_only = on" in text
    assert "statement_timeout = '5s'" in text
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
    for write_grant in ("GRANT INSERT", "GRANT UPDATE", "GRANT DELETE", "GRANT TRUNCATE"):
        assert write_grant not in text
    assert "dashboard_gateway" in text
    assert "- default" in text
    assert "cap_drop:\n      - ALL" in text
    assert "no-new-privileges:true" in text


def test_cloudflared_depends_on_dashboard_and_has_only_gateway_network():
    text = _text("deploy/compose.dashboard-tunnel.yml")
    assert "dashboard:" in text
    assert "condition: service_healthy" in text
    assert "api:" not in text
    assert "ports: []" in text
    assert "- dashboard_gateway" in text
    assert "- default" not in text
    assert "cap_drop:\n      - ALL" in text
    assert "no-new-privileges:true" in text


def test_tunnel_launcher_requires_isolated_origin_and_preflight():
    text = _text("deploy/start-dashboard-tunnel.sh")
    assert "sh deploy/preflight-forward.sh" in text
    assert "deploy/compose.dashboard.yml" in text
    assert "http://dashboard:8080" in text
    assert "Do NOT configure the public hostname to target api:8000" in text
    assert "cloudflared container is not attached to the research API network" in text
    assert "dashboard-db-role dashboard cloudflared" in text


def test_forward_launcher_starts_gateway_but_keeps_research_api_private():
    launcher = _text("deploy/start-forward.sh")
    hardened = _text("deploy/compose.forward.yml")
    assert "sh deploy/preflight-forward.sh --research-only" in launcher
    assert "deploy/compose.dashboard.yml" in launcher
    assert "dashboard-db-role dashboard" in launcher
    assert "127.0.0.1:8080/dashboard" in launcher
    assert "never use as the Cloudflare origin" in launcher
    assert '"127.0.0.1:8000:8000"' in hardened


def test_preflight_and_verify_enforce_gateway_separation_and_db_privileges():
    preflight = _text("deploy/preflight-forward.sh")
    verify = _text("deploy/verify-forward.sh")
    assert "cloudflared shares a Docker network with the research API" in preflight
    assert "dashboard role grants SELECT on all tables" in preflight
    assert "dashboard role contains a write grant" in preflight
    assert "dashboard SELECT table set differs from allowlist" in verify
    assert "cloudflared shares Docker network with research API" in verify
    assert '"live_capital_usd": 0' in verify


def test_dashboard_has_separate_secret_and_no_wallet_material():
    text = _text("deploy/.env.forward.example")
    assert "DASHBOARD_DB_PASSWORD=replace-with-a-third-long-random-password" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in text
    assert "PRIVATE_KEY" not in text
    assert "SEED_PHRASE" not in text
