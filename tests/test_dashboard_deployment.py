from pathlib import Path


def test_hardened_dashboard_stays_loopback_only_and_has_separate_credentials():
    compose = Path("deploy/compose.forward.yml").read_text()
    example = Path("deploy/.env.forward.example").read_text()

    assert '"127.0.0.1:8000:8000"' in compose
    assert "DASHBOARD_USERNAME: ${DASHBOARD_USERNAME:-}" in compose
    assert "DASHBOARD_PASSWORD: ${DASHBOARD_PASSWORD:-}" in compose
    assert "DASHBOARD_USERNAME=edge-admin" in example
    assert "DASHBOARD_PASSWORD=replace-with-a-separate-long-random-password" in example
    assert "Keep these separate from FORWARD_INGEST_SECRET" in example
    assert "HTTPS" in example


def test_dashboard_has_no_external_frontend_dependency_or_embedded_research_secret():
    source = Path("app/dashboard.py").read_text()

    assert "https://" not in source
    assert "http://" not in source
    assert "FORWARD_INGEST_SECRET" not in source
    assert "forward_ingest_secret" not in source
    assert "JUPITER_API_KEY" not in source
    assert "HELIUS_API_KEY" not in source
    assert "can_trade_live\": False" in source
    assert "can_sign\": False" in source
    assert "can_move_funds\": False" in source
    assert "can_promote_strategy\": False" in source
