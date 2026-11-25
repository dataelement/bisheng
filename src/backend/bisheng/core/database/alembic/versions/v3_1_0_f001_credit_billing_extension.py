"""F001 credit billing extension: tool pricing, tool calls, call source_type/source_id, usage_type."""

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.alembic_helpers.online import (
    column_exists,
    get_check_constraint,
    index_exists,
    table_exists,
    unique_constraint_exists,
)
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType, update_time_server_default

revision = "v310_f001_credit_billing_extension"
down_revision = "v310b2_merge_f016_pricing_memory_heads"
branch_labels = None
depends_on = None

_OLD_USAGE_UQ = "uq_dsh_usage_user_model_month"
_NEW_USAGE_UQ = "uq_dsh_usage_user_type_model_month"
_USAGE_TYPE_CK = "ck_dsh_usage_type"


def _find_unique_name(table: str, constraint: str) -> str | None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_table = next((name for name in inspector.get_table_names() if name.casefold() == table.casefold()), None)
    if actual_table is None:
        return None
    for item in inspector.get_unique_constraints(actual_table):
        name = item.get("name")
        if name and name.casefold() == constraint.casefold():
            return name
    return None


def _drop_unique(table: str, constraint: str) -> None:
    actual_name = _find_unique_name(table, constraint)
    if actual_name:
        op.drop_constraint(actual_name, table, type_="unique")
    elif index_exists(table, constraint):
        op.drop_index(constraint, table_name=table)


