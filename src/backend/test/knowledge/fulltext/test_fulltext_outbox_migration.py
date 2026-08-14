from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from bisheng.core.database.alembic.versions import (
    v2_6_0_f087_knowledge_fulltext_outbox as migration,
)
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import KnowledgeFulltextOutbox


def test_outbox_model_contains_no_content_or_document_payload():
    columns = set(KnowledgeFulltextOutbox.__table__.columns.keys())

    assert {"desired_revision", "applied_revision", "lease_owner", "fanout_cursor"} <= columns
    assert "content" not in columns
    assert "document" not in columns
    assert all(
        foreign_key.target_fullname.split(".")[0] != "knowledgefile"
        for foreign_key in KnowledgeFulltextOutbox.__table__.foreign_keys
    )


def test_outbox_migration_creates_only_the_independent_empty_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()

        inspector = inspect(connection)
        assert inspector.get_table_names() == ["knowledge_fulltext_outbox"]
        assert {item["name"] for item in inspector.get_unique_constraints("knowledge_fulltext_outbox")} == {
            "uk_knowledge_fulltext_outbox_aggregate"
        }
        assert "ix_kfo_dispatch" in {item["name"] for item in inspector.get_indexes("knowledge_fulltext_outbox")}

        migration.downgrade()
        assert "knowledge_fulltext_outbox" not in inspect(connection).get_table_names()
