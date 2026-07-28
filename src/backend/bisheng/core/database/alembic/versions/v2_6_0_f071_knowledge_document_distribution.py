"""Add single-entity document publish/share distribution state.

Revision ID: f071_knowledge_document_distribution
Revises: f070_department_transfer_permission_cleanup
Create Date: 2026-07-27
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from bisheng.core.database.dialect_helpers import (
    JsonType,
    column_exists,
    constraint_exists,
    index_exists,
    is_column_nullable,
    table_exists,
)

revision: str = "f071_knowledge_document_distribution"
down_revision: str | Sequence[str] | None = (
    "f070_department_transfer_permission_cleanup"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_TABLE = "knowledge_document"
FILE_TABLE = "knowledgefile"
VERSION_TABLE = "knowledge_document_version"
SPACE_TABLE = "knowledge"

SHARE_SCENARIO_CODE = "knowledge_space_file_share_request"
SHARE_SCENARIO_NAME = "部门知识文件分享审批"
SHARE_FLOW_CODE = "knowledge_space_file_share_fixed_flow"
SHARE_FLOW_NAME = "部门知识文件分享固定审批流"
SHARE_ROUTE_NAME = "部门知识文件分享固定审批路由"
SHARE_SOURCE_NODE_CODE = "share_source_space_approvers"
SHARE_TARGET_NODE_CODE = "share_target_space_approvers"
DEFAULT_CONTEXT_ID = 1
SEED_OWNER_KEY = "migration_owner"
SEED_OWNER_VALUE = revision

_APPROVAL_TABLES = (
    "approval_scenario",
    "approval_route_rule",
    "approval_flow_definition",
    "approval_flow_version",
    "approval_node_definition",
)

_DOCUMENT_COLUMNS = (
    sa.Column("tenant_id", sa.Integer(), nullable=True),
    sa.Column("predecessor_logic_file_id", sa.Integer(), nullable=True),
    sa.Column(
        "content_generation",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "lifecycle_status",
        sa.String(16),
        nullable=False,
        server_default=sa.text("'active'"),
    ),
)

_FILE_COLUMNS = (
    sa.Column("reference_document_id", sa.Integer(), nullable=True),
    sa.Column("entry_type", sa.String(24), nullable=True),
    sa.Column("entry_status", sa.String(16), nullable=True),
    sa.Column("predecessor_logic_file_id", sa.Integer(), nullable=True),
    sa.Column("share_source_file_id", sa.Integer(), nullable=True),
    sa.Column(
        "allow_download",
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("approval_instance_id", sa.Integer(), nullable=True),
    sa.Column("projection_previous_file_id", sa.Integer(), nullable=True),
    sa.Column(
        "desired_content_generation",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "applied_content_generation",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "desired_entry_generation",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "applied_entry_generation",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "projection_status",
        sa.String(16),
        nullable=False,
        server_default=sa.text("'pending'"),
    ),
    sa.Column(
        "projection_retry_count",
        sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column("projection_next_retry_at", sa.DateTime(), nullable=True),
    sa.Column("projection_lease_owner", sa.String(64), nullable=True),
    sa.Column("projection_lease_until", sa.DateTime(), nullable=True),
    sa.Column("projection_last_error", sa.Text(), nullable=True),
)

_DOCUMENT_INDEXES = (
    (
        "idx_kdoc_tenant_lifecycle",
        ["tenant_id", "lifecycle_status"],
    ),
    (
        "idx_kdoc_tenant_content_generation",
        ["tenant_id", "content_generation"],
    ),
    (
        "idx_kdoc_tenant_predecessor",
        ["tenant_id", "predecessor_logic_file_id"],
    ),
)

_FILE_INDEXES = (
    (
        "idx_kfile_document_space_status",
        ["tenant_id", "reference_document_id", "knowledge_id", "entry_status"],
    ),
    (
        "idx_kfile_document_type_status",
        ["tenant_id", "reference_document_id", "entry_type", "entry_status"],
    ),
    (
        "idx_kfile_projection_retry_lease",
        [
            "tenant_id",
            "projection_status",
            "projection_next_retry_at",
            "projection_lease_until",
        ],
    ),
    (
        "idx_kfile_entry_cleanup",
        ["tenant_id", "entry_status", "projection_previous_file_id"],
    ),
    ("idx_kfile_predecessor", ["predecessor_logic_file_id"]),
    ("idx_kfile_share_source", ["share_source_file_id"]),
)


def _require_base_tables(connection: sa.Connection) -> None:
    missing = [
        table_name
        for table_name in (
            DOCUMENT_TABLE,
            FILE_TABLE,
            VERSION_TABLE,
            SPACE_TABLE,
        )
        if not table_exists(connection, table_name)
    ]
    if missing:
        raise RuntimeError(
            "F059 migration requires existing tables: " + ", ".join(missing)
        )


def _add_missing_columns(
    connection: sa.Connection,
    table_name: str,
    columns: tuple[sa.Column, ...],
) -> None:
    for column in columns:
        if not column_exists(connection, table_name, column.name):
            op.add_column(table_name, column.copy())


def _create_missing_indexes(
    connection: sa.Connection,
    table_name: str,
    indexes: tuple[tuple[str, list[str]], ...],
) -> None:
    for index_name, columns in indexes:
        if not index_exists(connection, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)


def _preflight_and_backfill_document_tenants(
    connection: sa.Connection,
) -> None:
    metadata = sa.MetaData()
    document = sa.Table(DOCUMENT_TABLE, metadata, autoload_with=connection)
    version = sa.Table(VERSION_TABLE, metadata, autoload_with=connection)
    knowledge_file = sa.Table(FILE_TABLE, metadata, autoload_with=connection)
    knowledge = sa.Table(SPACE_TABLE, metadata, autoload_with=connection)

    duplicate_file_ids = list(
        connection.execute(
            sa.select(version.c.knowledge_file_id)
            .group_by(version.c.knowledge_file_id)
            .having(sa.func.count() > 1)
        ).scalars()
    )
    if duplicate_file_ids:
        raise RuntimeError(
            "physical knowledge file is linked to multiple documents: "
            + ",".join(str(file_id) for file_id in duplicate_file_ids[:20])
        )

    documents = list(
        connection.execute(
            sa.select(
                document.c.id,
                document.c.knowledge_id,
                document.c.tenant_id,
            ).order_by(document.c.id.asc())
        ).mappings()
    )
    for row in documents:
        candidates = list(
            connection.execute(
                sa.select(
                    knowledge_file.c.tenant_id.label("file_tenant_id"),
                    knowledge_file.c.knowledge_id.label("file_space_id"),
                    knowledge.c.tenant_id.label("space_tenant_id"),
                )
                .select_from(
                    version.join(
                        knowledge_file,
                        version.c.knowledge_file_id == knowledge_file.c.id,
                    ).outerjoin(
                        knowledge,
                        knowledge.c.id == knowledge_file.c.knowledge_id,
                    )
                )
                .where(version.c.document_id == row["id"])
                .order_by(version.c.id.asc())
            ).mappings()
        )
        if not candidates:
            raise RuntimeError(
                f"cannot resolve tenant for knowledge_document {row['id']}"
            )

        tenant_ids: set[int] = set()
        for candidate in candidates:
            file_space_id = candidate["file_space_id"]
            file_tenant_id = candidate["file_tenant_id"]
            space_tenant_id = candidate["space_tenant_id"]
            if (
                file_space_id != row["knowledge_id"]
                or file_tenant_id is None
                or space_tenant_id is None
                or int(file_tenant_id) != int(space_tenant_id)
            ):
                raise RuntimeError(
                    f"tenant mismatch for knowledge_document {row['id']}"
                )
            tenant_ids.add(int(file_tenant_id))

        if len(tenant_ids) != 1:
            raise RuntimeError(
                f"cannot resolve tenant uniquely for knowledge_document {row['id']}"
            )
        tenant_id = next(iter(tenant_ids))
        if row["tenant_id"] is not None and int(row["tenant_id"]) != tenant_id:
            raise RuntimeError(
                f"tenant mismatch for knowledge_document {row['id']}"
            )
        connection.execute(
            sa.update(document)
            .where(document.c.id == row["id"])
            .values(tenant_id=tenant_id)
        )


def _approval_tables():
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


def _scalar_id(connection: sa.Connection, statement) -> int | None:
    value = connection.execute(statement).scalar()
    return int(value) if value is not None else None


def _json_mapping(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _seed_share_scenario(connection: sa.Connection) -> None:
    if not all(table_exists(connection, name) for name in _APPROVAL_TABLES):
        return

    scenario, route, flow, version, node = _approval_tables()
    created_scenario = False
    created_flow = False
    created_version = False
    scenario_id = _scalar_id(
        connection,
        sa.select(scenario.c.id).where(
            scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
            scenario.c.scenario_code == SHARE_SCENARIO_CODE,
        ),
    )
    if scenario_id is None:
        created_scenario = True
        connection.execute(
            sa.insert(scenario).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_code=SHARE_SCENARIO_CODE,
                scenario_name=SHARE_SCENARIO_NAME,
                display_name=SHARE_SCENARIO_NAME,
                enabled=True,
            )
        )
        scenario_id = _scalar_id(
            connection,
            sa.select(scenario.c.id).where(
                scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
                scenario.c.scenario_code == SHARE_SCENARIO_CODE,
            ),
        )
    if scenario_id is None:
        raise RuntimeError("cannot seed F059 share approval scenario")

    flow_id = _scalar_id(
        connection,
        sa.select(flow.c.id).where(
            flow.c.tenant_id == DEFAULT_CONTEXT_ID,
            flow.c.scenario_id == scenario_id,
            flow.c.flow_code == SHARE_FLOW_CODE,
        ),
    )
    if flow_id is None:
        conflicting_flow_scenario_id = _scalar_id(
            connection,
            sa.select(flow.c.scenario_id).where(
                flow.c.tenant_id == DEFAULT_CONTEXT_ID,
                flow.c.flow_code == SHARE_FLOW_CODE,
            ),
        )
        if conflicting_flow_scenario_id is not None:
            raise RuntimeError(
                "F059 share approval flow code belongs to another scenario"
            )
        created_flow = True
        connection.execute(
            sa.insert(flow).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_id=scenario_id,
                flow_code=SHARE_FLOW_CODE,
                flow_name=SHARE_FLOW_NAME,
                is_active=True,
            )
        )
        flow_id = _scalar_id(
            connection,
            sa.select(flow.c.id).where(
                flow.c.tenant_id == DEFAULT_CONTEXT_ID,
                flow.c.flow_code == SHARE_FLOW_CODE,
            ),
        )
    if flow_id is None:
        raise RuntimeError("cannot seed F059 share approval flow")

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
        created_version = True
        connection.execute(
            sa.insert(version).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                flow_definition_id=flow_id,
                version_no=1,
                is_active=True,
                definition_snapshot={
                    "contract": SHARE_SCENARIO_CODE,
                    "version": 1,
                    SEED_OWNER_KEY: SEED_OWNER_VALUE,
                    "node_codes": [
                        SHARE_SOURCE_NODE_CODE,
                        SHARE_TARGET_NODE_CODE,
                    ],
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
        raise RuntimeError("cannot seed F059 share approval flow version")

    node_definitions = (
        (
            SHARE_SOURCE_NODE_CODE,
            "分享方知识空间管理员审批",
            0,
            {
                "sources": [
                    {"type": "knowledge_space_owner"},
                    {"type": "knowledge_space_manager"},
                ]
            },
        ),
        (
            SHARE_TARGET_NODE_CODE,
            "接收方知识空间管理员审批",
            1,
            {
                "sources": [
                    {"type": "target_knowledge_space_owner"},
                    {"type": "target_knowledge_space_manager"},
                ]
            },
        ),
    )
    for node_code, node_name, node_order, approver_config in node_definitions:
        node_id = _scalar_id(
            connection,
            sa.select(node.c.id).where(
                node.c.flow_version_id == version_id,
                node.c.node_code == node_code,
            ),
        )
        if node_id is None:
            connection.execute(
                sa.insert(node).values(
                    tenant_id=DEFAULT_CONTEXT_ID,
                    flow_version_id=version_id,
                    node_code=node_code,
                    node_name=node_name,
                    node_order=node_order,
                    node_mode="or",
                    approver_config=approver_config,
                    extra_config={
                        "system_managed": True,
                        SEED_OWNER_KEY: SEED_OWNER_VALUE,
                    },
                )
            )

    route_row = connection.execute(
        sa.select(route.c.id, route.c.flow_definition_id).where(
            route.c.tenant_id == DEFAULT_CONTEXT_ID,
            route.c.scenario_id == scenario_id,
            route.c.route_name == SHARE_ROUTE_NAME,
        )
    ).mappings().first()
    if (
        route_row is not None
        and (
            route_row["flow_definition_id"] is None
            or int(route_row["flow_definition_id"]) != flow_id
        )
    ):
        raise RuntimeError(
            "F059 share approval route points to another flow"
        )
    route_id = (
        int(route_row["id"])
        if route_row is not None
        else None
    )
    if route_id is None:
        connection.execute(
            sa.insert(route).values(
                tenant_id=DEFAULT_CONTEXT_ID,
                scenario_id=scenario_id,
                route_name=SHARE_ROUTE_NAME,
                route_type="approval",
                sort_order=0,
                flow_definition_id=flow_id,
                match_config={
                    SEED_OWNER_KEY: SEED_OWNER_VALUE,
                    "created_scenario": created_scenario,
                    "created_flow": created_flow,
                    "created_version": created_version,
                },
                enabled=True,
            )
        )


def _delete_share_scenario_seed(connection: sa.Connection) -> None:
    if not all(table_exists(connection, name) for name in _APPROVAL_TABLES):
        return
    scenario, route, flow, version, node = _approval_tables()
    scenario_id = _scalar_id(
        connection,
        sa.select(scenario.c.id).where(
            scenario.c.tenant_id == DEFAULT_CONTEXT_ID,
            scenario.c.scenario_code == SHARE_SCENARIO_CODE,
        ),
    )
    if scenario_id is None:
        return
    flow_ids = list(
        connection.execute(
            sa.select(flow.c.id).where(
                flow.c.tenant_id == DEFAULT_CONTEXT_ID,
                flow.c.scenario_id == scenario_id,
                flow.c.flow_code == SHARE_FLOW_CODE,
            )
        ).scalars()
    )
    if not flow_ids:
        return

    route_rows = list(
        connection.execute(
            sa.select(
                route.c.id,
                route.c.flow_definition_id,
                route.c.match_config,
            ).where(
                route.c.scenario_id == scenario_id,
                route.c.flow_definition_id.in_(flow_ids),
            )
        ).mappings()
    )
    owned_route_rows = [
        row
        for row in route_rows
        if _json_mapping(row["match_config"]).get(SEED_OWNER_KEY)
        == SEED_OWNER_VALUE
    ]
    owned_route_ids = [int(row["id"]) for row in owned_route_rows]
    created_flow_ids = {
        int(row["flow_definition_id"])
        for row in owned_route_rows
        if _json_mapping(row["match_config"]).get("created_flow")
    }
    created_scenario = any(
        _json_mapping(row["match_config"]).get("created_scenario")
        for row in owned_route_rows
    )

    version_rows = list(
        connection.execute(
            sa.select(
                version.c.id,
                version.c.flow_definition_id,
                version.c.definition_snapshot,
            ).where(version.c.flow_definition_id.in_(flow_ids))
        ).mappings()
    )
    owned_version_ids = {
        int(row["id"])
        for row in version_rows
        if _json_mapping(row["definition_snapshot"]).get(SEED_OWNER_KEY)
        == SEED_OWNER_VALUE
    }
    version_ids = [int(row["id"]) for row in version_rows]
    owned_node_ids: set[int] = set()
    if version_ids:
        node_rows = list(
            connection.execute(
                sa.select(
                    node.c.id,
                    node.c.flow_version_id,
                    node.c.extra_config,
                ).where(node.c.flow_version_id.in_(version_ids))
            ).mappings()
        )
        owned_node_ids = {
            int(row["id"])
            for row in node_rows
            if int(row["flow_version_id"]) in owned_version_ids
            or _json_mapping(row["extra_config"]).get(SEED_OWNER_KEY)
            == SEED_OWNER_VALUE
        }
    if owned_node_ids:
        connection.execute(
            sa.delete(node).where(node.c.id.in_(owned_node_ids))
        )
    if owned_version_ids:
        connection.execute(
            sa.delete(version).where(version.c.id.in_(owned_version_ids))
        )
    if owned_route_ids:
        connection.execute(
            sa.delete(route).where(route.c.id.in_(owned_route_ids))
        )

    for flow_id in sorted(created_flow_ids):
        remaining_reference = connection.execute(
            sa.select(route.c.id)
            .where(route.c.flow_definition_id == flow_id)
            .limit(1)
        ).scalar()
        remaining_version = connection.execute(
            sa.select(version.c.id)
            .where(version.c.flow_definition_id == flow_id)
            .limit(1)
        ).scalar()
        if remaining_reference is None and remaining_version is None:
            connection.execute(
                sa.delete(flow).where(flow.c.id == flow_id)
            )

    if created_scenario:
        remaining_route = connection.execute(
            sa.select(route.c.id)
            .where(route.c.scenario_id == scenario_id)
            .limit(1)
        ).scalar()
        remaining_flow = connection.execute(
            sa.select(flow.c.id)
            .where(flow.c.scenario_id == scenario_id)
            .limit(1)
        ).scalar()
        if remaining_route is None and remaining_flow is None:
            connection.execute(
                sa.delete(scenario).where(scenario.c.id == scenario_id)
            )


def upgrade() -> None:
    connection = op.get_bind()
    _require_base_tables(connection)

    _add_missing_columns(connection, DOCUMENT_TABLE, _DOCUMENT_COLUMNS)
    _add_missing_columns(connection, FILE_TABLE, _FILE_COLUMNS)
    _preflight_and_backfill_document_tenants(connection)

    if is_column_nullable(connection, DOCUMENT_TABLE, "tenant_id"):
        op.alter_column(
            DOCUMENT_TABLE,
            "tenant_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    if not constraint_exists(
        connection,
        VERSION_TABLE,
        "uk_kdv_knowledge_file",
    ):
        op.create_unique_constraint(
            "uk_kdv_knowledge_file",
            VERSION_TABLE,
            ["knowledge_file_id"],
        )

    _create_missing_indexes(
        connection,
        DOCUMENT_TABLE,
        _DOCUMENT_INDEXES,
    )
    _create_missing_indexes(
        connection,
        FILE_TABLE,
        _FILE_INDEXES,
    )
    _seed_share_scenario(connection)


def _assert_distribution_downgrade_safe(
    connection: sa.Connection,
    *,
    now: datetime | None = None,
) -> None:
    """阻止在仍有分发状态时删除统一文档模型字段。"""

    now = now or datetime.now()
    metadata = sa.MetaData()

    if table_exists(connection, FILE_TABLE):
        file_table = sa.Table(
            FILE_TABLE,
            metadata,
            autoload_with=connection,
        )
        file_columns = file_table.c

        def has_file_columns(*names: str) -> bool:
            return all(name in file_columns for name in names)

        file_checks: list[tuple[str, sa.ColumnElement[bool]]] = []
        if has_file_columns("entry_type", "entry_status"):
            file_checks.extend(
                [
                    (
                        "active logical entry",
                        sa.and_(
                            file_columns.entry_type.in_(("publish", "share")),
                            file_columns.entry_status == "active",
                        ),
                    ),
                    (
                        "transitional entry",
                        file_columns.entry_status.in_(("preparing", "deleting")),
                    ),
                ]
            )
        if has_file_columns("entry_type"):
            file_checks.append(
                (
                    "projection tombstone",
                    file_columns.entry_type == "projection_tombstone",
                )
            )
        if has_file_columns(
            "desired_content_generation",
            "applied_content_generation",
            "desired_entry_generation",
            "applied_entry_generation",
        ):
            file_checks.append(
                (
                    "projection generation lag",
                    sa.or_(
                        file_columns.desired_content_generation
                        > file_columns.applied_content_generation,
                        file_columns.desired_entry_generation
                        > file_columns.applied_entry_generation,
                    ),
                )
            )
        if has_file_columns("projection_status"):
            file_checks.append(
                (
                    "unfinished projection",
                    file_columns.projection_status.in_(
                        ("pending", "processing", "failed")
                    ),
                )
            )
        lease_conditions: list[sa.ColumnElement[bool]] = []
        if has_file_columns("projection_lease_owner"):
            lease_conditions.append(
                sa.and_(
                    file_columns.projection_lease_owner.is_not(None),
                    file_columns.projection_lease_owner != "",
                )
            )
        if has_file_columns("projection_lease_until"):
            lease_conditions.append(
                file_columns.projection_lease_until > now
            )
        if lease_conditions:
            file_checks.append(
                ("projection lease", sa.or_(*lease_conditions))
            )

        for unsafe_state, predicate in file_checks:
            exists = connection.execute(
                sa.select(file_table.c.id).where(predicate).limit(1)
            ).scalar()
            if exists is not None:
                raise RuntimeError(
                    "Unsafe knowledge distribution downgrade: "
                    f"{unsafe_state} exists"
                )

    if table_exists(connection, DOCUMENT_TABLE):
        document_table = sa.Table(
            DOCUMENT_TABLE,
            metadata,
            autoload_with=connection,
        )
        if "lifecycle_status" in document_table.c:
            exists = connection.execute(
                sa.select(document_table.c.id)
                .where(document_table.c.lifecycle_status == "deleting")
                .limit(1)
            ).scalar()
            if exists is not None:
                raise RuntimeError(
                    "Unsafe knowledge distribution downgrade: "
                    "deleting document exists"
                )


def downgrade() -> None:
    connection = op.get_bind()
    _assert_distribution_downgrade_safe(connection)
    _delete_share_scenario_seed(connection)

    if table_exists(connection, FILE_TABLE):
        for index_name, _ in reversed(_FILE_INDEXES):
            if index_exists(connection, FILE_TABLE, index_name):
                op.drop_index(index_name, table_name=FILE_TABLE)
    if table_exists(connection, DOCUMENT_TABLE):
        for index_name, _ in reversed(_DOCUMENT_INDEXES):
            if index_exists(connection, DOCUMENT_TABLE, index_name):
                op.drop_index(index_name, table_name=DOCUMENT_TABLE)
    if table_exists(connection, VERSION_TABLE) and constraint_exists(
        connection,
        VERSION_TABLE,
        "uk_kdv_knowledge_file",
    ):
        op.drop_constraint(
            "uk_kdv_knowledge_file",
            VERSION_TABLE,
            type_="unique",
        )

    if table_exists(connection, FILE_TABLE):
        for column in reversed(_FILE_COLUMNS):
            if column_exists(connection, FILE_TABLE, column.name):
                op.drop_column(FILE_TABLE, column.name)
    if table_exists(connection, DOCUMENT_TABLE):
        for column in reversed(_DOCUMENT_COLUMNS):
            if column_exists(connection, DOCUMENT_TABLE, column.name):
                op.drop_column(DOCUMENT_TABLE, column.name)
