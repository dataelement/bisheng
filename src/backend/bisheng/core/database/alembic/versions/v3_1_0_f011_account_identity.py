"""Add identity rule metadata without rewriting historical identity values."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import (
    column_exists,
    index_exists,
    table_exists,
    unique_constraint_exists,
)

revision = "v310b1_f011_account_identity"
down_revision = "v310b1_f004_workflow_soft_delete"
branch_labels = None
depends_on = None

_OLD_UNIQUE = "uk_user_source_external_id"
_NEW_UNIQUE = "uk_user_source_account_match"


def _legacy_name_type():
    connection = op.get_bind()
    if connection.dialect.name == "mysql":
        inspector = sa.inspect(connection)
        table = next(name for name in inspector.get_table_names() if name.casefold() == "user")
        original = next(column for column in inspector.get_columns(table) if column["name"].casefold() == "user_name")
        # The deprecated SSO protocol compared user_name. Copy its character
        # set/collation on upgrades, including a deployment's custom policy.
        return original["type"].copy()
    # DM8 applies the same database-level character comparison to both fields.
    return sa.String(128)


def _drop_unique(name: str) -> None:
    if unique_constraint_exists("user", name):
        op.drop_constraint(name, "user", type_="unique")
    elif index_exists("user", name):
        op.drop_index(name, table_name="user")


def upgrade() -> None:
    if not table_exists("user"):
        return
    columns = (
        sa.Column("account_rule_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("account_match_key", sa.String(64), nullable=False, server_default=sa.text("'legacy'")),
        sa.Column("nickname_customized", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("legacy_sso_name", _legacy_name_type(), nullable=True),
    )
    for column in columns:
        if not column_exists("user", column.name):
            op.add_column("user", column)
    if not unique_constraint_exists("user", _NEW_UNIQUE) and not index_exists("user", _NEW_UNIQUE):
        op.create_unique_constraint(_NEW_UNIQUE, "user", ["source", "external_id", "account_match_key"])
    _drop_unique(_OLD_UNIQUE)
    if not index_exists("user", "ix_user_legacy_sso_name"):
        op.create_index("ix_user_legacy_sso_name", "user", ["legacy_sso_name"])


def downgrade() -> None:
    if not table_exists("user"):
        return
    conditions = []
    columns = []
    if column_exists("user", "account_rule_version"):
        version = sa.column("account_rule_version", sa.Integer())
        columns.append(version)
        conditions.append(version != 0)
    if column_exists("user", "nickname_customized"):
        customized = sa.column("nickname_customized", sa.Boolean())
        columns.append(customized)
        conditions.append(customized == sa.true())
    if column_exists("user", "legacy_sso_name"):
        alias = sa.column("legacy_sso_name", sa.String(128))
        columns.append(alias)
        conditions.append(alias.is_not(None))
    connection = op.get_bind()
    if conditions:
        users = sa.table("user", *columns)
        count = connection.execute(
            sa.select(sa.func.count()).select_from(users).where(sa.or_(*conditions))
        ).scalar_one()
        if count:
            raise RuntimeError("Active identity rules exist; use a reviewed forward repair instead of rollback")
    if table_exists("user_account_reservation"):
        count = connection.execute(
            sa.select(sa.func.count()).select_from(sa.table("user_account_reservation"))
        ).scalar_one()
        if count:
            raise RuntimeError("Reserved identities exist; direct rollback would lose account protection")
    if not unique_constraint_exists("user", _OLD_UNIQUE) and not index_exists("user", _OLD_UNIQUE):
        op.create_unique_constraint(_OLD_UNIQUE, "user", ["source", "external_id"])
    _drop_unique(_NEW_UNIQUE)
    if index_exists("user", "ix_user_legacy_sso_name"):
        op.drop_index("ix_user_legacy_sso_name", table_name="user")
    for name in ("legacy_sso_name", "nickname_customized", "account_match_key", "account_rule_version"):
        if column_exists("user", name):
            op.drop_column("user", name)
