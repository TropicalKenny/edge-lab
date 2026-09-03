from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "compose.controls.yml"
PREFLIGHT = ROOT / "deploy" / "preflight-controls.sh"
START = ROOT / "deploy" / "start-control-plane.sh"
CORE_PREFLIGHT = ROOT / "deploy" / "preflight-core-forward.sh"
CORE_START = ROOT / "deploy" / "start-core-forward.sh"


def test_control_plane_never_mounts_docker_socket_or_passes_venue_keys():
    text = COMPOSE.read_text()
    assert "docker.sock" not in text
    telegram_section = text.split("telegram-controls:", 1)[1]
    for forbidden in (
        "HELIUS_API_KEY",
        "JUPITER_API_KEY",
        "GOPLUS_ACCESS_TOKEN",
        "FORWARD_INGEST_SECRET",
        "OWNER_CONTROL_API_TOKEN",
    ):
        assert forbidden not in telegram_section
    assert 'SIGNER_ENABLED: "false"' in telegram_section
    assert "ports: []" in telegram_section


def test_owner_control_is_loopback_only_and_has_no_venue_credentials():
    text = COMPOSE.read_text()
    owner = text.split("owner-control:", 1)[1].split("telegram-controls:", 1)[0]
    assert '"127.0.0.1:8090:8090"' in owner
    assert 'SIGNER_ENABLED: "false"' in owner
    assert "OWNER_CONTROL_API_TOKEN" in owner
    assert "HELIUS_API_KEY" not in owner
    assert "JUPITER_API_KEY" not in owner
    assert "docker.sock" not in owner


def test_control_role_is_explicit_and_has_no_delete_or_all_table_grant():
    text = COMPOSE.read_text()
    role = text.split("control-db-role:", 1)[1].split("owner-control:", 1)[0]
    assert "REVOKE ALL ON ALL TABLES" in role
    assert "GRANT UPDATE (status) ON forward_studies" in role
    assert "GRANT UPDATE (resolved, resolved_at) ON forward_study_incidents" in role
    assert "GRANT INSERT ON owner_commands" in role
    assert "GRANT DELETE" not in role
    assert "GRANT ALL ON ALL TABLES" not in role
    assert "NOBYPASSRLS" in role


def test_control_scripts_do_not_require_solana_provider_keys():
    preflight = PREFLIGHT.read_text()
    start = START.read_text()
    for forbidden in ("HELIUS_API_KEY", "JUPITER_API_KEY"):
        assert forbidden not in preflight
        assert forbidden not in start


def test_core_forward_launcher_deliberately_excludes_solana_workers():
    preflight = CORE_PREFLIGHT.read_text()
    start = CORE_START.read_text()
    assert "Hyperliquid/Polymarket core can start without Helius/Jupiter" in preflight
    assert "solana-launch-collector" not in start
    assert "solana-forensic-sampler" not in start
    assert "solana-forward-runner" not in start
    assert "app.workers.solana_forward_bootstrap" in start
    assert "SIGNER_ENABLED=false" in start
