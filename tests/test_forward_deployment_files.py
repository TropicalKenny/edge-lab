from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def service_block(text: str, name: str) -> str:
    marker = f"  {name}:\n"
    assert marker in text
    rest = text.split(marker, 1)[1]
    next_service = rest.find("\n  ")
    return rest if next_service < 0 else rest[:next_service]


def test_forward_compose_keeps_data_services_private_and_signer_disabled():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    assert 'SIGNER_ENABLED: "false"' in text
    assert '"127.0.0.1:8000:8000"' in text
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}" in text
    assert "FORWARD_INGEST_SECRET: ${FORWARD_INGEST_SECRET:?set FORWARD_INGEST_SECRET}" in text
    assert "private_key" not in text.lower()
    assert "wallet" not in text.lower()
    assert "/exchange" not in text.lower()


def test_forward_overlay_gives_all_forward_workers_hardened_database_url():
    text = (ROOT / "deploy" / "compose.forward.yml").read_text()
    database_url = "DATABASE_URL: postgresql+psycopg://edge:${POSTGRES_PASSWORD}@postgres:5432/edge"
    for name in (
        "hyperliquid-forward-bootstrap",
        "hyperliquid-forward-runner",
        "polymarket-forward-bootstrap",
        "polymarket-forward-runner",
        "forward-evaluator",
    ):
        block = service_block(text, name)
        assert database_url in block
        assert 'SIGNER_ENABLED: "false"' in block


def test_forward_launcher_refuses_example_secrets_and_starts_both_forward_venues():
    text = (ROOT / "deploy" / "start-forward.sh").read_text()
    assert "Refusing to start with example secrets" in text
    assert 'SIGNER_ENABLED:-false' in text
    assert 'SIGNER_ENABLED != false' in text
    assert "export SIGNER_ENABLED=false" in text
    assert "hyperliquid-forward-bootstrap" in text
    assert "hyperliquid-forward-runner" in text
    assert "polymarket-forward-bootstrap" in text
    assert "polymarket-forward-runner" in text
    assert "forward-evaluator" in text


def test_real_forward_env_and_backups_are_gitignored():
    text = (ROOT / ".gitignore").read_text().splitlines()
    assert "deploy/.env.forward" in text
    assert "deploy/backups/" in text
