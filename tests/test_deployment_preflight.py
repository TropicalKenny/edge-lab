from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "deploy" / "preflight-forward.sh"
VERIFY = ROOT / "deploy" / "verify-forward.sh"
RUNBOOK = ROOT / "docs" / "MILESTONE6E_FORWARD_DEPLOYMENT.md"


def test_deployment_shell_scripts_parse_with_posix_sh():
    for path in (PREFLIGHT, VERIFY):
        result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_preflight_fails_closed_on_secrets_signer_and_wallet_material():
    text = PREFLIGHT.read_text()
    assert "chmod 600" in text
    assert "PRIVATE_KEY|SEED_PHRASE|MNEMONIC" in text
    assert "SIGNER_ENABLED must be false" in text
    assert "export SIGNER_ENABLED=false" in text
    assert "POSTGRES_PASSWORD must be at least 24 characters" in text
    assert "FORWARD_INGEST_SECRET must be at least 32 characters" in text
    assert "HELIUS_API_KEY is required for Solana research" in text
    assert "JUPITER_API_KEY is required for quote-only Solana research" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN is required for dashboard preflight" in text
    assert "--research-only" in text


def test_preflight_validates_rendered_network_without_persisting_rendered_secrets():
    text = PREFLIGHT.read_text()
    assert "config -q" in text
    assert "config --format json |" in text
    assert "PostgreSQL has a published host port" in text
    assert "Redis has a published host port" in text
    assert "API host binding is not 127.0.0.1" in text
    assert "cloudflared has a published host port" in text
    assert "cloudflared unexpectedly receives" in text
    assert "SIGNER_ENABLED=false" in text
    assert "> /tmp" not in text
    assert ">/tmp" not in text
    assert "mktemp" not in text


def test_runtime_verify_checks_read_only_dashboard_and_all_three_studies():
    text = VERIFY.read_text()
    assert "http://127.0.0.1:8000/dashboard/api/summary" in text
    for flag in (
        '"can_trade_live": False',
        '"can_sign": False',
        '"can_move_funds": False',
        '"vault_accessible": False',
        '"signer_enabled": False',
    ):
        assert flag in text
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
    assert "Dashboard V1 is now part of the FastAPI service" in text
    assert "owner-only Cloudflare Access application" in text
    assert "No result from this deployment can authorize capital or enable a signer" in text
