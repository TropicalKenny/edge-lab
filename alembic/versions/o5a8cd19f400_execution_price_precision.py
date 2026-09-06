"""Preserve USD per atomic-token execution prices without rewriting old evidence."""
from alembic import op
import sqlalchemy as sa

revision = "o5a8cd19f400"
down_revision = "n4f7bc08e399"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("forward_execution_records") as batch:
        for column in ("paper_average_price", "shadow_average_price"):
            batch.alter_column(column, existing_type=sa.Numeric(28, 10), type_=sa.Numeric(50, 30), existing_nullable=True)


def downgrade():
    # A precision reduction would silently destroy observed prices.
    raise RuntimeError("execution price precision cannot be reduced without evidence loss")
