"""Tests for the historical data initialization script."""
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)

# Script under test
import scripts.init_knowledge_document_versions as script_mod
from scripts.init_knowledge_document_versions import backfill


# Default = SPACE (3); pass other values to test the skip path.
async def _seed_space(session: AsyncSession, knowledge_id: int, knowledge_type: int = 3) -> None:
    ks = Knowledge(id=knowledge_id, name=f"space{knowledge_id}", type=knowledge_type, user_id=1)
    session.add(ks)
    await session.commit()


async def _seed_file(
    session: AsyncSession, *, file_id: int, knowledge_id: int, status: int = 2, file_type: int = 1,
    file_level_path: str | None = None, level: int = 0,
    object_name: str | None = None, simhash: str | None = None,
) -> None:
    kf = KnowledgeFile(
        id=file_id, knowledge_id=knowledge_id, file_name=f"f{file_id}.pdf",
        file_type=file_type, status=status, file_level_path=file_level_path, level=level,
        object_name=object_name, simhash=simhash,
    )
    session.add(kf)
    await session.commit()


async def _get_file(session: AsyncSession, file_id: int) -> KnowledgeFile:
    result = await session.execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id))
    return result.scalars().first()


@pytest.mark.asyncio
async def test_backfill_creates_document_and_primary_v1_for_parsed_file(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1, status=2)

    report = await backfill(async_db_session)

    assert report.documents_created == 1
    assert report.versions_created == 1

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    ver_repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)

    docs = await doc_repo.find_by_knowledge_id(1)
    assert len(docs) == 1
    assert docs[0].primary_version_id is not None

    versions = await ver_repo.find_by_document_id(docs[0].id)
    assert len(versions) == 1
    assert versions[0].version_no == 1
    assert versions[0].is_primary is True
    assert versions[0].knowledge_file_id == 100


@pytest.mark.asyncio
async def test_backfill_skips_qa_knowledge_base(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1, knowledge_type=1)  # QA
    await _seed_file(async_db_session, file_id=100, knowledge_id=1)

    report = await backfill(async_db_session)

    assert report.documents_created == 0
    assert report.skipped_non_space == 1


@pytest.mark.asyncio
async def test_backfill_skips_normal_and_private_knowledge_bases(async_db_session: AsyncSession):
    # 0=NORMAL, 2=PRIVATE — both are legacy 知识库, not 知识空间
    await _seed_space(async_db_session, 1, knowledge_type=0)
    await _seed_space(async_db_session, 2, knowledge_type=2)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1)
    await _seed_file(async_db_session, file_id=200, knowledge_id=2)

    report = await backfill(async_db_session)

    assert report.documents_created == 0
    assert report.skipped_non_space == 2


@pytest.mark.asyncio
async def test_backfill_skips_folders(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1, file_type=0)  # DIR

    report = await backfill(async_db_session)

    assert report.documents_created == 0
    assert report.skipped_folder == 1


@pytest.mark.asyncio
async def test_backfill_failed_parse_v1_still_primary(async_db_session: AsyncSession):
    """Per product decision: historical V1 is always primary, regardless of parse status.
    Failed files have no indexed chunks, so they naturally don't appear in retrieval;
    the UI gates version management on knowledgefile.status."""
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1, status=3)  # FAILED

    report = await backfill(async_db_session)
    assert report.versions_created == 1

    ver_repo = KnowledgeDocumentVersionRepositoryImpl(async_db_session)
    v = await ver_repo.find_by_knowledge_file_id(100)
    assert v is not None
    assert v.is_primary is True  # historical V1 is always primary

    # And the document's primary_version_id points at this V1.
    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    docs = await doc_repo.find_by_knowledge_id(1)
    assert docs[0].primary_version_id == v.id


