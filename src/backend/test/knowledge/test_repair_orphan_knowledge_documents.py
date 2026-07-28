"""Regression tests for the F071 orphan document repair script."""

import pytest
from sqlalchemy import Connection, create_engine, text

from scripts.repair_orphan_knowledge_documents import (
    RepairBlockedError,
    repair_orphan_documents,
    scan_orphan_documents,
)


def _connection() -> Connection:
    engine = create_engine("sqlite://")
    connection = engine.connect()
    for ddl in (
        """
        CREATE TABLE knowledge_document (
            id INTEGER PRIMARY KEY,
            knowledge_id INTEGER NOT NULL,
            primary_version_id INTEGER
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
            knowledge_id INTEGER NOT NULL,
            reference_document_id INTEGER
        )
        """,
        """
        CREATE TABLE knowledge_file_similarity_candidate (
            id INTEGER PRIMARY KEY,
            candidate_document_id INTEGER NOT NULL
        )
        """,
    ):
        connection.execute(text(ddl))
    return connection


def test_scan_classifies_safe_and_blocked_orphans():
    connection = _connection()
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, knowledge_id)
            VALUES (1, 10), (2, 10), (3, 10), (4, 10)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(id, knowledge_id, reference_document_id)
            VALUES (20, 10, NULL), (21, 10, 4)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document_version(
                id, document_id, knowledge_file_id
            )
            VALUES (30, 2, 20), (31, 3, 999)
            """
        )
    )

    report = scan_orphan_documents(connection)
    candidates = {item.document_id: item for item in report.candidates}

    assert set(candidates) == {1, 3, 4}
    assert candidates[1].reason == "no_versions"
    assert candidates[1].safe_to_delete is True
    assert candidates[3].reason == "all_versions_reference_missing_files"
    assert candidates[3].safe_to_delete is True
    assert candidates[4].reason == "referenced_by_knowledgefile"
    assert candidates[4].safe_to_delete is False


def test_apply_removes_only_safe_database_orphans():
    connection = _connection()
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, knowledge_id)
            VALUES (1, 10), (2, 10), (3, 10)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(id, knowledge_id, reference_document_id)
            VALUES (20, 10, NULL)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document_version(
                id, document_id, knowledge_file_id
            )
            VALUES (30, 2, 20), (31, 3, 999)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledge_file_similarity_candidate(
                id, candidate_document_id
            )
            VALUES (40, 1), (41, 2), (42, 3)
            """
        )
    )

    result = repair_orphan_documents(
        connection,
        document_ids=(1, 3),
    )

    assert result.deleted_documents == 2
    assert result.deleted_versions == 1
    assert result.deleted_similarity_candidates == 2
    assert connection.execute(text("SELECT id FROM knowledge_document ORDER BY id")).scalars().all() == [2]
    assert connection.execute(text("SELECT id FROM knowledgefile ORDER BY id")).scalars().all() == [20]
    assert connection.execute(
        text("SELECT id FROM knowledge_file_similarity_candidate ORDER BY id")
    ).scalars().all() == [41]


def test_apply_refuses_referenced_orphan_without_partial_delete():
    connection = _connection()
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, knowledge_id)
            VALUES (1, 10), (4, 10)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO knowledgefile(id, knowledge_id, reference_document_id)
            VALUES (21, 10, 4)
            """
        )
    )

    with pytest.raises(
        RepairBlockedError,
        match="still referenced",
    ):
        repair_orphan_documents(
            connection,
            document_ids=(1, 4),
        )

    assert connection.execute(text("SELECT id FROM knowledge_document ORDER BY id")).scalars().all() == [1, 4]


def test_apply_is_idempotent_after_success():
    connection = _connection()
    connection.execute(
        text(
            """
            INSERT INTO knowledge_document(id, knowledge_id)
            VALUES (1, 10)
            """
        )
    )

    first = repair_orphan_documents(connection, document_ids=(1,))
    second = repair_orphan_documents(connection, document_ids=(1,))

    assert first.deleted_documents == 1
    assert second.deleted_documents == 0
    assert second.scan.total_candidates == 0
