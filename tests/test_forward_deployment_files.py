from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forward_compose_keeps_data_services_private_and_signer_disabled():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert 'SIGNER_ENABLED: "false"' in text
    assert '"127.0.0.1:8000:8000"' in text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}" in text
    assert "FORWARD_INGEST_SECRET: ${FORWARD_INGEST_SECRET:?set FORWARD_INGEST_SECRET}" in text
    assert "hyperliquid-forward-bootstrap:" in text
    assert "forward-evaluator:" in text
    assert text.count(
        "DATABASE_URL: postgresql+psycopg://edge:${POSTGRES_PASSWORD}@postgres:5432/edge"
    ) >= 6
    assert "private_key" not in text.lower()
    assert "wallet" not in text.lower()
    assert "/exchange" not in text.lower()


def test_burn_in_launcher_refuses_secrets_and_does_not_start_study_clock():
    text = (ROOT / "deploy" / "start-forward.sh").read_text()
    assert "Refusing to start with example secrets" in text
    assert 'SIGNER_ENABLED:-false' in text
    assert 'SIGNER_ENABLED != false' in text
    assert "export SIGNER_ENABLED=false" in text
    command = text.split("up -d --build", 1)[1].split("docker compose", 1)[0]
    assert "hyperliquid-collector" in command
    assert "db-backup" in command
    assert "hyperliquid-forward-bootstrap" not in command
    assert "hyperliquid-forward-runner" not in command
    assert "forward-evaluator" not in command


def test_official_study_launcher_starts_bootstrap_runner_and_evaluator():
    text = (ROOT / "deploy" / "start-study.sh").read_text()
    assert "Refusing to start study with example secrets" in text
    assert 'SIGNER_ENABLED:-false' in text
    assert 'SIGNER_ENABLED != false' in text
    assert "export SIGNER_ENABLED=false" in text
    assert "hyperliquid-forward-bootstrap" in text
    assert "hyperliquid-forward-runner" in text
    assert "forward-evaluator" in text


def test_forward_vps_example_has_non_live_bootstrap_controls():
    text = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert "HYPERLIQUID_FORWARD_STUDY_EXTERNAL_ID=hyperliquid-btc-carry-m6c-v1" in text
    assert "HYPERLIQUID_FORWARD_INITIAL_CAPITAL_USD=1000" in text
    assert "HYPERLIQUID_FORWARD_PAIRED_NOTIONAL_USD=100" in text
    assert "FORWARD_EVALUATION_POLL_SECONDS=3600" in text
    assert "PRIVATE_KEY" not in text
    assert "WALLET" not in text


def test_real_forward_env_and_backups_are_gitignored():
    text = (ROOT / ".gitignore").read_text().splitlines()
    assert "deploy/.env.forward" in text
    assert "deploy/backups/" in text