@pytest.mark.asyncio
async def test_backfill_is_idempotent(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1)

    report1 = await backfill(async_db_session)
    report2 = await backfill(async_db_session)

    assert report1.documents_created == 1
    assert report2.documents_created == 0  # nothing left to do
    assert report2.skipped_already_done == 1


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_write(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1)

    report = await backfill(async_db_session, dry_run=True)
    assert report.documents_created == 1  # report still counts what would be done

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    docs = await doc_repo.find_by_knowledge_id(1)
    assert docs == []


@pytest.mark.asyncio
async def test_backfill_respects_folder_path(async_db_session: AsyncSession):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1,
        file_level_path="/10/20", level=2,
    )

    await backfill(async_db_session)

    doc_repo = KnowledgeDocumentRepositoryImpl(async_db_session)
    docs = await doc_repo.find_by_knowledge_id(1)
    assert docs[0].file_level_path == "/10/20"
    assert docs[0].level == 2


# ── SimHash backfill ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_computes_simhash_for_parsed_file_without_one(
    async_db_session: AsyncSession, monkeypatch,
):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1, status=2,
        object_name="knowledge/1/100.pdf", simhash=None,
    )
    fake = AsyncMock(return_value="abcdef0123456789")
    monkeypatch.setattr(script_mod, "_extract_file_simhash", fake)

    report = await backfill(async_db_session)

    assert report.simhash_computed == 1
    fake.assert_awaited_once()
    kf = await _get_file(async_db_session, 100)
    assert kf.simhash == "abcdef0123456789"


@pytest.mark.asyncio
async def test_backfill_skips_simhash_when_already_present(
    async_db_session: AsyncSession, monkeypatch,
):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1, status=2,
        object_name="knowledge/1/100.pdf", simhash="1111111111111111",
    )
    fake = AsyncMock(return_value="abcdef0123456789")
    monkeypatch.setattr(script_mod, "_extract_file_simhash", fake)

    report = await backfill(async_db_session)

    assert report.simhash_computed == 0
    assert report.simhash_skipped_has_value == 1
    fake.assert_not_awaited()
    kf = await _get_file(async_db_session, 100)
    assert kf.simhash == "1111111111111111"  # untouched


@pytest.mark.asyncio
async def test_backfill_skips_simhash_for_non_success_file(
    async_db_session: AsyncSession, monkeypatch,
):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1, status=3,  # FAILED
        object_name="knowledge/1/100.pdf", simhash=None,
    )
    fake = AsyncMock(return_value="abcdef0123456789")
    monkeypatch.setattr(script_mod, "_extract_file_simhash", fake)

    report = await backfill(async_db_session)

    assert report.simhash_computed == 0
    assert report.simhash_skipped_not_success == 1
    fake.assert_not_awaited()
    kf = await _get_file(async_db_session, 100)
    assert kf.simhash is None


@pytest.mark.asyncio
async def test_backfill_skip_simhash_flag_disables_computation(
    async_db_session: AsyncSession, monkeypatch,
):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1, status=2,
        object_name="knowledge/1/100.pdf", simhash=None,
    )
    fake = AsyncMock(return_value="abcdef0123456789")
    monkeypatch.setattr(script_mod, "_extract_file_simhash", fake)

    report = await backfill(async_db_session, compute_simhash=False)

    assert report.simhash_computed == 0
    fake.assert_not_awaited()
    kf = await _get_file(async_db_session, 100)
    assert kf.simhash is None


@pytest.mark.asyncio
async def test_backfill_dry_run_counts_but_does_not_compute_simhash(
    async_db_session: AsyncSession, monkeypatch,
):
    await _seed_space(async_db_session, 1)
    await _seed_file(
        async_db_session, file_id=100, knowledge_id=1, status=2,
        object_name="knowledge/1/100.pdf", simhash=None,
    )
    fake = AsyncMock(return_value="abcdef0123456789")
    monkeypatch.setattr(script_mod, "_extract_file_simhash", fake)

    report = await backfill(async_db_session, dry_run=True)

    assert report.simhash_computed == 1  # would compute one
    fake.assert_not_awaited()  # but doesn't read files in dry-run
    kf = await _get_file(async_db_session, 100)
    assert kf.simhash is None
