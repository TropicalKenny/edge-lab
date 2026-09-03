"""align Hyperliquid carry positions with shadow-fill model

Revision ID: m3e6ab97d288
Revises: l2d59a86c177
Create Date: 2026-09-03 11:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m3e6ab97d288"
down_revision: str | Sequence[str] | None = "l2d59a86c177"
branch_labels = None
depends_on = None


_DATE_COLUMNS = (
    "entry_shadow_observed_at",
    "exit_shadow_observed_at",
)

_NUMERIC_COLUMNS = (
    "entry_shadow_spot_filled_quantity",
    "entry_shadow_perp_filled_quantity",
    "entry_shadow_spot_price",
    "entry_shadow_perp_price",
    "entry_shadow_spot_cost_usd",
    "entry_shadow_perp_cost_usd",
    "exit_spot_fee_usd",
    "exit_perp_fee_usd",
    "exit_spot_slippage_usd",
    "exit_perp_slippage_usd",
    "exit_shadow_spot_filled_quantity",
    "exit_shadow_perp_filled_quantity",
    "exit_shadow_spot_price",
    "exit_shadow_perp_price",
    "exit_shadow_spot_cost_usd",
    "exit_shadow_perp_cost_usd",
)


def upgrade() -> None:
    for name in _DATE_COLUMNS:
        op.add_column(
            "hyperliquid_carry_positions",
            sa.Column(name, sa.DateTime(timezone=True), nullable=True),
        )
    for name in _NUMERIC_COLUMNS:
        op.add_column(
            "hyperliquid_carry_positions",
            sa.Column(name, sa.Numeric(28, 10), nullable=True),
        )


def downgrade() -> None:
    for name in reversed(_NUMERIC_COLUMNS):
        op.drop_column("hyperliquid_carry_positions", name)
    for name in reversed(_DATE_COLUMNS):
        op.drop_column("hyperliquid_carry_positions", name)
