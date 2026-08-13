from pathlib import Path

from app.venues.solana import JupiterShadowClient

ROOT = Path(__file__).resolve().parents[1]


def test_solana_forward_overlay_uses_hardened_database_and_disabled_signer():
    text = (ROOT / "deploy" / "compose.solana-forward.yml").read_text()
    assert "postgresql+psycopg://edge:${POSTGRES_PASSWORD}@postgres:5432/edge" in text
    assert text.count('SIGNER_ENABLED: "false"') >= 4
    assert "HELIUS_API_KEY: ${HELIUS_API_KEY:?set HELIUS_API_KEY}" in text
    assert "JUPITER_API_KEY: ${JUPITER_API_KEY:?set JUPITER_API_KEY}" in text
    assert "app.solana_forward_ops status" in text
    assert "--require-ready" in text


def test_forward_launcher_requires_research_keys_and_starts_solana_services():
    text = (ROOT / "deploy" / "start-forward.sh").read_text()
    assert "HELIUS_API_KEY is required for Solana forward research" in text
    assert "JUPITER_API_KEY is required for quote-only Solana forward research" in text
    assert "deploy/compose.solana-forward.yml" in text
    assert "--profile solana" in text
    for service in (
        "solana-launch-collector",
        "solana-forensic-sampler",
        "solana-forward-bootstrap",
        "solana-forward-runner",
    ):
        assert service in text
    assert "export SIGNER_ENABLED=false" in text


def test_solana_forward_sources_contain_no_live_execution_or_key_surface():
    paths = [
        ROOT / "app" / "solana_forward.py",
        ROOT / "app" / "solana_forward_operational.py",
        ROOT / "app" / "solana_forward_ops.py",
        ROOT / "app" / "workers" / "solana_forward_bootstrap.py",
        ROOT / "app" / "workers" / "solana_forward_runner.py",
        ROOT / "deploy" / "compose.solana-forward.yml",
    ]
    combined = "\n".join(path.read_text() for path in paths).lower()
    for forbidden in (
        "/execute",
        "private_key",
        "seed phrase",
        "seed_phrase",
        "wallet_secret",
        "sign_transaction",
        "send_transaction",
    ):
        assert forbidden not in combined
    assert not hasattr(JupiterShadowClient, "execute")


def test_forward_env_example_freezes_baseline_before_first_bootstrap():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert "SOLANA_FORWARD_STUDY_EXTERNAL_ID=solana-pump-baseline-m6g-v1" in text
    assert "SOLANA_FORWARD_ENTRY_NOTIONAL_USD=25" in text
    assert "SOLANA_FORWARD_DECISION_DELAY_MINUTES=5" in text
    assert "SOLANA_FORWARD_HOLD_MINUTES=30" in text
    assert "SOLANA_FORWARD_MAX_QUOTE_PRICE_IMPACT_PCT=0.05" in text
    assert "SOLANA_FORWARD_MIN_PREFLIGHT_EXIT_RATIO=0.90" in text
    assert "SOLANA_FORWARD_NAV_INTERVAL_SECONDS=300" in text
