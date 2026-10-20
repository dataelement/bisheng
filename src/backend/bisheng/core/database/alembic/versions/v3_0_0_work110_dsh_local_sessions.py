"""Allow native desktop events without commercial seat identity; DDL only."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import table_exists

revision = "work110_dsh_local_sessions"
down_revision = "f062_work110_audit_tree"
branch_labels = None
depends_on = None


def upgrade():
    table = "dsh_model_call"
    if not table_exists(table):
        return
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {item["name"].lower(): item for item in inspector.get_columns(table)}
    for name, datatype in (("seat_id", sa.String(36)), ("grant_version", sa.BigInteger())):
        if name in columns and not columns[name]["nullable"]:
            op.alter_column(table, name, existing_type=datatype, nullable=True)
    for constraint in inspector.get_check_constraints(table):
        if (constraint.get("name") or "").lower() == "ck_dsh_call_versions":
            op.drop_constraint(constraint["name"], table, type_="check")
            break
    op.create_check_constraint(
        "ck_dsh_call_versions",
        table,
        "(grant_version IS NULL OR grant_version >= 1) AND event_version >= 1 AND quota_epoch >= 1 AND policy_version >= 1",
    )


def downgrade():
    # Local events and historical evidence must remain readable after rollback.
    pass
