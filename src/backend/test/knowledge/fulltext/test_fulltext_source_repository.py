from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import text

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database.tenant_filter import register_tenant_filter_events
from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
    KnowledgeSpaceSharedStorageRouting,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextFileSnapshot,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
)


def test_category_names_are_resolved_only_from_authoritative_config():
    document_types = [
        SimpleNamespace(
            code="POL",
            label="政策制度",
            children=[SimpleNamespace(code="POL-01", label="管理制度")],
        )
    ]

    assert KnowledgeFulltextSourceRepositoryImpl.resolve_category_names(
        document_types,
        document_category_code="pol",
        file_subcategory_code="pol-01",
    ) == ("政策制度", "管理制度")


def test_missing_authoritative_category_name_stays_null():
    assert KnowledgeFulltextSourceRepositoryImpl.resolve_category_names(
        [],
        document_category_code="UNKNOWN",
        file_subcategory_code="UNKNOWN-01",
    ) == (None, None)


async def test_legacy_success_file_snapshot_is_not_hidden_by_default_tenant_filter(
    async_db_session,
    monkeypatch,
):
    register_tenant_filter_events()
    token = set_current_tenant_id(1)
    try:
        await async_db_session.exec(
            text(
                """
                ALTER TABLE knowledge_space_scope
                ADD COLUMN portal_discovery_enabled INTEGER NOT NULL DEFAULT 0
                """
            )
        )
        await async_db_session.exec(
            text(
                """
                INSERT INTO knowledge (id, tenant_id, name, index_name, auth_type)
                VALUES (198, 1, '测试知识库', 'col_test', 'PUBLIC'),
                       (199, 1, '来源知识库', 'col_source', 'PUBLIC')
                """
            )
        )
        await async_db_session.exec(
            text(
                """
                INSERT INTO knowledgefile (
                    id, tenant_id, user_id, knowledge_id, file_name, file_type,
                    file_source, status, reference_document_id, projection_status,
                    md5, object_name, split_rule, desired_content_generation,
                    original_knowledge_id
                ) VALUES (1829, 1, 1, 198, 'knowledge-space-api-usage.md', 1,
                          'upload', 2, NULL, 'pending', 'source-md5',
                          'knowledge/1829.md', '{"chunk_size": 500}', 3, 199)
                """
            )
        )
        await async_db_session.commit()

        repository = KnowledgeFulltextSourceRepositoryImpl(async_db_session)
        monkeypatch.setattr(repository, "_load_tags", AsyncMock(return_value=[]))
        monkeypatch.setattr(repository, "_load_user_name", AsyncMock(return_value=None))
        monkeypatch.setattr(repository, "_load_category_names", AsyncMock(return_value=(None, None)))
        monkeypatch.setattr(repository, "_load_folder_path", AsyncMock(return_value=None))

        snapshot = await repository.get_current_snapshot(1829)

        assert snapshot is not None
        assert snapshot.file_id == 1829
        assert snapshot.logical_document_id is None
        assert snapshot.original_knowledge_id == 199
        assert snapshot.original_knowledge_name == "来源知识库"
        assert KnowledgeFulltextDocumentService.decide(snapshot).value == "upsert"
        repair_source = await repository.get_auto_repair_source(1829)
        assert repair_source is not None
        assert repair_source.md5 == "source-md5"
        assert repair_source.object_name == "knowledge/1829.md"
        assert repair_source.split_rule == '{"chunk_size": 500}'
        assert repair_source.desired_content_generation == 3
    finally:
        current_tenant_id.reset(token)


