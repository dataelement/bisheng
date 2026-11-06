"""Preserved ES retry sources cannot bypass current SQL retrieval status."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.services import knowledge_file_visibility_service as module
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
from bisheng.workstation.domain.services.workstation_service import WorkStationService


@pytest.fixture
def current_tenant(tenant_context):
    tenant_context(101)


@pytest.fixture
async def visibility(current_tenant, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn, tables=[KnowledgeFile.__table__, KnowledgeDocument.__table__, KnowledgeDocumentVersion.__table__]
            )
        )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    statuses = {1: 2, 2: 3, 3: 1, 4: 4, 5: 5, 6: 6, 7: 7, 8: 2, 9: 2}
    async with sessions() as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=ident,
                    tenant_id=101,
                    knowledge_id=10,
                    user_id=7,
                    file_name=f"version-{ident}",
                    file_type=1,
                    status=status,
                )
                for ident, status in statuses.items()
            ]
        )
        session.add(
            KnowledgeFile(id=30, tenant_id=101, knowledge_id=20, user_id=7, file_name="other", file_type=1, status=2)
        )
        session.add(KnowledgeDocument(id=100, knowledge_id=10, primary_version_id=2))
        session.add_all(
            [
                KnowledgeDocumentVersion(id=1, document_id=100, knowledge_file_id=9, version_no=1, is_primary=False),
                KnowledgeDocumentVersion(id=2, document_id=100, knowledge_file_id=1, version_no=2, is_primary=True),
            ]
        )
        await session.commit()
    monkeypatch.setattr(module, "get_async_db_session", sessions)
    user = SimpleNamespace(user_id=7, tenant_id=101)
    service = KnowledgeFileVisibilityService(None, user)
    facts = SimpleNamespace(granted=set(range(1, 10)) - {8})

    async def visible(space_id, ids):
        assert space_id == 10
        return set(ids) & facts.granted

    service.post_filter_visible_files = AsyncMock(side_effect=visible)
    service._batch_visible_file_ids = AsyncMock(side_effect=visible)
    service._config = lambda: SimpleNamespace(index_filter_threshold=100)
    try:
        yield SimpleNamespace(service=service, sessions=sessions, facts=facts, user=user)
    finally:
        await engine.dispose()


async def test_sql_primary_candidates_include_only_success_without_deleting_failed_source(visibility):
    service = visibility.service
    assert await service._list_primary_file_ids_in_space(10) == {1, 8}
    async with visibility.sessions() as session:
        failed = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == 2))).one()
        history = await KnowledgeDocumentVersionRepositoryImpl(session).find_non_primary_file_ids_by_knowledge_ids([10])
    assert failed.file_name == "version-2" and failed.status == KnowledgeFileStatus.FAILED.value
    assert history == [9]


async def test_preserved_es_hits_are_cut_by_sql_status_permission_and_primary_version(visibility):
    hits = [
        Document(page_content=f"retained source {ident}", metadata={"document_id": ident}) for ident in range(1, 10)
    ]
    permitted = await visibility.service.post_filter_retrievable_files(
        10, [hit.metadata["document_id"] for hit in hits]
    )
    assert permitted == {1}
    assert len(hits) == 9 and hits[1].page_content == "retained source 2"
    visibility.service.post_filter_visible_files.assert_awaited_once()


async def test_index_prefilter_does_not_pass_failed_or_ungranted_successful_files(visibility):
    result = await visibility.service.build_index_prefilter(10, None)
    assert result.strategy == "in" and result.milvus_expr == "document_id in [1]"
    assert result.es_filter == [{"terms": {"metadata.document_id": [1]}}]


async def test_explicit_folder_tag_scope_cannot_reintroduce_a_failed_file(visibility):
    result = await visibility.service.build_index_prefilter(10, [2, 8])
    assert result.is_empty


async def test_status_is_rechecked_between_rounds_instead_of_cached_from_prefilter(visibility):
    async with visibility.sessions() as session:
        await session.exec(
            sa.update(KnowledgeFile).where(KnowledgeFile.id == 1, KnowledgeFile.tenant_id == 101).values(status=3)
        )
        await session.exec(
            sa.update(KnowledgeFile).where(KnowledgeFile.id == 2, KnowledgeFile.tenant_id == 101).values(status=2)
        )
        await session.commit()
    assert await visibility.service.post_filter_retrievable_files(10, range(1, 10)) == {2}


async def test_all_failed_or_processing_hits_leave_no_retrievable_result(visibility):
    assert await visibility.service.post_filter_retrievable_files(10, range(2, 8)) == set()


async def test_visibility_for_explicit_history_delivery_is_not_changed_by_retrieval_filter(visibility):
    assert await visibility.service.post_filter_visible_files(10, [2, 3, 9]) == {2, 3, 9}
    assert await visibility.service.post_filter_retrievable_files(10, [2, 3, 9]) == set()


async def test_qa_organization_bucket_retains_its_original_postfilter_path(visibility):
    docs = [Document(page_content="QA answer", metadata={"document_id": 2})]
    result = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=visibility.user,
        kb_id=10,
        docs=docs,
        is_space_bucket=False,
    )
    assert result is docs
    visibility.service.post_filter_visible_files.assert_not_awaited()
