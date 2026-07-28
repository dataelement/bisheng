"""Migration contracts for F059 document distribution."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.schema import CreateTable

MIGRATION_MODULE = (
    "bisheng.core.database.alembic.versions."
    "v2_6_0_f071_knowledge_document_distribution"
)


def _create_pre_f059_schema(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledge (
                id INTEGER PRIMARY KEY,
                tenant_id INTEGER NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledgefile (
                id INTEGER PRIMARY KEY,
                knowledge_id INTEGER NOT NULL,
                tenant_id INTEGER NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledge_document (
                id INTEGER PRIMARY KEY,
                knowledge_id INTEGER NOT NULL,
                tenant_id INTEGER NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledge_document_version (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL,
                knowledge_file_id INTEGER NOT NULL,
                version_no INTEGER NOT NULL
            )
            """
        )
    )


def _seed_consistent_document(connection: sa.Connection) -> None:
    connection.execute(
        sa.text("INSERT INTO knowledge(id, tenant_id) VALUES (12, 7)")
    )
    connection.execute(
        sa.text(
            "INSERT INTO knowledgefile(id, knowledge_id, tenant_id) "
            "VALUES (100, 12, 7)"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO knowledge_document(id, knowledge_id, tenant_id) "
            "VALUES (91, 12, NULL)"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO knowledge_document_version"
            "(id, document_id, knowledge_file_id, version_no) "
            "VALUES (501, 91, 100, 1)"
        )
    )


def test_migration_metadata_and_no_new_business_tables():
    migration = importlib.import_module(MIGRATION_MODULE)

    assert migration.revision == "f071_knowledge_document_distribution"
    assert migration.down_revision == "f070_department_transfer_permission_cleanup"
    assert not hasattr(migration, "PLACEMENT_TABLE")
    assert not hasattr(migration, "OUTBOX_TABLE")


def test_tenant_backfill_is_derived_from_version_file_and_space():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_pre_f059_schema(connection)
        _seed_consistent_document(connection)

        migration._preflight_and_backfill_document_tenants(connection)

        tenant_id = connection.execute(
            sa.text("SELECT tenant_id FROM knowledge_document WHERE id = 91")
        ).scalar_one()

    assert tenant_id == 7


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (
            "DELETE FROM knowledge_document_version WHERE document_id = 91",
            "cannot resolve tenant",
        ),
        (
            "UPDATE knowledgefile SET tenant_id = 8 WHERE id = 100",
            "tenant mismatch",
        ),
        (
            "UPDATE knowledge SET tenant_id = 8 WHERE id = 12",
            "tenant mismatch",
        ),
    ],
)
def test_tenant_backfill_stops_on_ambiguous_or_inconsistent_data(
    mutation: str,
    expected: str,
):
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_pre_f059_schema(connection)
        _seed_consistent_document(connection)
        connection.execute(sa.text(mutation))

        with pytest.raises(RuntimeError, match=expected):
            migration._preflight_and_backfill_document_tenants(connection)


def test_preflight_rejects_a_physical_file_linked_to_multiple_documents():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_pre_f059_schema(connection)
        _seed_consistent_document(connection)
        connection.execute(
            sa.text(
                "INSERT INTO knowledge_document(id, knowledge_id, tenant_id) "
                "VALUES (92, 12, NULL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO knowledge_document_version"
                "(id, document_id, knowledge_file_id, version_no) "
                "VALUES (502, 92, 100, 1)"
            )
        )

        with pytest.raises(RuntimeError, match="multiple documents"):
            migration._preflight_and_backfill_document_tenants(connection)


