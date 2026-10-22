"""Remove mandatory seat identity from main's existing model-call table; DDL only."""

import sqlalchemy as sa
from alembic import op

revision = "work110_dsh_local_sessions"
down_revision = "f065_dsh_install_policy_default_off"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    table = next((name for name in inspector.get_table_names() if name.lower() == "dsh_model_call"), None)
    if table is None:
        return
    columns = {item["name"].lower(): item for item in inspector.get_columns(table)}
    for name, datatype in (("seat_id", sa.String(36)), ("grant_version", sa.BigInteger())):
        if name in columns and not columns[name]["nullable"]:
            op.alter_column(table, columns[name]["name"], existing_type=datatype, nullable=True)
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
    # Native calls and audit evidence cannot be discarded to recreate a main baseline.
    pass
