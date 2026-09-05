from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_m6j_compose_has_no_ports_and_forces_signer_off():
    text = (ROOT / "deploy" / "compose.m6j.yml").read_text()
    assert 'SIGNER_ENABLED: "false"' in text
    assert "ports:" not in text
    assert "research-acceleration" in text
    assert "m6j-hyperliquid-research" in text
    assert "m6j-polymarket-research" in text
    assert "m6j-solana-research" in text
    assert sum(
        line.strip().startswith("M6K_ENABLED:") for line in text.splitlines()
    ) == 3


def test_m6j_m6k_workers_expose_no_transaction_submission_surface():
    paths = [
        ROOT / "app" / "workers" / "m6j_hyperliquid_research.py",
        ROOT / "app" / "workers" / "m6j_polymarket_research.py",
        ROOT / "app" / "workers" / "m6j_solana_research.py",
        ROOT / "app" / "m6k_research.py",
    ]
    forbidden = (
        "sendTransaction",
        "send_transaction",
        "private_key",
        "PRIVATE_KEY",
        "wallet_secret",
        "sign_and_send",
        "place_order",
        "create_order",
        "Jupiter /execute",
    )
    for path in paths:
        text = path.read_text()
        for needle in forbidden:
            assert needle not in text, f"{path.name} contains forbidden execution surface {needle}"


def test_start_forward_includes_m6j_profile_and_services():
    text = (ROOT / "deploy" / "start-forward.sh").read_text()
    assert "deploy/compose.m6j.yml" in text
    assert "--profile research-acceleration" in text
    assert "m6j-hyperliquid-research m6j-polymarket-research m6j-solana-research" in text
    assert "export SIGNER_ENABLED=false" in text


def test_m6j_m6k_do_not_replace_frozen_baseline_ids():
    env = (ROOT / "deploy" / ".env.forward.example").read_text()
    assert "POLYMARKET_FORWARD_STUDY_EXTERNAL_ID=polymarket-structural-m6f-v1" in env
    assert "SOLANA_FORWARD_STUDY_EXTERNAL_ID=solana-pump-baseline-m6g-v1" in env
    assert "M6J_ENABLED=true" in env
    assert "M6J_HYPERLIQUID_HORIZONS_HOURS=24,168,336,720" in env
    assert "M6J_SOLANA_OUTCOME_HORIZONS_MINUTES=5,15,30,60" in env
    assert "M6K_ENABLED=true" in env
    assert "M6K_HYPERLIQUID_MIN_OBSERVATIONS=168" in env
    assert "M6K_HYPERLIQUID_MIN_POSITIVE_FRACTION=0.70" in env
    assert "M6K_HYPERLIQUID_MIN_BASELINE_FRACTION=0.50" in env
    assert "M6K_HYPERLIQUID_MIN_STRESS_POSITIVE_FRACTION=0.50" in env
    assert "M6K_HYPERLIQUID_MIN_CURRENT_BASELINE_STREAK=24" in env
    assert "M6K_HYPERLIQUID_COST_STRESS_MULTIPLIER=2" in env
    assert "M6K_POLYMARKET_BASELINE_EDGE_BPS=10" in env
    assert "M6K_SOLANA_RESOLUTION_LOOKBACK_HOURS=72" in env
    assert "M6K_SOLANA_RESOLUTION_MAX_PER_CYCLE=100" in env


def test_polymarket_research_websocket_uses_bounded_large_frame_limit():
    text = (ROOT / "app" / "workers" / "m6j_polymarket_research.py").read_text()
    assert "max_size=4 * 1024 * 1024" in text
    assert "max_size=None" not in text
