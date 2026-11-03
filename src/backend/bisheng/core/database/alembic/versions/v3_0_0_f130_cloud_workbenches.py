"""Add hosted workbench tables and hosted-app credential subjects on the 130 line."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlmodel import SQLModel

from bisheng.core.database.alembic_helpers.online import column_exists, table_exists
from bisheng.core.database.dialect_helpers import LargeText, get_column_type

revision = "f130_cloud_workbenches"
down_revision = "f111_matched_words"
branch_labels = None
depends_on = None


def widen_existing_byte_counters():
    """Preserve large artifacts when an environment already has runtime tables."""
    conn = op.get_bind()
    for table, column in (("runtime_artifact", "size_bytes"), ("runtime_transfer", "offset")):
        if not table_exists(table) or not column_exists(table, column):
            continue
        kind = (get_column_type(conn, table, column) or "").lower()
        if kind in {"bigint", "biginteger"}:
            continue
        if kind not in {"int", "integer"}:
            raise RuntimeError(f"Unexpected byte-counter column type: {table}.{column}")
        op.alter_column(table, column, type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)


def add_release_notes_columns():
    for table in ("app_deployment", "app_version"):
        if table_exists(table) and not column_exists(table, "release_notes"):
            op.add_column(table, sa.Column("release_notes", LargeText(), nullable=True))


def upgrade():
    from bisheng.core.database.model_discovery import import_all_sqlmodel_models

    import_all_sqlmodel_models()
    bind = op.get_bind()
    # Bootstrap and upgrades use the same dialect-neutral ORM schema.
    import importlib

    from bisheng.core.database.model_discovery import discover_sqlmodel_module_names

    legacy = {
        "bisheng.database.models." + name
        for name in ("app", "app_version", "app_instance", "app_access_log", "resource_tier")
    }
    cloud_tables = set()
    for name in discover_sqlmodel_module_names():
        if name not in legacy and not name.startswith(("bisheng.app_publish.", "bisheng.app_runtime.")):
            continue
        module = importlib.import_module(name)
        for value in vars(module).values():
            if isinstance(value, type) and getattr(value, "__module__", None) == name and hasattr(value, "__table__"):
                cloud_tables.add(value.__table__)
    SQLModel.metadata.create_all(
        bind, tables=[table for table in SQLModel.metadata.sorted_tables if table in cloud_tables]
    )
    add_release_notes_columns()
    widen_existing_byte_counters()
    if bind.dialect.name == "sqlite" or "api_credential" not in inspect(bind).get_table_names():
        return
    checks = inspect(bind).get_check_constraints("api_credential")
    existing = next((check for check in checks if check["name"] == "ck_api_credential_subject_kind"), None)
    if existing and "hosted_app" in existing.get("sqltext", ""):
        return
    with op.batch_alter_table("api_credential") as batch:
        if existing:
            batch.drop_constraint("ck_api_credential_subject_kind", type_="check")
        batch.create_check_constraint(
            "ck_api_credential_subject_kind", "subject_kind IN ('service_account', 'natural_person', 'hosted_app')"
        )


def downgrade():
    # Preserve released applications, credentials and shared data on rollback.
    pass
