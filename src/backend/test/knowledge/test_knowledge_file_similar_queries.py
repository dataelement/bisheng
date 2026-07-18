"""Tests for new similar-status / main-version DAO + repo queries."""
import pytest

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)


async def _seed_space(session, sid=1):
    session.add(Knowledge(id=sid, name=f"s{sid}", type=3, user_id=1))
    await session.commit()


async def _seed_file(session, fid, knowledge_id=1, similar_status=0, status=2, simhash=None):
    session.add(KnowledgeFile(
        id=fid, knowledge_id=knowledge_id, file_name=f"f{fid}.pdf",
        file_type=1, status=status, similar_status=similar_status,
        simhash=simhash,
    ))
    await session.commit()


async def _seed_doc_v1(session, fid, knowledge_id=1, is_primary=True):
    doc = KnowledgeDocument(knowledge_id=knowledge_id)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    v = KnowledgeDocumentVersion(
        document_id=doc.id, knowledge_file_id=fid, version_no=1, is_primary=is_primary,
    )
    session.add(v)
    await session.commit()
    if is_primary:
        await session.refresh(v)
        doc.primary_version_id = v.id
        session.add(doc)
        await session.commit()
    return doc, v


@pytest.mark.asyncio
async def test_aget_files_by_similar_status_pending(async_db_session, monkeypatch):
    """KnowledgeFileDao.aget_files_by_similar_status returns files matching similar_status."""
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, 100, similar_status=1)
    await _seed_file(async_db_session, 101, similar_status=0)
    await _seed_file(async_db_session, 102, similar_status=2)

    with patch("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
               side_effect=lambda: _ctx()):
        rows = await KnowledgeFileDao.aget_files_by_similar_status(1, similar_status=1)
        ids = {r.id for r in rows}
        assert ids == {100}


@pytest.mark.asyncio
async def test_aget_files_by_similar_status_excludes_unparsed(async_db_session, monkeypatch):
    """aget_files_by_similar_status only returns parsed-SUCCESS files."""
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield async_db_session

    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, 100, similar_status=1, status=2)  # SUCCESS
    await _seed_file(async_db_session, 101, similar_status=1, status=1)  # WAITING

    with patch("bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
               side_effect=lambda: _ctx()):
        rows = await KnowledgeFileDao.aget_files_by_similar_status(1, similar_status=1)
        assert {r.id for r in rows} == {100}


@pytest.mark.asyncio
async def test_find_main_version_files_in_space(async_db_session):
    """find_main_version_files_in_space returns parsed-success primary-version files only."""
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, 100, simhash="aaaaaaaaaaaaaaaa")  # primary
    await _seed_file(async_db_session, 101, simhash="bbbbbbbbbbbbbbbb")  # non-primary
    await _seed_file(async_db_session, 200, simhash="cccccccccccccccc")  # primary, status FAIL
    await _seed_doc_v1(async_db_session, 100, is_primary=True)
    await _seed_doc_v1(async_db_session, 101, is_primary=False)
    # mark file 200 as failed
    f200 = await async_db_session.get(KnowledgeFile, 200)
    f200.status = 3
    async_db_session.add(f200); await async_db_session.commit()
    await _seed_doc_v1(async_db_session, 200, is_primary=True)

    repo = KnowledgeFileRepositoryImpl(async_db_session)
    rows = await repo.find_main_version_files_in_space(knowledge_id=1)
    ids = {r.id for r in rows}
    assert ids == {100}  # only parsed-success primary file


@pytest.mark.asyncio
async def test_find_main_version_files_excludes_self(async_db_session):
    """exclude_file_id removes the specified file from results."""
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, 100, simhash="aaaaaaaaaaaaaaaa")
    await _seed_file(async_db_session, 101, simhash="bbbbbbbbbbbbbbbb")
    await _seed_doc_v1(async_db_session, 100, is_primary=True)
    await _seed_doc_v1(async_db_session, 101, is_primary=True)

    repo = KnowledgeFileRepositoryImpl(async_db_session)
    rows = await repo.find_main_version_files_in_space(knowledge_id=1, exclude_file_id=100)
    assert {r.id for r in rows} == {101}
