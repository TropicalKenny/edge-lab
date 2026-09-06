from __future__ import annotations

import json
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.evaluation_models import StrategyEvaluationRun
from app.forward_models import ForwardStudy


def latest_study_evaluation(db: Session, study: ForwardStudy):
    siblings = db.scalar(select(func.count(ForwardStudy.id)).where(
        ForwardStudy.strategy_version_id == study.strategy_version_id,
        ForwardStudy.started_at == study.started_at,
    ))
    rows = db.scalars(select(StrategyEvaluationRun).where(
        StrategyEvaluationRun.strategy_version_id == study.strategy_version_id,
        StrategyEvaluationRun.forward_started_at == study.started_at,
    ).order_by(StrategyEvaluationRun.evaluated_at.desc())).yield_per(100)
    for row in rows:
        try:
            metadata = json.loads(row.metrics_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        identity = metadata.get("study_id")
        if identity == study.id or (identity is None and siblings == 1):
            return row
    return None
