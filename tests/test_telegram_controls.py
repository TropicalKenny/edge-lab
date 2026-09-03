from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.control_models  # register M6I tables
import app.evaluation_models
import app.forward_models
import app.lifecycle_models
from app.config import Settings
from app.forward_models import ForwardNavObservation, ForwardStudy
from app.models import Base, Experiment, Strategy, StrategyVersion
from app.telegram_control import TelegramControlRouter


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def solana_study(db: Session) -> ForwardStudy:
    strategy = Strategy(slug="solana-control-test", name="Solana Test", status="amber")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="m6g-test",
        code_sha="abc",
        config_json="{}",
        immutable=True,
    )
    db.add(version)
    db.flush()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="telegram test",
        data_version="v1",
        train_window="none",
        validation_window="forward",
        holdout_window="forward",
        search_space_json="{}",
        status="running",
    )
    db.add(experiment)
    db.flush()
    study = ForwardStudy(
        external_id="solana-pump-baseline-test",
        strategy_version_id=version.id,
        experiment_id=experiment.id,
        family="meme",
        venue="solana",
        instrument="PUMP",
        status="active",
        initial_capital_usd=Decimal("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=datetime.now(timezone.utc),
    )
    db.add(study)
    db.flush()
    db.add(
        ForwardNavObservation(
            study_id=study.id,
            observed_at=datetime.now(timezone.utc),
            nav_usd=Decimal("1125"),
            source="test",
        )
    )
    db.commit()
    db.refresh(study)
    return study


def router() -> TelegramControlRouter:
    return TelegramControlRouter(
        Settings(
            telegram_bot_token="test-token",
            telegram_chat_id="111",
            telegram_owner_user_id="222",
        )
    )


def test_authorization_requires_both_private_chat_and_owner_user():
    r = router()
    valid = {
        "update_id": 1,
        "message": {"chat": {"id": 111}, "from": {"id": 222}, "text": "/status"},
    }
    assert r.authorized_message(valid) == ("111", "222", "/status")

    wrong_user = {
        "update_id": 2,
        "message": {"chat": {"id": 111}, "from": {"id": 999}, "text": "/status"},
    }
    wrong_chat = {
        "update_id": 3,
        "message": {"chat": {"id": 999}, "from": {"id": 222}, "text": "/status"},
    }
    assert r.authorized_message(wrong_user) is None
    assert r.authorized_message(wrong_chat) is None


def test_balance_is_explicitly_simulated_and_never_implies_live_capital():
    db = db_session()
    solana_study(db)
    text = router().render(db, "/balance")
    assert "PAPER/SHADOW BALANCE" in text
    assert "$1,125.00" in text
    assert "$1,000.00" in text
    assert "+12.50%" in text
    assert "Live capital: $0.00" in text
    assert "Signer: DISABLED" in text


def test_pause_command_uses_shared_owner_control_service():
    db = db_session()
    study = solana_study(db)
    text = router().apply(
        db,
        update_id=88,
        user_id="222",
        text="/pause solana maintenance test",
    )
    assert text is not None
    assert "active → paused" in text
    assert db.get(ForwardStudy, study.id).status == "paused"

    # Telegram retries are idempotent because the update id is part of the key.
    again = router().apply(
        db,
        update_id=88,
        user_id="222",
        text="/pause solana maintenance test",
    )
    assert again is not None
    assert db.get(ForwardStudy, study.id).status == "paused"


def test_lifecycle_off_keeps_m6g_study_active():
    db = db_session()
    study = solana_study(db)
    text = router().apply(
        db,
        update_id=89,
        user_id="222",
        text="/lifecycle off pause lifecycle research",
    )
    assert text is not None
    assert "Enabled: FALSE" in text
    assert db.get(ForwardStudy, study.id).status == "active"


def test_performance_command_is_safe_before_m6h_has_samples():
    db = db_session()
    solana_study(db)
    text = router().render(db, "/performance")
    assert "EDGE LAB — PERFORMANCE" in text
    assert "M6H lifecycle vs uninterrupted hold" in text
    assert "tp30-rebuy15" in text
    assert "samples 0/300" in text
    assert "cycles 0/300" in text
