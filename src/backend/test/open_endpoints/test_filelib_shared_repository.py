from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import DefaultClause, MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.filelib_space_repository_impl import (
    FilelibSpaceRepositoryImpl,
)


@pytest.fixture
async def repository(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    token = current_tenant_id.set(1)
    try:
        metadata = MetaData()
        for model in (Knowledge, KnowledgeFile, KnowledgeDocument, KnowledgeDocumentVersion):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                    column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

        @asynccontextmanager
        async def fresh_session():
            async with AsyncSession(engine) as independent:
                yield independent

        monkeypatch.setattr(
            "bisheng.knowledge.domain.repositories.implementations.filelib_space_repository_impl.get_async_db_session",
            fresh_session,
        )
        async with AsyncSession(engine) as session:
            yield FilelibSpaceRepositoryImpl(session)
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def test_encoding_lookup_preserves_historical_identity_and_excludes_deleted(repository):
    session = repository.session
    for file_id in range(1, 5):
        session.add(
            KnowledgeFile(
                id=file_id,
                knowledge_id=7 if file_id < 4 else 8,
                tenant_id=1,
                file_encoding="CODE",
                file_name="a.pdf",
                file_type=1,
                status=2,
                deleted_at=datetime(2026, 1, 1) if file_id == 3 else None,
            )
        )
    session.add(KnowledgeDocument(id=10, tenant_id=1, knowledge_id=7, primary_version_id=20))
    session.add(
        KnowledgeDocumentVersion(
            id=20, tenant_id=1, document_id=10, knowledge_file_id=1, version_no=1, is_primary=False
        )
    )
    await session.commit()
    assert [f.id for f in await repository.find_by_encoding("CODE", 7)] == [1, 2]
    assert await repository.primary_flags([1, 2]) == {1: False}


async def test_clear_roots_excludes_nested_and_recycled_entries(repository):
    for file_id, path, kind in [(1, "", 0), (2, "/1", 1), (3, "", 1)]:
        repository.session.add(
            KnowledgeFile(id=file_id, knowledge_id=7, tenant_id=1, file_name="a", file_type=kind, file_level_path=path)
        )
    await repository.session.commit()
    assert [f.id for f in await repository.root_entries(7)] == [1, 3]


async def test_abstracts_query_shared_identity_and_actual_target(repository, monkeypatch):
    entry = SimpleNamespace(id=12, knowledge_id=7, tenant_id=1, status=2, projection_status="ready")
    monkeypatch.setattr(repository, "content_refs", AsyncMock(return_value={12: (100, 200, 3)}))
    monkeypatch.setattr(repository, "primary_flags", AsyncMock(return_value={}))
    monkeypatch.setattr(repository, "_route", AsyncMock(return_value=SimpleNamespace(index_name="tenant_shared")))
    client = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "aggregations": {
                    "entries": {
                        "buckets": {
                            "12": {"first": {"hits": {"hits": [{"_source": {"metadata": {"abstract": "摘要"}}}]}}}
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.filelib_space_repository_impl.get_es_connection",
        AsyncMock(return_value=client),
    )
    assert await repository.abstracts([entry]) == {12: "摘要"}
    request = client.search.await_args.kwargs
    assert request["index"] == "tenant_shared"
    filters = request["aggs"]["entries"]["filters"]["filters"]["12"]["bool"]["filter"]
    assert {"term": {"metadata.canonical_document_id": 100}} in filters
    assert {"term": {"metadata.canonical_version_id": 200}} in filters
    assert {"term": {"metadata.content_generation": 3}} in filters
    assert {"term": {"metadata.knowledge_ids": 7}} in filters
    assert "metadata.document_id" not in str(request)


async def test_parse_result_refreshes_writer_generations_and_keeps_lifecycle(repository, monkeypatch):
    from sqlalchemy import update

    session = repository.session
    file = KnowledgeFile(
        id=99,
        tenant_id=1,
        knowledge_id=7,
        file_type=1,
        file_name="data.txt",
        status=1,
        desired_content_generation=1,
        applied_content_generation=1,
    )
    session.add(file)
    await session.commit()
    await session.refresh(file)
    await session.exec(
        update(KnowledgeFile)
        .where(KnowledgeFile.id == 99)
        .values(
            reference_document_id=100,
            entry_type="manager",
            entry_status="active",
            desired_content_generation=3,
            applied_content_generation=3,
            projection_status="ready",
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    hook = "bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook."
    monkeypatch.setattr(hook + "track_fulltext_file_changes", lambda value: None)

    async def commit(*args, **kwargs):
        await session.commit()

    monkeypatch.setattr(hook + "commit_tracked_fulltext_changes", commit)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl.KnowledgeBackgroundRepositoryImpl.request_auto_publish",
        lambda *args: None,
    )
    finalized = await repository.persist_parse_result(99, 2)
    assert finalized.status == 2 and finalized.applied_content_generation == 3
    assert finalized.reference_document_id == 100 and finalized.entry_type == "manager"


async def test_api_factory_wires_shared_lifecycle_and_resolver(repository):
    from bisheng.open_endpoints.api.dependencies import build_filelib_space_query_service

    query = build_filelib_space_query_service(
        request=None, user=SimpleNamespace(user_id=5, tenant_id=1), session=repository.session, storage=object()
    )
    owner = query.space_service
    assert owner.knowledge_space_retirement_service.session is repository.session
    assert owner.document_distribution_service.file_repository is owner.knowledge_file_repo
    assert owner.document_entry_resolver is query.content_service.resolver
    assert owner.document_durable_reference_resolver.entry_resolver is owner.document_entry_resolver
    assert owner.department_file_view_lifecycle_service is not None
