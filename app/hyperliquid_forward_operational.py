from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.forward_models import ForwardStudy, ForwardStudyIncident
from app.forward_research import ForwardResearchError
from app.hyperliquid_forward import (
    CarryRunnerConfigError,
    CarryRunnerError,
    TickResult,
    _aware,
)
from app.hyperliquid_forward_hardened import (
    CarryDataIntegrityError,
    HardenedHyperliquidCarryForwardRunner,
)


class OperationalHyperliquidCarryForwardRunner(HardenedHyperliquidCarryForwardRunner):
    """Hardened runner that permanently stops contaminated studies from adding evidence."""

    @staticmethod
    def _study_block(study_id: str, db: Session) -> str | None:
        integrity_failures = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.data_integrity.is_(True),
                )
            )
            or 0
        )
        if integrity_failures:
            return "study has a recorded data-integrity failure; further evidence is disabled"
        critical = int(
            db.scalar(
                select(func.count())
                .select_from(ForwardStudyIncident)
                .where(
                    ForwardStudyIncident.study_id == study_id,
                    ForwardStudyIncident.severity == "critical",
                    ForwardStudyIncident.resolved.is_(False),
                )
            )
            or 0
        )
        if critical:
            return "study has an unresolved critical incident; forward runner is paused"
        return None

    async def run_active_studies(
        self, db: Session, *, now: datetime | None = None
    ) -> list[TickResult]:
        now = _aware(now or datetime.now(timezone.utc))
        studies = db.scalars(
            select(ForwardStudy).where(
                ForwardStudy.status == "active",
                ForwardStudy.venue == "hyperliquid",
                ForwardStudy.family == "funding",
            )
        ).all()
        results: list[TickResult] = []
        for study in studies:
            blocked = self._study_block(study.id, db)
            if blocked is not None:
                results.append(TickResult(study.id, "blocked", blocked))
                continue
            try:
                results.append(await self.run_study_once(db, study=study, now=now))
            except CarryDataIntegrityError as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="critical",
                    code="HL_CARRY_DATA_INTEGRITY",
                    message=str(exc),
                    data_integrity=True,
                )
                results.append(TickResult(study.id, "blocked", str(exc)))
            except CarryRunnerConfigError as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="critical",
                    code="HL_CARRY_CONFIG_INVALID",
                    message=str(exc),
                    data_integrity=True,
                )
                results.append(TickResult(study.id, "blocked", str(exc)))
            except (ForwardResearchError, CarryRunnerError) as exc:
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="HL_CARRY_RUNNER_ERROR",
                    message=str(exc),
                    data_integrity=False,
                )
                results.append(TickResult(study.id, "error", str(exc)))
            except Exception as exc:
                db.rollback()
                self._record_runner_incident(
                    db,
                    study,
                    now,
                    severity="error",
                    code="HL_CARRY_UNEXPECTED_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                    data_integrity=False,
                )
                results.append(
                    TickResult(study.id, "error", f"{type(exc).__name__}: {exc}")
                )
        return results
