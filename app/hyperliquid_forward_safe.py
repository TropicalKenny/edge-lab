from __future__ import annotations

from app.forward_models import ForwardStudy
from app.hyperliquid_forward import CarryStudyConfig, HyperliquidCarryForwardRunner, HyperliquidForwardError


class SafeHyperliquidCarryForwardRunner(HyperliquidCarryForwardRunner):
    """Adds study-level capital invariants to the public-data carry runner."""

    @staticmethod
    def validate_study_capital(study: ForwardStudy, config: CarryStudyConfig) -> None:
        if config.allocated_capital_usd > study.initial_capital_usd:
            raise HyperliquidForwardError(
                "carry allocation exceeds frozen study capital; V1 forward research forbids implicit leverage"
            )

    async def run_study_cycle(self, db, study: ForwardStudy, *, now=None):
        config = CarryStudyConfig.from_json(study.study_config_json)
        self.validate_study_capital(study, config)
        return await super().run_study_cycle(db, study, now=now)