def _create_f059_downgrade_schema(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledge_document (
                id INTEGER PRIMARY KEY,
                lifecycle_status VARCHAR(16) NOT NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            CREATE TABLE knowledgefile (
                id INTEGER PRIMARY KEY,
                reference_document_id INTEGER NULL,
                entry_type VARCHAR(24) NULL,
                entry_status VARCHAR(16) NULL,
                desired_content_generation INTEGER NOT NULL,
                applied_content_generation INTEGER NOT NULL,
                desired_entry_generation INTEGER NOT NULL,
                applied_entry_generation INTEGER NOT NULL,
                projection_status VARCHAR(16) NOT NULL,
                projection_lease_owner VARCHAR(64) NULL,
                projection_lease_until DATETIME NULL
            )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO knowledge_document(id, lifecycle_status)
            VALUES (91, 'active')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO knowledgefile(
                id,
                reference_document_id,
                entry_type,
                entry_status,
                desired_content_generation,
                applied_content_generation,
                desired_entry_generation,
                applied_entry_generation,
                projection_status,
                projection_lease_owner,
                projection_lease_until
            ) VALUES (
                100,
                91,
                'manager',
                'active',
                1,
                1,
                1,
                1,
                'ready',
                NULL,
                NULL
            )
            """
        )
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            "UPDATE knowledgefile SET entry_type = 'publish'",
            "active logical entry",
        ),
        (
            "UPDATE knowledgefile SET entry_status = 'preparing'",
            "transitional entry",
        ),
        (
            "UPDATE knowledgefile SET entry_type = 'projection_tombstone'",
            "projection tombstone",
        ),
        (
            "UPDATE knowledgefile SET desired_content_generation = 2",
            "projection generation lag",
        ),
        (
            "UPDATE knowledgefile SET projection_status = 'failed'",
            "unfinished projection",
        ),
        (
            "UPDATE knowledgefile SET projection_lease_owner = 'worker-a'",
            "projection lease",
        ),
        (
            "UPDATE knowledge_document SET lifecycle_status = 'deleting'",
            "deleting document",
        ),
    ],
)
def test_downgrade_preflight_rejects_live_distribution_state(
    mutation: str,
    expected: str,
):
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_f059_downgrade_schema(connection)
        connection.execute(sa.text(mutation))

        with pytest.raises(RuntimeError, match=expected):
            migration._assert_distribution_downgrade_safe(
                connection,
                now=datetime.now() + timedelta(seconds=1),
            )


def test_downgrade_preflight_allows_settled_manager_only_state():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_f059_downgrade_schema(connection)

        migration._assert_distribution_downgrade_safe(
            connection,
            now=datetime.now(),
        )


def test_downgrade_runs_preflight_before_seed_or_schema_changes(monkeypatch):
    migration = importlib.import_module(MIGRATION_MODULE)
    connection = Mock()
    stop = RuntimeError("unsafe downgrade")
    preflight = Mock(side_effect=stop)
    seed_delete = Mock()
    monkeypatch.setattr(migration.op, "get_bind", Mock(return_value=connection))
    monkeypatch.setattr(
        migration,
        "_assert_distribution_downgrade_safe",
        preflight,
        raising=False,
    )
    monkeypatch.setattr(
        migration,
        "_delete_share_scenario_seed",
        seed_delete,
    )

    with pytest.raises(RuntimeError, match="unsafe downgrade"):
        migration.downgrade()

    preflight.assert_called_once_with(connection)
    seed_delete.assert_not_called()


def test_distribution_models_compile_for_mysql_and_dm_compatible_dialect():
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

    mysql_document = str(
        CreateTable(KnowledgeDocument.__table__).compile(dialect=mysql.dialect())
    )
    mysql_file = str(
        CreateTable(KnowledgeFile.__table__).compile(dialect=mysql.dialect())
    )

    dm_dialect = DefaultDialect()
    dm_dialect.name = "dm"
    dm_document = str(
        CreateTable(KnowledgeDocument.__table__).compile(dialect=dm_dialect)
    )
    dm_file = str(
        CreateTable(KnowledgeFile.__table__).compile(dialect=dm_dialect)
    )

    assert "tenant_id INTEGER NOT NULL" in mysql_document
    assert "DEFAULT 1" not in mysql_document.split("tenant_id", 1)[1].split(",", 1)[0]
    assert "allow_download BOOL" in mysql_file
    assert "projection_last_error TEXT" in mysql_file

    assert "tenant_id INTEGER NOT NULL" in dm_document
    assert "allow_download SMALLINT" in dm_file
    assert "projection_last_error TEXT" in dm_file


def _create_approval_seed_schema(connection: sa.Connection) -> None:
    statements = [
        """
        CREATE TABLE approval_scenario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            scenario_code VARCHAR(128) NOT NULL,
            scenario_name VARCHAR(255) NOT NULL,
            display_name VARCHAR(255),
            enabled INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE approval_route_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            scenario_id INTEGER NOT NULL,
            route_name VARCHAR(255) NOT NULL,
            route_type VARCHAR(32) NOT NULL,
            sort_order INTEGER NOT NULL,
            flow_definition_id INTEGER,
            match_config TEXT,
            enabled INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE approval_flow_definition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            scenario_id INTEGER NOT NULL,
            flow_code VARCHAR(128) NOT NULL,
            flow_name VARCHAR(255) NOT NULL,
            is_active INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE approval_flow_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            flow_definition_id INTEGER NOT NULL,
            version_no INTEGER NOT NULL,
            is_active INTEGER NOT NULL,
            definition_snapshot TEXT
        )
        """,
        """
        CREATE TABLE approval_node_definition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER NOT NULL,
            flow_version_id INTEGER NOT NULL,
            node_code VARCHAR(128) NOT NULL,
            node_name VARCHAR(255) NOT NULL,
            node_order INTEGER NOT NULL,
            node_mode VARCHAR(32) NOT NULL,
            approver_config TEXT,
            extra_config TEXT
        )
        """,
    ]
    for statement in statements:
        connection.execute(sa.text(statement))


def test_share_scenario_seed_is_idempotent_and_has_two_explicit_nodes():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_approval_seed_schema(connection)

        migration._seed_share_scenario(connection)
        migration._seed_share_scenario(connection)

        scenario_count = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM approval_scenario "
                "WHERE scenario_code = :scenario_code"
            ),
            {"scenario_code": migration.SHARE_SCENARIO_CODE},
        ).scalar_one()
        nodes = list(
            connection.execute(
                sa.text(
                    "SELECT node_code, node_order, approver_config "
                    "FROM approval_node_definition ORDER BY node_order"
                )
            ).mappings()
        )

    assert scenario_count == 1
    assert [(row["node_code"], row["node_order"]) for row in nodes] == [
        (migration.SHARE_SOURCE_NODE_CODE, 0),
        (migration.SHARE_TARGET_NODE_CODE, 1),
    ]
    assert "knowledge_space_owner" in nodes[0]["approver_config"]
    assert "target_knowledge_space_owner" in nodes[1]["approver_config"]


def test_share_scenario_downgrade_removes_revision_owned_seed_only():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_approval_seed_schema(connection)
        migration._seed_share_scenario(connection)

        migration._delete_share_scenario_seed(connection)

        counts = [
            connection.execute(
                sa.text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()
            for table_name in migration._APPROVAL_TABLES
        ]

    assert counts == [0, 0, 0, 0, 0]


def test_share_scenario_downgrade_preserves_preexisting_complete_seed():
    migration = importlib.import_module(MIGRATION_MODULE)
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        _create_approval_seed_schema(connection)
        migration._seed_share_scenario(connection)
        connection.execute(
            sa.text(
                "UPDATE approval_route_rule SET match_config = '{}'"
            )
        )
        connection.execute(
            sa.text(
                "UPDATE approval_flow_version "
                "SET definition_snapshot = :definition_snapshot"
            ),
            {"definition_snapshot": '{"contract":"preexisting"}'},
        )
        connection.execute(
            sa.text(
                "UPDATE approval_node_definition "
                "SET extra_config = :extra_config"
            ),
            {"extra_config": '{"system_managed":true}'},
        )

        migration._seed_share_scenario(connection)
        migration._delete_share_scenario_seed(connection)

        counts = [
            connection.execute(
                sa.text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()
            for table_name in migration._APPROVAL_TABLES
        ]

    assert counts == [1, 1, 1, 1, 2]
