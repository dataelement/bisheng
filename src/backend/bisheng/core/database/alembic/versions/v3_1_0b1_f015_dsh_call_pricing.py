"""F015: per-call price snapshot, spend and billing currency on dsh_model_call.

Nullable, additive columns only. Pre-F015 rows keep NULL and are still billed by
their legacy multiplier on replay; nothing is backfilled here.
"""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import JsonType

revision = "v310b1_f015_dsh_call_pricing"
down_revision = "v310b1_merge_work130_heads"
branch_labels = None
depends_on = None

TABLE = "dsh_model_call"


def _columns() -> list[sa.Column]:
    return [
        sa.Column("pricing", JsonType(), nullable=True),
        sa.Column("cost_micro", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
    ]


def upgrade():
    # A fresh install gets these columns from create_all with the rest of the table.
    if not table_exists(TABLE):
        return
    for column in _columns():
        if not column_exists(TABLE, column.name):
            op.add_column(TABLE, column)


def downgrade():
    raise RuntimeError(
        "Call price evidence must be retained; roll back by restoring the pre-upgrade backup (F015 runbook)"
    )
