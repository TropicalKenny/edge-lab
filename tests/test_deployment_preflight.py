from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "deploy" / "preflight-forward.sh"
VERIFY = ROOT / "deploy" / "verify-forward.sh"
RUNBOOK = ROOT / "docs" / "MILESTONE6E_FORWARD_DEPLOYMENT.md"
START_FORWARD = ROOT / "deploy" / "start-forward.sh"
START_TUNNEL = ROOT / "deploy" / "start-dashboard-tunnel.sh"


def test_deployment_shell_scripts_parse_with_posix_sh():
    for path in (PREFLIGHT, VERIFY, START_FORWARD, START_TUNNEL):
        result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_launchers_cannot_skip_preflight():
    assert "sh deploy/preflight-forward.sh --research-only" in START_FORWARD.read_text()
    assert "sh deploy/preflight-forward.sh" in START_TUNNEL.read_text()


def test_preflight_fails_closed_on_secrets_signer_wallet_and_dashboard_db():
    text = PREFLIGHT.read_text()
    assert "chmod 600" in text
    assert "PRIVATE_KEY|SEED_PHRASE|MNEMONIC" in text
    assert "SIGNER_ENABLED must be false" in text
    assert "export SIGNER_ENABLED=false" in text
    assert "POSTGRES_PASSWORD must be at least 24 characters" in text
    assert "FORWARD_INGEST_SECRET must be at least 32 characters" in text
    assert "POSTGRES_PASSWORD must differ from FORWARD_INGEST_SECRET" in text
    assert "DASHBOARD_DB_PASSWORD is required for dashboard preflight" in text
    assert "DASHBOARD_DB_PASSWORD must differ from POSTGRES_PASSWORD" in text
    assert "DASHBOARD_DB_PASSWORD must differ from FORWARD_INGEST_SECRET" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN is required for dashboard preflight" in text
    assert "--research-only" in text


def test_preflight_validates_rendered_dashboard_network_and_exact_privileges():
    text = PREFLIGHT.read_text()
    assert "config -q" in text
    assert "config --format json |" in text
    assert "dashboard-db-role" in text
    assert "dashboard does not use edge_dashboard database role" in text
    assert "dashboard role grant is missing table" in text
    assert "dashboard role grants SELECT on all tables" in text
    assert "dashboard role contains a write grant" in text
    assert "dashboard role does not default transactions to read-only" in text
    assert "cloudflared must be isolated to dashboard_edge" in text
    assert "cloudflared shares a Docker network with the research API" in text
    assert "cloudflared receives unexpected environment variables" in text
    assert "dashboard receives unexpected environment variables" in text
    assert "API host binding is not 127.0.0.1" in text
    assert "SIGNER_ENABLED=false" in text
    assert "> /tmp" not in text
    assert ">/tmp" not in text
    assert "mktemp" not in text


def test_runtime_verify_checks_cloudflare_surface_db_privileges_networks_and_three_studies():
    text = VERIFY.read_text()
    assert "isolated dashboard service boundary failed" in text
    assert 'base="http://127.0.0.1:8080"' in text
    for path in (
        "/signer/status",
        "/risk/evaluate",
        "/paper/simulate",
        "/forward/ops/studies",
        "/portfolio/allocate",
        "/openapi.json",
        "/docs",
    ):
        assert path in text
    assert "independent-simulated-forward-study-bankrolls" in text
    assert '"live_capital_usd":0' in text
    assert "dashboard SELECT table set differs from allowlist" in text
    assert 'dashboard has "+privilege+" on "+table' in text
    assert "cloudflared shares Docker network with research API" in text
    assert "python -m app.forward_ops status" in text
    assert "python -m app.polymarket_forward_ops status" in text
    assert "python -m app.solana_forward_ops status" in text
    assert "--require-ready --quiet" in text
    assert "/execute" not in text
    assert "private_key" not in text.lower()


def test_deployment_runbook_uses_preflight_before_trusting_forward_clock():
    text = RUNBOOK.read_text()
    assert "sh deploy/preflight-forward.sh" in text
    assert "sh deploy/verify-forward.sh --with-dashboard --strict" in text
    assert "dashboard_edge" in text
    assert "exact table" in text.lower()
    assert "SELECT-only" in text
    assert "owner-only Cloudflare Access application" in text
    assert "No result from this deployment can authorize capital or enable a signer" in text
