"""DB-backed tests: QA file search can match file_encoding when enabled.

search_shougang_portal_qa_files_by_name searches files by a keyword. Operators
want that keyword to ALSO match the file_encoding column (e.g. 'DEV-PROC-001'),
not just file_name. The behaviour is gated behind ``match_file_encoding`` so the
other callers of aget_file_by_space_filters keep name-only matching.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)


def _patch_session_factory(session):
    """Patch get_async_db_session inside the knowledge_file module to yield session."""

    @asynccontextmanager
    async def _fake_factory():
        yield session

    return patch(
        'bisheng.knowledge.domain.models.knowledge_file.get_async_db_session',
        _fake_factory,
    )


async def _insert(session, **kwargs):
    defaults = dict(
        user_id=1,
        user_name='tester',
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )
    defaults.update(kwargs)
    file = KnowledgeFile(**defaults)
    session.add(file)
    await session.commit()
    return file


@pytest.mark.asyncio
async def test_space_filters_keyword_matches_name_or_encoding_when_enabled(async_db_session):
    # name matches the keyword
    await _insert(async_db_session, knowledge_id=10, file_name='PROC手册.pdf', file_encoding='X-A-1')
    # file_encoding matches the keyword
    await _insert(async_db_session, knowledge_id=10, file_name='桃树应用.pdf', file_encoding='DEV-PROC-001')
    # neither matches; also proves NULL encoding does not blow up the OR clause
    await _insert(async_db_session, knowledge_id=10, file_name='无关.pdf', file_encoding=None)

    with _patch_session_factory(async_db_session):
        rows = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=[10],
            file_name='PROC',
            status=[KnowledgeFileStatus.SUCCESS.value],
            match_file_encoding=True,
        )

    assert {r.file_name for r in rows} == {'PROC手册.pdf', '桃树应用.pdf'}


@pytest.mark.asyncio
async def test_space_filters_default_matches_name_only(async_db_session):
    # keyword only appears in file_encoding, not file_name
    await _insert(async_db_session, knowledge_id=10, file_name='无关文档.pdf', file_encoding='DEV-PROC-001')

    with _patch_session_factory(async_db_session):
        rows = await KnowledgeFileDao.aget_file_by_space_filters(
            knowledge_ids=[10],
            file_name='DEV-PROC-001',
            status=[KnowledgeFileStatus.SUCCESS.value],
        )

    assert rows == []
