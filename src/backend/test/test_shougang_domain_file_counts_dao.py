"""DB-backed tests for KnowledgeFileDao.async_count_files_by_domain_codes.

Counts SUCCESS document files per business-domain code (the second-from-last
'-'-segment of file_encoding) across ALL knowledge bases, ignoring space/login
filters.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)


def _patch_session_factory(session):
    """Patch get_async_db_session inside the knowledge_file module to yield session."""

    @asynccontextmanager
    async def _fake_factory():
        yield session

    return patch(
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        _fake_factory,
    )


async def _insert(session, **kwargs):
    defaults = dict(
        user_id=1,
        user_name="tester",
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
    await _insert(async_db_session, knowledge_id=10, file_name="a", file_encoding="GF-STD-PP-001")
    await _insert(async_db_session, knowledge_id=11, file_name="b", file_encoding="GF-RPT-PP-002")
    await _insert(async_db_session, knowledge_id=12, file_name="c", file_encoding="GF-STD-QM-003")
    # FAILED status -> not counted
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="d",
        file_encoding="GF-STD-PP-004",
        status=KnowledgeFileStatus.FAILED.value,
    )
    # DIR file_type -> not counted
    await _insert(
        async_db_session, knowledge_id=10, file_name="e", file_encoding="GF-STD-PP-005", file_type=FileType.DIR.value
    )
    # NULL encoding -> not counted
    await _insert(async_db_session, knowledge_id=10, file_name="f", file_encoding=None)
    # 'PP' only appears in 1st segment; second-from-last segment is SA -> counts as SA, not PP.
    await _insert(async_db_session, knowledge_id=13, file_name="g", file_encoding="PP-STD-SA-006")

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(["PP", "QM", "SA"])

    assert result == {"PP": 2, "QM": 1, "SA": 1}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_rejects_like_overfetch_on_non_business_segment(async_db_session):
    # 'PP' sits in a dash-surrounded NON-business segment, so the
    # LIKE '%-PP-%' prefilter WILL fetch this row -- but the business code
    # (second-from-last segment) is QM. The Python guard must reject the
    # over-fetch and count it as QM only, never PP.
    await _insert(async_db_session, knowledge_id=30, file_name="a", file_encoding="GF-PP-QM-001")
    # Multi-segment, operator-configured prefix ('GF-PP'): the business code is
    # still the second-from-last segment (QM). Counting parts[2] here would
    # wrongly pick 'QM' for one row but generally breaks once the prefix grows;
    # the dash-surrounded 'PP' again tempts the LIKE prefilter to over-fetch.
    await _insert(async_db_session, knowledge_id=31, file_name="b", file_encoding="GF-PP-EXTRA-QM-002")

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(["PP", "QM"])

    assert result == {"PP": 0, "QM": 2}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_dedupes_mixed_case_codes(async_db_session):
    await _insert(async_db_session, knowledge_id=40, file_name="a", file_encoding="GF-STD-PP-001")
    await _insert(async_db_session, knowledge_id=41, file_name="b", file_encoding="GF-RPT-PP-002")

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(["PP", "pp", "PP"])

    # Duplicate/mixed-case requests collapse to a single normalized key.
    assert result == {"PP": 2}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_empty_codes_returns_empty(async_db_session):
    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes([])
    assert result == {}


@pytest.mark.asyncio
async def test_count_files_by_domain_codes_unmatched_code_returns_zero(async_db_session):
    await _insert(async_db_session, knowledge_id=20, file_name="a", file_encoding="GF-STD-PP-001")

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_domain_codes(["PP", "ZZ"])

    assert result == {"PP": 1, "ZZ": 0}


@pytest.mark.asyncio
async def test_count_files_by_domain_scopes_only_counts_matching_visible_spaces():
    """Domain scopes still count by encoding business segment (unchanged by category fix)."""

    class FakeResult:
        def all(self):
            # (file_id, reference_document_id, knowledge_id, file_encoding)
            return [
                (1, 1, 10, "GF-STD-PP-001"),
                (2, 2, 11, "GF-STD-PP-002"),
                (3, 3, 20, "GF-STD-QM-003"),
                (4, 4, 10, "GF-PP-QM-004"),
            ]

    class FakeSession:
        async def exec(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    with _patch_session_factory(session):
        result = await KnowledgeFileDao.async_count_files_by_domain_scopes(
            {"PP": {10}, "QM": {20}},
        )

    # 11 不在 PP 可见空间；最后一条的业务域是 QM，但 10 不在 QM 可见空间。
    assert result == {"PP": 1, "QM": 1}


@pytest.mark.asyncio
async def test_count_files_by_category_scopes_filters_by_document_type_in_bound_spaces():
    """Category homepage counts files whose document-type code matches the card code."""

    class FakeResult:
        def all(self):
            return [
                (1, 1, 10, "GF-STD-PP-001"),
                (2, 2, 10, "GF-POL-PP-002"),
                (3, 3, 20, "GF-STD-QM-003"),
                (4, 4, 10, "GF-PP-QM-004"),
            ]

    class FakeSession:
        async def exec(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    with _patch_session_factory(session):
        result = await KnowledgeFileDao.async_count_files_by_category_scopes(
            {"POL": {10}, "STD": {10, 20}, "QM": {10}},
        )

    # Last row's document type is QM, but space 10 is not in QM scope.
    assert result == {"POL": 1, "STD": 2, "QM": 0}


@pytest.mark.asyncio
async def test_scoped_counts_include_only_explicit_grant_files_from_grant_only_parent(
):
    class DomainResult:
        def all(self):
            return [
                (1, 1, 10, "GF-STD-PM-001"),
                (2, 2, 30, "GF-STD-PM-002"),
                (3, 3, 30, "GF-STD-PM-003"),
            ]

    class CategoryResult:
        def all(self):
            return [
                (1, 1, 10, "GF-STD-PM-001"),
                (2, 2, 30, "GF-STD-PM-002"),
                (3, 3, 30, "GF-STD-PM-003"),
            ]

    class FakeSession:
        def __init__(self, result):
            self.result = result

        async def exec(self, statement):
            self.statement = statement
            return self.result

    with _patch_session_factory(FakeSession(DomainResult())):
        domain_counts = await KnowledgeFileDao.async_count_files_by_domain_scopes(
            {"PM": {10}},
            {"PM": {2}},
        )
    with _patch_session_factory(FakeSession(CategoryResult())):
        category_counts = await KnowledgeFileDao.async_count_files_by_category_scopes(
            {"STD": {10}},
            {"STD": {2}},
        )

    assert domain_counts == {"PM": 2}
    assert category_counts == {"STD": 2}


@pytest.mark.asyncio
async def test_count_files_by_category_scopes_rejects_like_overfetch_on_non_document_segment(async_db_session):
    # LIKE '%-POL-%' prefilter fetches this row, but the document-type segment is STD.
    await _insert(async_db_session, knowledge_id=10, file_name="a", file_encoding="GF-STD-POL-001")
    await _insert(async_db_session, knowledge_id=10, file_name="b", file_encoding="GF-POL-PP-002")
    await _insert(async_db_session, knowledge_id=20, file_name="c", file_encoding="GF-STD-QM-003")

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_category_scopes(
            {"POL": {10}, "STD": {10, 20}},
        )

    assert result == {"POL": 1, "STD": 2}


@pytest.mark.asyncio
async def test_count_files_by_category_scopes_empty_space_returns_zero():
    result = await KnowledgeFileDao.async_count_files_by_category_scopes({"STD": set()})
    assert result == {"STD": 0}


@pytest.mark.asyncio
async def test_count_files_by_category_scopes_matches_active_canonical_inventory(async_db_session):
    common = {
        "knowledge_id": 10,
        "file_encoding": "GF-STD-PP-001",
        "reference_document_id": 900,
        "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
    }
    await _insert(
        async_db_session,
        file_name="manager.pdf",
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        **common,
    )
    await _insert(
        async_db_session,
        file_name="publish.pdf",
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        **common,
    )
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="invalid.pdf",
        file_encoding="GF-STD-PP-002",
        reference_document_id=901,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.INVALID.value,
    )

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.async_count_files_by_category_scopes({"STD": {10}})

    assert result == {"STD": 1}


@pytest.mark.asyncio
async def test_portal_file_count_matches_cursor_canonical_scope(async_db_session):
    common = {
        "knowledge_id": 10,
        "file_encoding": "GF-STD-PM-001",
        "reference_document_id": 900,
        "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
    }
    await _insert(
        async_db_session,
        file_name="manager.pdf",
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        **common,
    )
    await _insert(
        async_db_session,
        file_name="publish.pdf",
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        **common,
    )
    granted = await _insert(
        async_db_session,
        knowledge_id=30,
        file_name="granted.pdf",
        file_encoding="GF-STD-PM-002",
        reference_document_id=901,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    await _insert(
        async_db_session,
        knowledge_id=30,
        file_name="not-granted.pdf",
        file_encoding="GF-STD-PM-003",
        reference_document_id=902,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="inactive.pdf",
        file_encoding="GF-STD-PM-004",
        reference_document_id=903,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.INVALID.value,
    )

    filters = {
        "knowledge_ids": [10, 30],
        "status": [KnowledgeFileStatus.SUCCESS.value],
        "file_ext": "pdf",
        "document_type": "STD",
        "business_domain_code": "PM",
        "full_space_ids": [10],
        "explicit_file_ids": [int(granted.id)],
    }
    with _patch_session_factory(async_db_session):
        total = await KnowledgeFileDao.acount_portal_files(**filters)
        rows = await KnowledgeFileDao.aget_file_by_space_filters_cursor(
            **filters,
            order_sort="desc",
            cursor=None,
            limit=100,
        )

    assert total == 2
    assert {int(file.reference_document_id or file.id) for file in rows} == {900, 901}


@pytest.mark.asyncio
async def test_portal_cursor_paginates_canonical_documents_without_cross_page_duplicates(async_db_session):
    first = await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="manager.pdf",
        file_encoding="GF-STD-PP-001",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        update_time=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    await _insert(
        async_db_session,
        knowledge_id=20,
        file_name="publish.pdf",
        file_encoding="GF-STD-PP-001",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        update_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    second = await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="other.pdf",
        file_encoding="GF-STD-PP-002",
        reference_document_id=901,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        update_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with _patch_session_factory(async_db_session):
        first_page = await KnowledgeFileDao.aget_file_by_space_filters_cursor(
            knowledge_ids=[10, 20],
            status=[KnowledgeFileStatus.SUCCESS.value],
            document_type="STD",
            business_domain_code="PP",
            order_sort="desc",
            limit=1,
        )
        second_page = await KnowledgeFileDao.aget_file_by_space_filters_cursor(
            knowledge_ids=[10, 20],
            status=[KnowledgeFileStatus.SUCCESS.value],
            document_type="STD",
            business_domain_code="PP",
            order_sort="desc",
            cursor=[first_page[-1].update_time, first_page[-1].id],
            limit=1,
        )

    assert [item.id for item in first_page] == [first.id]
    assert [item.id for item in second_page] == [second.id]


@pytest.mark.asyncio
async def test_navigation_counts_equal_all_canonical_cursor_pages(async_db_session):
    common = {
        "file_encoding": "GF-STD-PP-001",
        "entry_status": KnowledgeFileEntryStatus.ACTIVE.value,
    }
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="manager.pdf",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        update_time=datetime(2026, 1, 3, tzinfo=timezone.utc),
        **common,
    )
    await _insert(
        async_db_session,
        knowledge_id=20,
        file_name="publish.pdf",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        update_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        **common,
    )
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="other.pdf",
        reference_document_id=901,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        update_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        **common,
    )
    await _insert(
        async_db_session,
        knowledge_id=10,
        file_name="invalid.pdf",
        reference_document_id=902,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.INVALID.value,
        update_time=datetime(2025, 12, 31, tzinfo=timezone.utc),
        file_encoding="GF-STD-PP-002",
    )

    with _patch_session_factory(async_db_session):
        category_counts = await KnowledgeFileDao.async_count_files_by_category_scopes(
            {"STD": {10, 20}}
        )
        domain_counts = await KnowledgeFileDao.async_count_files_by_domain_scopes(
            {"PP": {10, 20}}
        )
        listed = []
        cursor = None
        while True:
            page = await KnowledgeFileDao.aget_file_by_space_filters_cursor(
                knowledge_ids=[10, 20],
                status=[KnowledgeFileStatus.SUCCESS.value],
                document_type="STD",
                business_domain_code="PP",
                order_sort="desc",
                cursor=cursor,
                limit=1,
            )
            if not page:
                break
            listed.extend(page)
            cursor = [page[-1].update_time, page[-1].id]

    canonical_ids = {int(item.reference_document_id or item.id) for item in listed}
    assert category_counts == {"STD": len(listed)}
    assert domain_counts == {"PP": len(listed)}
    assert canonical_ids == {900, 901}


@pytest.mark.asyncio
async def test_portal_cursor_ranks_only_full_space_or_explicit_file_candidates(async_db_session):
    await _insert(
        async_db_session,
        knowledge_id=30,
        file_name="manager.pdf",
        file_encoding="GF-STD-PP-001",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    explicit = await _insert(
        async_db_session,
        knowledge_id=30,
        file_name="publish.pdf",
        file_encoding="GF-STD-PP-001",
        reference_document_id=900,
        entry_type=KnowledgeFileEntryType.PUBLISH.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )

    with _patch_session_factory(async_db_session):
        result = await KnowledgeFileDao.aget_file_by_space_filters_cursor(
            knowledge_ids=[30],
            status=[KnowledgeFileStatus.SUCCESS.value],
            document_type="STD",
            business_domain_code="PP",
            full_space_ids=[],
            explicit_file_ids=[explicit.id],
        )

    assert [item.id for item in result] == [explicit.id]
