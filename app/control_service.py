from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.control_models import IncidentControlState, OwnerCommand, StudyControlSetting
from app.forward_models import ForwardStudy, ForwardStudyIncident


class OwnerControlError(RuntimeError):
    pass


ALLOWED_COMMANDS = {
    "pause",
    "resume",
    "freeze",
    "lifecycle_on",
    "lifecycle_off",
    "incident_ack",
    "incident_resolve",
}

STUDY_ALIASES = {"hyperliquid", "polymarket", "solana"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class OwnerControlResult:
    command_id: str
    command: str
    status: str
    target_type: str
    target_id: str | None
    outcome: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class OwnerControlService:
    """Typed M6I research controls only. It has no execution, signer, shell or fund path."""

    @staticmethod
    def list_studies(db: Session) -> list[ForwardStudy]:
        return list(
            db.scalars(select(ForwardStudy).order_by(ForwardStudy.started_at.asc())).all()
        )

    @staticmethod
    def resolve_study(db: Session, target: str) -> ForwardStudy:
        target = target.strip()
        if not target:
            raise OwnerControlError("study target is required")
        study = db.get(ForwardStudy, target)
        if study is not None:
            return study
        study = db.scalar(select(ForwardStudy).where(ForwardStudy.external_id == target))
        if study is not None:
            return study
        alias = target.lower()
        if alias in STUDY_ALIASES:
            study = db.scalar(
                select(ForwardStudy)
                .where(ForwardStudy.venue == alias)
                .order_by(ForwardStudy.started_at.desc())
                .limit(1)
            )
            if study is not None:
                return study
        raise OwnerControlError(f"study not found: {target}")

    @staticmethod
    def lifecycle_enabled(db: Session, study_id: str) -> bool:
        row = db.get(StudyControlSetting, study_id)
        return True if row is None else bool(row.lifecycle_enabled)

    @staticmethod
    def incident_acknowledged(db: Session, incident_id: str) -> bool:
        row = db.get(IncidentControlState, incident_id)
        return bool(row and row.acknowledged_at is not None)

    @staticmethod
    def _existing_result(row: OwnerCommand) -> OwnerControlResult:
        try:
            outcome = json.loads(row.outcome_json or "{}")
        except json.JSONDecodeError:
            outcome = {"raw": row.outcome_json}
        return OwnerControlResult(
            command_id=row.id,
            command=row.command,
            status=row.status,
            target_type=row.target_type,
            target_id=row.target_id,
            outcome=outcome if isinstance(outcome, dict) else {"value": outcome},
        )

    @classmethod
    def execute(
        cls,
        db: Session,
        *,
        command: str,
        actor_type: str,
        actor_id: str,
        idempotency_key: str,
        target: str,
        reason: str,
    ) -> OwnerControlResult:
        command = command.strip().lower()
        actor_type = actor_type.strip().lower()
        actor_id = actor_id.strip()
        idempotency_key = idempotency_key.strip()
        target = target.strip()
        reason = reason.strip() or "owner command"
        if command not in ALLOWED_COMMANDS:
            raise OwnerControlError(f"command is not allowlisted: {command}")
        if not actor_type or not actor_id:
            raise OwnerControlError("actor identity is required")
        if not idempotency_key or len(idempotency_key) > 180:
            raise OwnerControlError("valid idempotency key is required")
        if len(reason) > 1000:
            raise OwnerControlError("reason is too long")

        existing = db.scalar(
            select(OwnerCommand).where(OwnerCommand.idempotency_key == idempotency_key)
        )
        if existing is not None:
            result = cls._existing_result(existing)
            if result.status == "rejected":
                raise OwnerControlError(str(result.outcome.get("error") or "command was rejected"))
            return result

        target_type = "incident" if command.startswith("incident_") else "study"
        audit = OwnerCommand(
            idempotency_key=idempotency_key,
            actor_type=actor_type,
            actor_id=actor_id,
            command=command,
            target_type=target_type,
            target_id=target or None,
            reason=reason,
            status="pending",
            outcome_json="{}",
            requested_at=_now(),
        )
        db.add(audit)

        try:
            if target_type == "incident":
                outcome = cls._apply_incident_command(
                    db,
                    command=command,
                    incident_id=target,
                    actor=f"{actor_type}:{actor_id}",
                )
                audit.target_id = target
            else:
                study = cls.resolve_study(db, target)
                audit.target_id = study.id
                outcome = cls._apply_study_command(
                    db,
                    command=command,
                    study=study,
                    actor=f"{actor_type}:{actor_id}",
                )
            audit.status = "applied"
            audit.outcome_json = _json(outcome)
            audit.completed_at = _now()
            db.commit()
            db.refresh(audit)
            return OwnerControlResult(
                command_id=audit.id,
                command=command,
                status=audit.status,
                target_type=audit.target_type,
                target_id=audit.target_id,
                outcome=outcome,
            )
        except OwnerControlError as exc:
            db.rollback()
            rejected = OwnerCommand(
                idempotency_key=idempotency_key,
                actor_type=actor_type,
                actor_id=actor_id,
                command=command,
                target_type=target_type,
                target_id=target or None,
                reason=reason,
                status="rejected",
                outcome_json=_json({"error": str(exc)}),
                requested_at=_now(),
                completed_at=_now(),
            )
            db.add(rejected)
            db.commit()
            raise

    @staticmethod
    def _apply_study_command(
        db: Session,
        *,
        command: str,
        study: ForwardStudy,
        actor: str,
    ) -> dict[str, Any]:
        before = study.status
        if command == "pause":
            if before == "active":
                study.status = "paused"
            elif before == "paused":
                pass
            elif before == "frozen":
                raise OwnerControlError("frozen study cannot be paused or resumed")
            else:
                raise OwnerControlError(f"study cannot be paused from status {before}")
            return {"study": study.external_id, "before": before, "after": study.status}

        if command == "resume":
            if before == "paused":
                study.status = "active"
            elif before == "active":
                pass
            elif before == "frozen":
                raise OwnerControlError("frozen study cannot be resumed")
            else:
                raise OwnerControlError(f"study cannot be resumed from status {before}")
            return {"study": study.external_id, "before": before, "after": study.status}

        if command == "freeze":
            if before in {"active", "paused"}:
                study.status = "frozen"
            elif before == "frozen":
                pass
            else:
                raise OwnerControlError(f"study cannot be frozen from status {before}")
            return {
                "study": study.external_id,
                "before": before,
                "after": study.status,
                "irreversible_by_owner_controls": True,
            }

        if command in {"lifecycle_on", "lifecycle_off"}:
            if study.venue != "solana" or study.family != "meme":
                raise OwnerControlError("M6H lifecycle controls apply only to the Solana meme study")
            enabled = command == "lifecycle_on"
            setting = db.get(StudyControlSetting, study.id)
            before_enabled = True if setting is None else bool(setting.lifecycle_enabled)
            if setting is None:
                setting = StudyControlSetting(
                    study_id=study.id,
                    lifecycle_enabled=enabled,
                    updated_by=actor,
                    updated_at=_now(),
                )
                db.add(setting)
            else:
                setting.lifecycle_enabled = enabled
                setting.updated_by = actor
                setting.updated_at = _now()
            return {
                "study": study.external_id,
                "lifecycle_before": before_enabled,
                "lifecycle_after": enabled,
                "can_execute": False,
            }

        raise OwnerControlError(f"unsupported study command: {command}")

    @staticmethod
    def _apply_incident_command(
        db: Session,
        *,
        command: str,
        incident_id: str,
        actor: str,
    ) -> dict[str, Any]:
        if not incident_id:
            raise OwnerControlError("incident id is required")
        incident = db.get(ForwardStudyIncident, incident_id)
        if incident is None:
            raise OwnerControlError("incident not found")
        state = db.get(IncidentControlState, incident.id)

        if command == "incident_ack":
            if state is None:
                state = IncidentControlState(incident_id=incident.id)
                db.add(state)
            if state.acknowledged_at is None:
                state.acknowledged_at = _now()
                state.acknowledged_by = actor
            state.updated_at = _now()
            return {
                "incident_id": incident.id,
                "acknowledged": True,
                "resolved": bool(incident.resolved),
            }

        if command == "incident_resolve":
            if incident.data_integrity:
                raise OwnerControlError(
                    "data-integrity incidents are permanent evidence flags and cannot be resolved away"
                )
            if not incident.resolved:
                incident.resolved = True
                incident.resolved_at = _now()
            return {
                "incident_id": incident.id,
                "acknowledged": bool(state and state.acknowledged_at),
                "resolved": True,
            }

        raise OwnerControlError(f"unsupported incident command: {command}")
