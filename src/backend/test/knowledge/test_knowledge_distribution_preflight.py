"""Read-only release preflight for F059 canonical distribution."""

import json

from sqlalchemy import create_engine, text

from scripts.knowledge_document_distribution_preflight import run_preflight


def _connection():
    engine = create_engine("sqlite://")
    connection = engine.connect()
    for ddl in (
        """
        CREATE TABLE knowledge (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_document (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            knowledge_id INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_document_version (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL,
            knowledge_file_id INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE knowledgefile (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER,
            knowledge_id INTEGER NOT NULL,
            reference_document_id INTEGER,
            entry_type VARCHAR(24),
            entry_status VARCHAR(16),
            object_name TEXT,
            preview_file_object_name TEXT,
            bbox_object_name TEXT,
            thumbnails TEXT,
            file_size INTEGER DEFAULT 0,
            md5 VARCHAR(64),
            user_metadata JSON
        )
        """,
    ):
        connection.execute(text(ddl))
    return connection


def test_preflight_passes_consistent_canonical_state():
    connection = _connection()
    connection.execute(
        text("INSERT INTO knowledge(id, tenant_id) VALUES (10, 7)")
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, tenant_id, knowledge_id)
            VALUES (91, 7, 10)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(
                id, tenant_id, knowledge_id, reference_document_id,
                entry_type, entry_status, object_name, file_size
            )
            VALUES (
                100, 7, 10, 91, 'manager', 'active',
                'original/100.pdf', 200
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document_version(
                id, document_id, knowledge_file_id
            )
            VALUES (501, 91, 100)
            """
        )
    )

    report = run_preflight(connection)

    assert report["status"] == "pass"
    assert report["issues"] == []
    assert (
        report["checks"]["space_independent_object_keys"]["status"]
        == "pass"
    )


def test_preflight_blocks_duplicate_legacy_and_space_dependent_state():
    connection = _connection()
    connection.execute(
        text(
            "INSERT INTO knowledge(id, tenant_id) VALUES (10, 7), (20, 8)"
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, tenant_id, knowledge_id)
            VALUES (91, 7, 10), (92, 8, 20)
            """
        )
    )
    legacy_metadata = json.dumps(
        {
            "shougang_portal_publish": {
                "approval_instance_id": 3
            },
            "image": "knowledge/images/10/100/a.png",
        }
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(
                id, tenant_id, knowledge_id, reference_document_id,
                entry_type, entry_status, object_name, file_size,
                user_metadata
            )
            VALUES
                (100, 7, 10, 91, 'share', 'active', NULL, 0, :metadata),
                (101, 8, 20, NULL, NULL, NULL, 'original/101.pdf', 10, NULL)
            """
        ),
        {"metadata": legacy_metadata},
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document_version(
                id, document_id, knowledge_file_id
            )
            VALUES (501, 91, 100), (502, 92, 100)
            """
        )
    )

    report = run_preflight(connection)
    codes = {item["code"] for item in report["issues"]}

    assert report["status"] == "block"
    assert "duplicate_version_file_relation" in codes
    assert "document_tenant_not_deterministic" in codes
    assert "legacy_copy_publish_data" in codes
    assert "space_dependent_object_key" in codes
    assert "invalid_active_manager_count" in codes


def test_preflight_blocks_file_space_tenant_mismatch_before_migration():
    connection = _connection()
    connection.execute(
        text("INSERT INTO knowledge(id, tenant_id) VALUES (10, 8)")
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, tenant_id, knowledge_id)
            VALUES (91, NULL, 10)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(
                id, tenant_id, knowledge_id, object_name, file_size
            )
            VALUES (100, 7, 10, 'original/100.pdf', 200)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document_version(
                id, document_id, knowledge_file_id
            )
            VALUES (501, 91, 100)
            """
        )
    )

    report = run_preflight(connection)

    assert report["status"] == "block"
    assert {
        item["code"] for item in report["issues"]
    } >= {"document_tenant_not_deterministic"}
