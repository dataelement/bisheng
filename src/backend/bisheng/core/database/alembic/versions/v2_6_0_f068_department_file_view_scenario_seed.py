"""初始化当前默认部署上下文的部门文件查看固定审批场景。

Revision ID: f068_department_file_view_scenario_seed
Revises: f067_department_file_view_grant
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import JsonType, table_exists

revision: str = "f068_department_file_view_scenario_seed"
down_revision: str | Sequence[str] | None = "f067_department_file_view_grant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_CONTEXT_ID = 1
SCENARIO_CODE = "department_file_view_request"
SCENARIO_NAME = "部门文件查看审批"
FLOW_CODE = "department_file_view_fixed_flow"
FLOW_NAME = "部门文件查看固定审批流"
ROUTE_NAME = "部门文件查看固定审批路由"
NODE_CODE = "department_file_owner_approvers"
NODE_NAME = "文件所属部门管理员审批"

_REQUIRED_TABLES = (
    "approval_scenario",
    "approval_route_rule",
    "approval_flow_definition",
    "approval_flow_version",
    "approval_node_definition",
)


def _tables():
    scenario = sa.table(
        "approval_scenario",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("scenario_code", sa.String()),
        sa.column("scenario_name", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
    )
    route = sa.table(
        "approval_route_rule",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("scenario_id", sa.Integer()),
        sa.column("route_name", sa.String()),
        sa.column("route_type", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("flow_definition_id", sa.Integer()),
        sa.column("match_config", JsonType()),
        sa.column("enabled", sa.Boolean()),
    )
    flow = sa.table(
        "approval_flow_definition",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("scenario_id", sa.Integer()),
        sa.column("flow_code", sa.String()),
        sa.column("flow_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    version = sa.table(
        "approval_flow_version",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("flow_definition_id", sa.Integer()),
        sa.column("version_no", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("definition_snapshot", JsonType()),
    )
    node = sa.table(
        "approval_node_definition",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("flow_version_id", sa.Integer()),
        sa.column("node_code", sa.String()),
        sa.column("node_name", sa.String()),
        sa.column("node_order", sa.Integer()),
        sa.column("node_mode", sa.String()),
        sa.column("approver_config", JsonType()),
        sa.column("extra_config", JsonType()),
    )
    return scenario, route, flow, version, node


def _scalar_id(connection, statement) -> int | None:
    value = connection.execute(statement).scalar()
    return int(value) if value is not None else None


def _ensure_seed(connection) -> None:
    scenario, route, flow, version, node = _tables()

    scenario_id = _scalar_id(
        connection,
        sa.select(scenario.c.id).where(
            scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
            scenario.c.scenario_code == SCENARIO_CODE,
        ),
    )
    if scenario_id is None:
        connection.execute(
            sa.insert(scenario).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_code=SCENARIO_CODE,
                scenario_name=SCENARIO_NAME,
                display_name=SCENARIO_NAME,
                enabled=True,
            )
        )
        scenario_id = _scalar_id(
            connection,
            sa.select(scenario.c.id).where(
                scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
                scenario.c.scenario_code == SCENARIO_CODE,
            ),
        )
    if scenario_id is None:
        raise RuntimeError("固定审批场景初始化失败")

    flow_id = _scalar_id(
        connection,
        sa.select(flow.c.id).where(
            flow.c.tenant_id == DEFAULT_CONTEXT_ID,
            flow.c.flow_code == FLOW_CODE,
        ),
    )
    if flow_id is None:
        connection.execute(
            sa.insert(flow).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_id=scenario_id,
                flow_code=FLOW_CODE,
                flow_name=FLOW_NAME,
                is_active=True,
            )
        )
        flow_id = _scalar_id(
            connection,
            sa.select(flow.c.id).where(
                flow.c.tenant_id == DEFAULT_CONTEXT_ID,
                flow.c.flow_code == FLOW_CODE,
            ),
        )
    if flow_id is None:
        raise RuntimeError("固定审批流初始化失败")

    version_id = _scalar_id(
        connection,
        sa.select(version.c.id)
        .where(
            version.c.flow_definition_id == flow_id,
            version.c.is_active.is_(True),
        )
        .order_by(version.c.version_no.desc()),
    )
    if version_id is None:
        connection.execute(
            sa.insert(version).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                flow_definition_id=flow_id,
                version_no=1,
                is_active=True,
                definition_snapshot={
                    "contract": SCENARIO_CODE,
                    "version": 1,
                    "node_code": NODE_CODE,
                    "node_mode": "or",
                },
            )
        )
        version_id = _scalar_id(
            connection,
            sa.select(version.c.id).where(
                version.c.flow_definition_id == flow_id,
                version.c.is_active.is_(True),
            ),
        )
    if version_id is None:
        raise RuntimeError("固定审批流版本初始化失败")

    node_id = _scalar_id(
        connection,
        sa.select(node.c.id).where(
            node.c.flow_version_id == version_id,
            node.c.node_code == NODE_CODE,
        ),
    )
    if node_id is None:
        connection.execute(
            sa.insert(node).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                flow_version_id=version_id,
                node_code=NODE_CODE,
                node_name=NODE_NAME,
                node_order=0,
                node_mode="or",
                approver_config={
                    "sources": [{"type": "department_file_approvers"}],
                },
                extra_config={"system_managed": True},
            )
        )

    route_id = _scalar_id(
        connection,
        sa.select(route.c.id).where(
            route.c.tenant_id == DEFAULT_CONTEXT_ID,
            route.c.scenario_id == scenario_id,
            route.c.route_name == ROUTE_NAME,
        ),
    )
    if route_id is None:
        connection.execute(
            sa.insert(route).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_id=scenario_id,
                route_name=ROUTE_NAME,
                route_type="approval",
                sort_order=0,
                flow_definition_id=flow_id,
                match_config={},
                enabled=True,
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    if not all(table_exists(connection, table_name) for table_name in _REQUIRED_TABLES):
        return
    _ensure_seed(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if not all(table_exists(connection, table_name) for table_name in _REQUIRED_TABLES):
        return
    scenario, route, flow, version, node = _tables()
    scenario_id = _scalar_id(
        connection,
        sa.select(scenario.c.id).where(
            scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
            scenario.c.scenario_code == SCENARIO_CODE,
        ),
    )
    if scenario_id is None:
        return
    flow_ids = list(
        connection.execute(
            sa.select(flow.c.id).where(
                flow.c.tenant_id == DEFAULT_CONTEXT_ID,
                flow.c.scenario_id == scenario_id,
                flow.c.flow_code == FLOW_CODE,
            )
        ).scalars()
    )
    if flow_ids:
        version_ids = list(
            connection.execute(sa.select(version.c.id).where(version.c.flow_definition_id.in_(flow_ids))).scalars()
        )
        if version_ids:
            connection.execute(sa.delete(node).where(node.c.flow_version_id.in_(version_ids)))
            connection.execute(sa.delete(version).where(version.c.id.in_(version_ids)))
        connection.execute(
            sa.delete(route).where(
                route.c.scenario_id == scenario_id,
                route.c.flow_definition_id.in_(flow_ids),
            )
        )
        connection.execute(sa.delete(flow).where(flow.c.id.in_(flow_ids)))
    connection.execute(sa.delete(route).where(route.c.scenario_id == scenario_id))
    connection.execute(sa.delete(scenario).where(scenario.c.id == scenario_id))
