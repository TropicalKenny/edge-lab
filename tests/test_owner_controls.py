from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.control_models  # register M6I tables in Base.metadata
from app.control_models import OwnerCommand
from app.control_service import OwnerControlError, OwnerControlService
from app.forward_models import ForwardNavObservation, ForwardStudy, ForwardStudyIncident
from app.forward_research import ForwardResearchError, ForwardResearchService
from app.models import Base, Experiment, Strategy, StrategyVersion


def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def study_fixture(db: Session, *, venue: str = "solana", family: str = "meme") -> ForwardStudy:
    strategy = Strategy(slug=f"{venue}-test", name=f"{venue.title()} Test", status="red")
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version="v1",
        code_sha="abc",
        config_json="{}",
        immutable=True,
    )
    db.add(version)
    db.flush()
    experiment = Experiment(
        strategy_version_id=version.id,
        hypothesis="control test",
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
        external_id=f"{venue}-control-test",
        strategy_version_id=version.id,
        experiment_id=experiment.id,
        family=family,
        venue=venue,
        instrument="TEST",
        status="active",
        initial_capital_usd=Decimal("1000"),
        evaluation_policy_json="{}",
        study_config_json="{}",
        started_at=datetime.now(timezone.utc),
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def execute(db: Session, command: str, target: str, key: str):
    return OwnerControlService.execute(
        db,
        command=command,
        actor_type="test",
        actor_id="owner",
        idempotency_key=key,
        target=target,
        reason="test control",
    )


def test_pause_blocks_forward_writes_and_resume_restores_them():
    db = db_session()
    study = study_fixture(db)

    paused = execute(db, "pause", study.id, "pause-0001")
    assert paused.outcome["after"] == "paused"
    with pytest.raises(ForwardResearchError, match="not active"):
        ForwardResearchService.record_nav(
            db,
            study_id=study.id,
            observed_at=datetime.now(timezone.utc),
            nav_usd=Decimal("1001"),
        )

    resumed = execute(db, "resume", study.id, "resume-0001")
    assert resumed.outcome["after"] == "active"
    row = ForwardResearchService.record_nav(
        db,
        study_id=study.id,
        observed_at=datetime.now(timezone.utc),
        nav_usd=Decimal("1001"),
    )
    assert isinstance(row, ForwardNavObservation)


def test_freeze_is_not_reversible_by_owner_controls():
    db = db_session()
    study = study_fixture(db)
    frozen = execute(db, "freeze", study.id, "freeze-0001")
    assert frozen.outcome["after"] == "frozen"
    assert frozen.outcome["irreversible_by_owner_controls"] is True

    with pytest.raises(OwnerControlError, match="cannot be resumed"):
        execute(db, "resume", study.id, "resume-frozen-0001")
    assert db.get(ForwardStudy, study.id).status == "frozen"


def test_command_idempotency_returns_same_audit_record():
    db = db_session()
    study = study_fixture(db)
    first = execute(db, "pause", study.id, "same-command-0001")
    second = execute(db, "pause", study.id, "same-command-0001")
    assert first.command_id == second.command_id
    assert db.scalar(select(func.count(OwnerCommand.id))) == 1


def test_lifecycle_toggle_is_separate_from_m6g_study_state():
    db = db_session()
    study = study_fixture(db)
    result = execute(db, "lifecycle_off", study.id, "lifecycle-off-0001")
    assert result.outcome["lifecycle_after"] is False
    assert OwnerControlService.lifecycle_enabled(db, study.id) is False
    assert db.get(ForwardStudy, study.id).status == "active"

    result = execute(db, "lifecycle_on", study.id, "lifecycle-on-0001")
    assert result.outcome["lifecycle_after"] is True
    assert OwnerControlService.lifecycle_enabled(db, study.id) is True


def test_data_integrity_incident_cannot_be_resolved_away():
    db = db_session()
    study = study_fixture(db)
    incident = ForwardStudyIncident(
        study_id=study.id,
        external_key="integrity-1",
        severity="critical",
        code="DATA_GAP",
        message="test integrity incident",
        data_integrity=True,
        resolved=False,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    ack = execute(db, "incident_ack", incident.id, "incident-ack-0001")
    assert ack.outcome["acknowledged"] is True
    assert OwnerControlService.incident_acknowledged(db, incident.id) is True

    with pytest.raises(OwnerControlError, match="permanent evidence"):
        execute(db, "incident_resolve", incident.id, "incident-resolve-0001")
    assert db.get(ForwardStudyIncident, incident.id).resolved is False


def test_non_integrity_incident_can_be_resolved_without_deletion():
    db = db_session()
    study = study_fixture(db)
    incident = ForwardStudyIncident(
        study_id=study.id,
        external_key="ops-1",
        severity="warning",
        code="WORKER_RESTART",
        message="test operational incident",
        data_integrity=False,
        resolved=False,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    result = execute(db, "incident_resolve", incident.id, "incident-resolve-0002")
    assert result.outcome["resolved"] is True
    persisted = db.get(ForwardStudyIncident, incident.id)
    assert persisted is not None
    assert persisted.resolved is True
    assert persisted.resolved_at is not None
