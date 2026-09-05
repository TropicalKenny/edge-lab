from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.solana_meme_forward import M6LMemeConfig, alpha_score, security_gate
from app.solana_meme_forward_operational import study_config

ROOT = Path(__file__).resolve().parents[1]


def feature(**overrides):
    values = {
        "age_minutes": Decimal("5"),
        "momentum_score": Decimal("0.25"),
        "sell_ratio_5m": Decimal("0.38"),
        "volume_acceleration": Decimal("3"),
        "price_change_5m": Decimal("1.5"),
        "market_cap": Decimal("3000"),
        "liquidity_usd": Decimal("0"),
        "mintable": None,
        "freezable": None,
        "malicious_creator": None,
        "transfer_fee_rate": None,
        "missing_fields_json": "[]",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def security(**overrides):
    values = {
        "non_transferable": None,
        "mintable": None,
        "freezable": None,
        "malicious_creator": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def cfg(cohort: str = "exploratory") -> M6LMemeConfig:
    raw = study_config(cohort)
    study = SimpleNamespace(study_config_json=__import__("json").dumps(raw))
    return M6LMemeConfig.from_study(study)


def test_alpha_score_accepts_flow_candidate():
    score, accepted, reasons, components = alpha_score(feature(), cfg())
    assert accepted is True
    assert score >= 3
    assert "ALPHA_SCORE_BELOW_ENTRY" not in reasons
    assert components["momentum_score"] == "0.25"


def test_alpha_score_rejects_early_collapse_even_with_buy_pressure():
    score, accepted, reasons, _ = alpha_score(
        feature(price_change_5m=Decimal("-25")), cfg()
    )
    assert score >= 3
    assert accepted is False
    assert "EARLY_PRICE_COLLAPSE" in reasons


def test_exploratory_allows_unknown_but_strict_rejects_unknown():
    f = feature()
    s = security()
    allowed, blocked, unknown = security_gate(f, s, cohort="exploratory")
    assert allowed is True
    assert blocked == ()
    assert unknown

    allowed, blocked, unknown = security_gate(f, s, cohort="strict")
    assert allowed is False
    assert blocked == ()
    assert unknown


def test_known_unsafe_is_blocked_in_both_cohorts():
    f = feature(malicious_creator=True)
    for cohort in ("strict", "exploratory"):
        allowed, blocked, _ = security_gate(f, security(), cohort=cohort)
        assert allowed is False
        assert "MALICIOUS_CREATOR_KNOWN" in blocked


def test_m6l_studies_share_alpha_but_differ_unknown_policy():
    strict = study_config("strict")
    exploratory = study_config("exploratory")
    comparable = {
        key: value
        for key, value in strict.items()
        if key not in {"cohort", "unknown_policy"}
    }
    assert comparable == {
        key: value
        for key, value in exploratory.items()
        if key not in {"cohort", "unknown_policy"}
    }
    assert strict["unknown_policy"] == "reject_unknown"
    assert exploratory["unknown_policy"] == "allow_unknown_block_known_unsafe"


def test_m6l_compose_is_paper_only_and_has_no_ports():
    text = (ROOT / "deploy" / "compose.solana-forward.yml").read_text()
    assert "m6l-solana-bootstrap:" in text
    assert "m6l-solana-runner:" in text
    m6l = text.split("  m6l-solana-bootstrap:", 1)[1]
    assert 'SIGNER_ENABLED: "false"' in m6l
    assert "ports:" not in m6l
    assert "app.workers.solana_meme_forward_runner" in m6l


def test_m6l_source_exposes_no_transaction_submission_path():
    paths = [
        ROOT / "app" / "solana_meme_forward.py",
        ROOT / "app" / "solana_meme_forward_operational.py",
        ROOT / "app" / "workers" / "solana_meme_forward_runner.py",
    ]
    forbidden = (
        "sendTransaction",
        "send_transaction",
        "private_key",
        "wallet_secret",
        "sign_and_send",
        "place_order",
        "create_order",
    )
    for path in paths:
        text = path.read_text()
        for needle in forbidden:
            assert needle not in text, f"{path.name} contains forbidden execution surface {needle}"
