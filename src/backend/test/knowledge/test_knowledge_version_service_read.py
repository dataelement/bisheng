"""Read-side tests: list_versions / search_documents."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.knowledge_version_read_repository import KnowledgeVersionReadRepository
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeFilePermissionAdapter,
    KnowledgeFileDaoPermissionLoader,
)
from bisheng.knowledge.domain.services.knowledge_version_read_service import KnowledgeVersionReadService
from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
from bisheng.permission.application import business_authorization
from bisheng.permission.application.control_state import PermissionResourceSnapshot
from bisheng.permission.application.identity import reset_current_permission_actor, set_current_permission_actor
from bisheng.permission.domain.services.permission_action_service import PermissionActor


async def _seed(session):
    session.add(Knowledge(id=1, name="space1", type=3, user_id=1))
    session.add(KnowledgeFile(id=100, knowledge_id=1, file_name="a.pdf", file_type=1, status=2, user_name="alice"))
    session.add(KnowledgeFile(id=101, knowledge_id=1, file_name="a_v2.pdf", file_type=1, status=2, user_name="bob"))
    session.add(KnowledgeFile(id=200, knowledge_id=1, file_name="b.pdf", file_type=1, status=2))
    await session.commit()


@pytest.fixture
def read_environment(tenant_context, monkeypatch):
    tenant_context(1)
    token = set_current_permission_actor(PermissionActor(user_id=1, current_tenant_id=1))

    async def snapshots(keys):
        return {key: PermissionResourceSnapshot(*key, 1, "native-read", "CUSTOM", None, None, "READY") for key in keys}

    async def check(actor, targets, action):
        assert actor.user_id == 1 and action == "visible"
        return (True,) * len(targets)

    adapter = F048KnowledgeFilePermissionAdapter(
        loader=KnowledgeFileDaoPermissionLoader(
            SimpleNamespace(get_permission_snapshots=AsyncMock(side_effect=snapshots))
        ),
        permission=SimpleNamespace(),
    )
    monkeypatch.setattr(
        business_authorization,
        "get_f048_runtime",
        AsyncMock(return_value=SimpleNamespace(batch_check_actions=AsyncMock(side_effect=check))),
    )
    try:
        yield adapter
    finally:
        reset_current_permission_actor(token)


def _build_svc(async_db_session, adapter):
    @asynccontextmanager
    async def sessions():
        yield async_db_session

    user = UserPayload(user_id=1, tenant_id=1, user_role=[])
    read_service = KnowledgeVersionReadService(
        MagicMock(),
        user,
        repository=KnowledgeVersionReadRepository(session_factory=sessions),
        permission_adapter=adapter,
    )
    return KnowledgeVersionService(
        request=MagicMock(),
        login_user=user,
        doc_repo=KnowledgeDocumentRepositoryImpl(async_db_session),
        version_repo=KnowledgeDocumentVersionRepositoryImpl(async_db_session),
        knowledge_file_repo=KnowledgeFileRepositoryImpl(async_db_session),
        version_read_service=read_service,
    )


@pytest.mark.asyncio
async def test_list_versions_for_file_returns_chain(async_db_session, read_environment):
    await _seed(async_db_session)
    doc = KnowledgeDocument(knowledge_id=1)
    async_db_session.add(doc)
    await async_db_session.commit()
    await async_db_session.refresh(doc)
    v1 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=100, version_no=1, is_primary=False)
    v2 = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=101, version_no=2, is_primary=True)
    async_db_session.add(v1)
    async_db_session.add(v2)
    await async_db_session.commit()
    await async_db_session.refresh(v2)
    doc.primary_version_id = v2.id
    async_db_session.add(doc)
    await async_db_session.commit()

    svc = _build_svc(async_db_session, read_environment)
    # User clicks "Version history" on the primary version's file (id=101).
    result = await svc.list_versions_for_file(knowledge_file_id=101)
    assert result.document_id == doc.id
    assert result.current_primary_version_no == 2
    assert len(result.versions) == 2
    version_nos = [v.version_no for v in result.versions]
    assert version_nos == [1, 2]
    v2_entry = next(v for v in result.versions if v.version_no == 2)
    assert v2_entry.is_primary is True
    assert v2_entry.original_file_name == "a_v2.pdf"


@pytest.mark.asyncio
async def test_list_versions_raises_for_file_without_chain(async_db_session, read_environment):
    await _seed(async_db_session)
    svc = _build_svc(async_db_session, read_environment)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ctx:
        await svc.list_versions_for_file(knowledge_file_id=999)
    assert ctx.value.status_code == 404


@pytest.mark.asyncio
async def test_search_documents_excludes_current_document(async_db_session, read_environment):
    await _seed(async_db_session)
    doc1 = KnowledgeDocument(knowledge_id=1)
    doc2 = KnowledgeDocument(knowledge_id=1)
    async_db_session.add_all([doc1, doc2])
    await async_db_session.commit()
    await async_db_session.refresh(doc1)
    await async_db_session.refresh(doc2)
    v_doc1 = KnowledgeDocumentVersion(document_id=doc1.id, knowledge_file_id=100, version_no=1, is_primary=True)
    v_doc2 = KnowledgeDocumentVersion(document_id=doc2.id, knowledge_file_id=200, version_no=1, is_primary=True)
    async_db_session.add_all([v_doc1, v_doc2])
    await async_db_session.commit()
    await async_db_session.refresh(v_doc1)
    await async_db_session.refresh(v_doc2)
    doc1.primary_version_id = v_doc1.id
    doc2.primary_version_id = v_doc2.id
    async_db_session.add_all([doc1, doc2])
    await async_db_session.commit()

    svc = _build_svc(async_db_session, read_environment)
    # Searching from file 100 (in doc1): must exclude doc1; "a.pdf" doesn't match doc2 ("b.pdf")
    results = await svc.search_associable_documents(knowledge_id=1, keyword="a", current_file_id=100)
    doc_ids = [r.document_id for r in results]
    assert doc1.id not in doc_ids  # excludes self
    assert results == []
    # Searching "b" should find doc2
    results = await svc.search_associable_documents(knowledge_id=1, keyword="b", current_file_id=100)
    assert [r.document_id for r in results] == [doc2.id]