def _upgrade_tool_pricing(conn) -> None:
    if table_exists("dsh_tool_pricing"):
        return
    update_default = UPDATE_TIME_SERVER_DEFAULT if conn.dialect.name == "sqlite" else update_time_server_default(conn)
    op.create_table(
        "dsh_tool_pricing",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_id", sa.BigInteger(), nullable=False),
        sa.Column("pricing_mode", sa.String(16), nullable=False, server_default=sa.text("'CREDITS'")),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("price_micro", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("call_count", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("update_time", sa.DateTime(), nullable=False, server_default=update_default),
        sa.UniqueConstraint("tenant_id", "tool_id", name="uq_dsh_tool_pricing_tenant_tool"),
        sa.CheckConstraint("pricing_mode IN ('MONEY', 'CREDITS')", name="ck_dsh_tool_pricing_mode"),
        sa.CheckConstraint("currency IS NULL OR currency IN ('CNY', 'USD')", name="ck_dsh_tool_pricing_currency"),
        sa.CheckConstraint("price_micro >= 0", name="ck_dsh_tool_pricing_price"),
        sa.CheckConstraint("call_count >= 1 AND call_count <= 1000000", name="ck_dsh_tool_pricing_call_count"),
        sa.CheckConstraint("version >= 1", name="ck_dsh_tool_pricing_version"),
    )
    op.create_index("ix_dsh_tool_pricing_tenant_id", "dsh_tool_pricing", ["tenant_id"])
    op.create_index("ix_dsh_tool_pricing_tool_id", "dsh_tool_pricing", ["tool_id"])


def _upgrade_tool_call() -> None:
    if table_exists("dsh_tool_call"):
        return
    op.create_table(
        "dsh_tool_call",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("usage_month", sa.String(7), nullable=False),
        sa.Column("tool_group_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_group_name", sa.String(256), nullable=True),
        sa.Column("tool_id", sa.BigInteger(), nullable=False),
        sa.Column("tool_key", sa.String(128), nullable=False),
        sa.Column("engine", sa.String(64), nullable=True),
        sa.Column("pricing_snapshot", JsonType, nullable=True),
        sa.Column("billed_tokens", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_micro", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("billed_tokens >= 0", name="ck_dsh_tool_call_billed_tokens"),
        sa.CheckConstraint("cost_micro IS NULL OR cost_micro >= 0", name="ck_dsh_tool_call_cost"),
        sa.CheckConstraint("result IN ('success', 'failed', 'timeout', 'cancelled')", name="ck_dsh_tool_call_result"),
    )
    op.create_index("ix_dsh_tool_call_tenant_id", "dsh_tool_call", ["tenant_id"])
    op.create_index("ix_dsh_tool_call_user_started", "dsh_tool_call", ["tenant_id", "user_id", "started_at"])
    op.create_index("ix_dsh_tool_call_key_started", "dsh_tool_call", ["tenant_id", "tool_key", "started_at"])


def _upgrade_model_call() -> None:
    if not table_exists("dsh_model_call"):
        return
    if not column_exists("dsh_model_call", "source_type"):
        op.add_column("dsh_model_call", sa.Column("source_type", sa.String(32), nullable=True))
    if not column_exists("dsh_model_call", "source_id"):
        op.add_column("dsh_model_call", sa.Column("source_id", sa.String(64), nullable=True))


def _upgrade_monthly_usage(conn) -> None:
    if not table_exists("dsh_monthly_usage"):
        return
    if not column_exists("dsh_monthly_usage", "usage_type"):
        op.add_column(
            "dsh_monthly_usage",
            sa.Column("usage_type", sa.String(16), nullable=False, server_default=sa.text("'MODEL'")),
        )
    if conn.dialect.name == "sqlite":
        old_name = _find_unique_name("dsh_monthly_usage", _OLD_USAGE_UQ)
        need_new_uq = not unique_constraint_exists("dsh_monthly_usage", _NEW_USAGE_UQ)
        need_ck = get_check_constraint("dsh_monthly_usage", _USAGE_TYPE_CK) is None
        if old_name or need_new_uq or need_ck:
            with op.batch_alter_table("dsh_monthly_usage") as batch:
                if old_name:
                    batch.drop_constraint(old_name, type_="unique")
                if need_new_uq:
                    batch.create_unique_constraint(
                        _NEW_USAGE_UQ, ["tenant_id", "user_id", "usage_month", "usage_type", "model_id"]
                    )
                if need_ck:
                    batch.create_check_constraint(_USAGE_TYPE_CK, "usage_type IN ('MODEL', 'TOOL')")
        return

    if not unique_constraint_exists("dsh_monthly_usage", _NEW_USAGE_UQ) and not index_exists(
        "dsh_monthly_usage", _NEW_USAGE_UQ
    ):
        op.create_unique_constraint(
            _NEW_USAGE_UQ, "dsh_monthly_usage", ["tenant_id", "user_id", "usage_month", "usage_type", "model_id"]
        )
    _drop_unique("dsh_monthly_usage", _OLD_USAGE_UQ)
    if get_check_constraint("dsh_monthly_usage", _USAGE_TYPE_CK) is None:
        op.create_check_constraint(_USAGE_TYPE_CK, "dsh_monthly_usage", "usage_type IN ('MODEL', 'TOOL')")


def upgrade() -> None:
    conn = op.get_bind()
    _upgrade_tool_pricing(conn)
    _upgrade_tool_call()
    _upgrade_model_call()
    _upgrade_monthly_usage(conn)


def _downgrade_monthly_usage(conn) -> None:
    if not table_exists("dsh_monthly_usage"):
        return
    if column_exists("dsh_monthly_usage", "usage_type"):
        conn.exec_driver_sql("DELETE FROM dsh_monthly_usage WHERE usage_type = 'TOOL'")
    if conn.dialect.name == "sqlite":
        new_name = _find_unique_name("dsh_monthly_usage", _NEW_USAGE_UQ)
        ck = get_check_constraint("dsh_monthly_usage", _USAGE_TYPE_CK)
        need_old_uq = not unique_constraint_exists("dsh_monthly_usage", _OLD_USAGE_UQ)
        with op.batch_alter_table("dsh_monthly_usage") as batch:
            if new_name:
                batch.drop_constraint(new_name, type_="unique")
            if ck is not None:
                batch.drop_constraint(ck["name"], type_="check")
            if need_old_uq:
                batch.create_unique_constraint(_OLD_USAGE_UQ, ["tenant_id", "user_id", "usage_month", "model_id"])
            if column_exists("dsh_monthly_usage", "usage_type"):
                batch.drop_column("usage_type")
        return

    ck = get_check_constraint("dsh_monthly_usage", _USAGE_TYPE_CK)
    if ck is not None:
        op.drop_constraint(ck["name"], "dsh_monthly_usage", type_="check")
    if not unique_constraint_exists("dsh_monthly_usage", _OLD_USAGE_UQ) and not index_exists(
        "dsh_monthly_usage", _OLD_USAGE_UQ
    ):
        op.create_unique_constraint(
            _OLD_USAGE_UQ, "dsh_monthly_usage", ["tenant_id", "user_id", "usage_month", "model_id"]
        )
    _drop_unique("dsh_monthly_usage", _NEW_USAGE_UQ)
    if column_exists("dsh_monthly_usage", "usage_type"):
        op.drop_column("dsh_monthly_usage", "usage_type")


def downgrade() -> None:
    conn = op.get_bind()
    _downgrade_monthly_usage(conn)
    if table_exists("dsh_model_call"):
        if column_exists("dsh_model_call", "source_id"):
            op.drop_column("dsh_model_call", "source_id")
        if column_exists("dsh_model_call", "source_type"):
            op.drop_column("dsh_model_call", "source_type")
    if table_exists("dsh_tool_call"):
        for idx in ("ix_dsh_tool_call_key_started", "ix_dsh_tool_call_user_started", "ix_dsh_tool_call_tenant_id"):
            if index_exists("dsh_tool_call", idx):
                op.drop_index(idx, table_name="dsh_tool_call")
        op.drop_table("dsh_tool_call")
    if table_exists("dsh_tool_pricing"):
        for idx in ("ix_dsh_tool_pricing_tool_id", "ix_dsh_tool_pricing_tenant_id"):
            if index_exists("dsh_tool_pricing", idx):
                op.drop_index(idx, table_name="dsh_tool_pricing")
        op.drop_table("dsh_tool_pricing")
