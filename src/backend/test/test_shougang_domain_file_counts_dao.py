"""DB-backed tests for KnowledgeFileDao.async_count_files_by_domain_codes.

Counts SUCCESS document files per business-domain code (the second-from-last
'-'-segment of file_encoding) across ALL knowledge bases, ignoring space/login
filters.
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
async def test_count_files_by_domain_codes_uses_second_from_last_segment_exactly(async_db_session):
    # Spread across DIFFERENT knowledge_ids to prove the filter ignores space.
    await _insert(async_db_session, knowledge_id=10, file_name='a', file_encoding='GF-STD-PP-001')
    await _insert(async_db_session, knowledge_id=11, file_name='b', file_encoding='GF-RPT-PP-002')
    await _insert(async_db_session, knowledge_id=12, file_name='c', file_encoding='GF-STD-QM-003')
    # FAILED status -> not counted
    await _insert(async_db_session, knowledge_id=10, file_name='d',
                  file_encoding='GF-STD-PP-004', status=KnowledgeFileStatus.FAILED.value)
    # DIR file_type -> not counted
    await _insert(async_db_session, knowledge_id=10, file_name='e',
                  file_encoding='GF-STD-PP-005', file_type=FileType.DIR.value)
    # NULL encoding -> not counted
    await _insert(async_db_session, knowledge_id=10, file_name='f', file_encoding=None)
    # 'PP' only appears in 1st segment; second-from-last segment is SA -> counts as SA, not PP.
    await _insert(async_db_session, knowledge_id=13, file_name='g', file_encoding='PP-STD-SA-006')

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(['PP', 'QM', 'SA'])

    assert result == {'PP': 2, 'QM': 1, 'SA': 1}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_rejects_like_overfetch_on_non_business_segment(async_db_session):
    # 'PP' sits in a dash-surrounded NON-business segment, so the
    # LIKE '%-PP-%' prefilter WILL fetch this row -- but the business code
    # (second-from-last segment) is QM. The Python guard must reject the
    # over-fetch and count it as QM only, never PP.
    await _insert(async_db_session, knowledge_id=30, file_name='a', file_encoding='GF-PP-QM-001')
    # Multi-segment, operator-configured prefix ('GF-PP'): the business code is
    # still the second-from-last segment (QM). Counting parts[2] here would
    # wrongly pick 'QM' for one row but generally breaks once the prefix grows;
    # the dash-surrounded 'PP' again tempts the LIKE prefilter to over-fetch.
    await _insert(async_db_session, knowledge_id=31, file_name='b', file_encoding='GF-PP-EXTRA-QM-002')

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(['PP', 'QM'])

    assert result == {'PP': 0, 'QM': 2}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_dedupes_mixed_case_codes(async_db_session):
    await _insert(async_db_session, knowledge_id=40, file_name='a', file_encoding='GF-STD-PP-001')
    await _insert(async_db_session, knowledge_id=41, file_name='b', file_encoding='GF-RPT-PP-002')

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(['PP', 'pp', 'PP'])

    # Duplicate/mixed-case requests collapse to a single normalized key.
    assert result == {'PP': 2}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_empty_codes_returns_empty(async_db_session):
    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes([])
    assert result == {}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_unmatched_code_returns_zero(async_db_session):
    await _insert(async_db_session, knowledge_id=20, file_name='a', file_encoding='GF-STD-PP-001')

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(['PP', 'ZZ'])

    assert result == {'PP': 1, 'ZZ': 0}


@pytest.mark.asyncio
async def test_count_files_by_domain_scopes_only_counts_matching_visible_spaces():
    class FakeResult:
        def all(self):
            return [
                (10, 'GF-STD-PP-001'),
                (11, 'GF-STD-PP-002'),
                (20, 'GF-STD-QM-003'),
                (10, 'GF-PP-QM-004'),
            ]

    class FakeSession:
        async def exec(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    with _patch_session_factory(session):
        result = await KnowledgeFileDao.async_count_files_by_domain_scopes(
            {'PP': {10}, 'QM': {20}},
        )

    # 11 不在 PP 可见空间；最后一条的业务域是 QM，但 10 不在 QM 可见空间。
    assert result == {'PP': 1, 'QM': 1}