async def test_historical_physical_version_snapshot_is_deleted(async_db_session, monkeypatch):
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledge (id, tenant_id, name, index_name, auth_type)
            VALUES (198, 1, '测试知识库', 'col_test', 'PUBLIC')
            """
        )
    )
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledgefile (
                id, tenant_id, user_id, knowledge_id, file_name, file_type,
                file_source, status, reference_document_id, projection_status
            ) VALUES (1829, 1, 1, 198, 'history.md', 1, 'upload', 2, NULL, 'ready')
            """
        )
    )
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledge_document (
                id, tenant_id, knowledge_id, primary_version_id, lifecycle_status
            ) VALUES (500, 1, 198, 501, 'active')
            """
        )
    )
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledge_document_version (
                id, document_id, knowledge_file_id, version_no, is_primary
            ) VALUES (501, 500, 1830, 2, 1),
                     (502, 500, 1829, 1, 0)
            """
        )
    )
    await async_db_session.commit()

    repository = KnowledgeFulltextSourceRepositoryImpl(async_db_session)
    monkeypatch.setattr(repository, "_load_tags", AsyncMock(return_value=[]))
    monkeypatch.setattr(repository, "_load_user_name", AsyncMock(return_value=None))
    monkeypatch.setattr(repository, "_load_category_names", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(repository, "_load_folder_path", AsyncMock(return_value=None))

    snapshot = await repository.get_current_snapshot(1829)

    assert snapshot is not None
    assert snapshot.document_version_id == 502
    assert snapshot.is_primary_version is False
    assert KnowledgeFulltextDocumentService.decide(snapshot).value == "delete"


async def test_backfill_file_id_page_is_global_stable_and_scope_bounded(async_db_session):
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledge (id, tenant_id, name, index_name, auth_type)
            VALUES (198, 1, '知识库一', 'col_198', 'PUBLIC'),
                   (199, 1, '知识库二', 'col_199', 'PUBLIC')
            """
        )
    )
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledgefile (
                id, tenant_id, user_id, knowledge_id, file_name, file_type,
                file_source, status, reference_document_id, projection_status
            ) VALUES (10, 1, 1, 198, 'a.md', 1, 'upload', 2, NULL, 'pending'),
                     (11, 1, 1, 199, 'b.md', 1, 'upload', 2, NULL, 'pending'),
                     (12, 1, 1, 198, 'c.md', 1, 'upload', 2, NULL, 'pending')
            """
        )
    )
    await async_db_session.commit()
    repository = KnowledgeFulltextSourceRepositoryImpl(async_db_session)

    assert await repository.list_backfill_file_ids(
        after_file_id=10,
        limit=2,
        knowledge_id=None,
        file_id=None,
    ) == [11, 12]
    assert await repository.list_backfill_file_ids(
        after_file_id=0,
        limit=10,
        knowledge_id=198,
        file_id=None,
    ) == [10, 12]
    assert await repository.list_backfill_file_ids(
        after_file_id=0,
        limit=10,
        knowledge_id=None,
        file_id=11,
    ) == [11]


async def test_shared_space_chunk_source_uses_current_canonical_generation(
    async_db_session,
    monkeypatch,
):
    connection = await async_db_session.connection()
    await connection.run_sync(
        KnowledgeSpaceSharedStorageRouting.__table__.create,
        checkfirst=True,
    )
    await async_db_session.exec(
        text(
            """
            INSERT INTO knowledge_space_shared_storage_routing (
                tenant_id, shared_enabled, routing_version, write_frozen,
                index_name
            ) VALUES (1, 1, 5, 0, 'idx_space_shared_1')
            """
        )
    )
    await async_db_session.commit()
    repository = KnowledgeFulltextSourceRepositoryImpl(async_db_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations."
        "knowledge_fulltext_source_repository_impl.get_shared_storage_conf",
        lambda: SimpleNamespace(enabled=True, es_routing_enabled=False),
    )

    snapshot = KnowledgeFulltextFileSnapshot(
        file_id=1829,
        tenant_id=1,
        knowledge_id=198,
        knowledge_type=3,
        file_type="FILE",
        status="2",
        logical_document_id=500,
        document_version_id=501,
        content_file_id=1800,
        content_generation=3,
        file_name="published.md",
        file_source="publish",
        knowledge_name="共享空间",
        created_at=datetime(2026, 8, 28),
        updated_at=datetime(2026, 8, 28),
    )
    source = await repository.get_chunk_source(snapshot)

    assert source is not None
    assert source.shared is True
    assert source.index_name == "idx_space_shared_1"
    assert source.file_id == 1829
    assert source.knowledge_id == 198
    assert source.canonical_document_id == 500
    assert source.canonical_version_id == 501
    assert source.content_generation == 3
