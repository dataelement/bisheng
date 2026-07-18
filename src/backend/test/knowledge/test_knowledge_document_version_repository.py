"""Tests for KnowledgeDocumentVersionRepositoryImpl."""
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)


@pytest.mark.asyncio
async def test_save_and_query(async_db_session: AsyncSession):
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    v = KnowledgeDocumentVersion(
        document_id=1, knowledge_file_id=100, version_no=1, is_primary=True
    )
    saved = await repo.save(v)
    assert saved.id is not None
    assert saved.is_primary is True


@pytest.mark.asyncio
async def test_find_by_document_id(async_db_session: AsyncSession):
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=100, version_no=1, is_primary=True))
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=101, version_no=2, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=2, knowledge_file_id=200, version_no=1, is_primary=True))

    versions = await repo.find_by_document_id(1)
    assert len(versions) == 2
    assert [v.version_no for v in versions] == [1, 2]  # ascending order locked in


@pytest.mark.asyncio
async def test_find_primary(async_db_session: AsyncSession):
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=100, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=101, version_no=2, is_primary=True))

    primary = await repo.find_primary(1)
    assert primary is not None
    assert primary.knowledge_file_id == 101


@pytest.mark.asyncio
async def test_find_by_knowledge_file_id(async_db_session: AsyncSession):
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=500, version_no=1, is_primary=True))

    v = await repo.find_by_knowledge_file_id(500)
    assert v is not None
    assert v.document_id == 1


@pytest.mark.asyncio
async def test_next_version_no_for_document(async_db_session: AsyncSession):
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    assert await repo.next_version_no(document_id=1) == 1  # empty -> V1

    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=10, version_no=1, is_primary=True))
    assert await repo.next_version_no(document_id=1) == 2

    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=11, version_no=2, is_primary=False))
    assert await repo.next_version_no(document_id=1) == 3


@pytest.mark.asyncio
async def test_non_primary_file_ids_in_space(async_db_session: AsyncSession):
    """The retrieval filter helper: file_ids that should be excluded from RAG."""
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    # doc 1 in space — has main (V2) + history (V1)
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=100, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=1, knowledge_file_id=101, version_no=2, is_primary=True))
    # doc 2 in space — single version (main)
    await repo.save(KnowledgeDocumentVersion(document_id=2, knowledge_file_id=200, version_no=1, is_primary=True))

    excluded = await repo.find_non_primary_file_ids([1, 2])
    assert set(excluded) == {100}

    # document_ids=None -> global: returns all non-primary file_ids
    all_excluded = await repo.find_non_primary_file_ids(None)
    assert set(all_excluded) == {100}


# ---------------------------------------------------------------------------
# Tests for find_non_primary_file_ids_by_knowledge_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_non_primary_by_knowledge_ids_empty_input(async_db_session: AsyncSession):
    """Empty knowledge_ids -> [] with no DB query performed."""
    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    result = await repo.find_non_primary_file_ids_by_knowledge_ids([])
    assert result == []


@pytest.mark.asyncio
async def test_find_non_primary_by_knowledge_ids_no_versions(async_db_session: AsyncSession):
    """A knowledge space with a document but no version rows -> []."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    await doc_repo.save(KnowledgeDocument(knowledge_id=10, level=0))

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    result = await repo.find_non_primary_file_ids_by_knowledge_ids([10])
    assert result == []


@pytest.mark.asyncio
async def test_find_non_primary_by_knowledge_ids_single_space(async_db_session: AsyncSession):
    """1 primary + 2 non-primary versions in one space -> returns the 2 non-primary file ids."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    doc = await doc_repo.save(KnowledgeDocument(knowledge_id=20, level=0))
    doc_id = doc.id

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    # V1 and V2 are non-primary; V3 is primary
    await repo.save(KnowledgeDocumentVersion(document_id=doc_id, knowledge_file_id=301, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_id, knowledge_file_id=302, version_no=2, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_id, knowledge_file_id=303, version_no=3, is_primary=True))

    result = await repo.find_non_primary_file_ids_by_knowledge_ids([20])
    assert set(result) == {301, 302}


@pytest.mark.asyncio
async def test_find_non_primary_by_knowledge_ids_multiple_spaces(async_db_session: AsyncSession):
    """Non-primary file ids are aggregated across multiple knowledge spaces."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    doc_a = await doc_repo.save(KnowledgeDocument(knowledge_id=30, level=0))
    doc_b = await doc_repo.save(KnowledgeDocument(knowledge_id=31, level=0))

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    # Space 30: one non-primary + one primary
    await repo.save(KnowledgeDocumentVersion(document_id=doc_a.id, knowledge_file_id=401, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_a.id, knowledge_file_id=402, version_no=2, is_primary=True))
    # Space 31: two non-primary + one primary
    await repo.save(KnowledgeDocumentVersion(document_id=doc_b.id, knowledge_file_id=501, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_b.id, knowledge_file_id=502, version_no=2, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_b.id, knowledge_file_id=503, version_no=3, is_primary=True))

    result = await repo.find_non_primary_file_ids_by_knowledge_ids([30, 31])
    assert set(result) == {401, 501, 502}


@pytest.mark.asyncio
async def test_find_non_primary_by_knowledge_ids_isolation(async_db_session: AsyncSession):
    """Non-primary rows in a different knowledge space are NOT included."""
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    # Target space
    doc_target = await doc_repo.save(KnowledgeDocument(knowledge_id=40, level=0))
    # Other space — its non-primary rows must NOT appear in the result
    doc_other = await doc_repo.save(KnowledgeDocument(knowledge_id=99, level=0))

    repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    await repo.save(KnowledgeDocumentVersion(document_id=doc_target.id, knowledge_file_id=601, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_target.id, knowledge_file_id=602, version_no=2, is_primary=True))
    # Other space: non-primary row that should be excluded from the result
    await repo.save(KnowledgeDocumentVersion(document_id=doc_other.id, knowledge_file_id=701, version_no=1, is_primary=False))
    await repo.save(KnowledgeDocumentVersion(document_id=doc_other.id, knowledge_file_id=702, version_no=2, is_primary=True))

    result = await repo.find_non_primary_file_ids_by_knowledge_ids([40])
    assert set(result) == {601}
    assert 701 not in result
