"""Snapshot per-model credit rates and preserve raw provider usage."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import column_exists

revision = "f062_credit_multiplier"
down_revision = "f062_unified_model_access"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("dsh_model_visibility", "dsh_model_call"):
        if not column_exists(table, "credit_rate"):
            op.add_column(
                table, sa.Column("credit_rate", sa.BigInteger(), nullable=False, server_default=sa.text("100"))
            )
    if not column_exists("dsh_model_call", "billed_tokens"):
        op.add_column("dsh_model_call", sa.Column("billed_tokens", sa.BigInteger(), nullable=True))


def downgrade():
    if column_exists("dsh_model_call", "billed_tokens"):
        op.drop_column("dsh_model_call", "billed_tokens")
    for table in ("dsh_model_call", "dsh_model_visibility"):
        if column_exists(table, "credit_rate"):
            op.drop_column(table, "credit_rate")
