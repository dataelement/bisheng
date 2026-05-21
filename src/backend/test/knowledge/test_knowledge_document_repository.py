"""Tests for KnowledgeDocumentRepositoryImpl."""
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)


@pytest.mark.asyncio
async def test_save_and_find_by_id(async_db_session: AsyncSession):
    repo: KnowledgeDocumentRepository = KnowledgeDocumentRepositoryImpl(async_db_session)
    doc = KnowledgeDocument(knowledge_id=1, file_level_path="/10")
    saved = await repo.save(doc)
    assert saved.id is not None

    fetched = await repo.find_by_id(saved.id)
    assert fetched is not None
    assert fetched.knowledge_id == 1
    assert fetched.file_level_path == "/10"


@pytest.mark.asyncio
async def test_find_by_knowledge_id(async_db_session: AsyncSession):
    repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocument(knowledge_id=1, file_level_path="/a"))
    await repo.save(KnowledgeDocument(knowledge_id=1, file_level_path="/b"))
    await repo.save(KnowledgeDocument(knowledge_id=2, file_level_path="/a"))

    docs = await repo.find_by_knowledge_id(1)
    assert len(docs) == 2
    assert {d.knowledge_id for d in docs} == {1}


@pytest.mark.asyncio
async def test_find_in_folder(async_db_session: AsyncSession):
    repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocument(knowledge_id=1, file_level_path="/folderA"))
    await repo.save(KnowledgeDocument(knowledge_id=1, file_level_path="/folderA"))
    await repo.save(KnowledgeDocument(knowledge_id=1, file_level_path="/folderB"))

    in_a = await repo.find_in_folder(knowledge_id=1, file_level_path="/folderA")
    assert len(in_a) == 2

    in_root = await repo.find_in_folder(knowledge_id=1, file_level_path=None)
    assert in_root == []


@pytest.mark.asyncio
async def test_update_primary_version_id(async_db_session: AsyncSession):
    repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    saved = await repo.save(KnowledgeDocument(knowledge_id=1))
    await repo.update_primary_version_id(saved.id, primary_version_id=99)

    fetched = await repo.find_by_id(saved.id)
    assert fetched.primary_version_id == 99


@pytest.mark.asyncio
async def test_dependencies_factory_returns_repo(async_db_session: AsyncSession):
    from bisheng.knowledge.api.dependencies import (
        get_knowledge_document_repository,
        get_knowledge_document_version_repository,
    )

    doc_repo = await get_knowledge_document_repository(async_db_session)
    ver_repo = await get_knowledge_document_version_repository(async_db_session)

    assert isinstance(doc_repo, KnowledgeDocumentRepositoryImpl)
    assert isinstance(ver_repo, KnowledgeDocumentVersionRepositoryImpl)
