"""历史知识文件原始来源回填脚本的回归测试。"""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
)
from scripts.backfill_knowledge_file_original_origin import backfill_original_origins


def _space(space_id: int, tenant_id: int = 7) -> Knowledge:
    return Knowledge(
        id=space_id,
        tenant_id=tenant_id,
        user_id=1,
        name=f"space-{space_id}",
        type=KnowledgeTypeEnum.SPACE.value,
    )


def _file(
    file_id: int,
    *,
    knowledge_id: int,
    user_id: int | None,
    tenant_id: int = 7,
    **kwargs,
) -> KnowledgeFile:
    return KnowledgeFile(
        id=file_id,
        tenant_id=tenant_id,
        knowledge_id=knowledge_id,
        user_id=user_id,
        file_name=f"file-{file_id}.pdf",
        file_type=FileType.FILE.value,
        **kwargs,
    )


async def _rows(session: AsyncSession, *file_ids: int) -> dict[int, KnowledgeFile]:
    session.expire_all()
    result = await session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids)))
    return {int(row.id): row for row in result.scalars().all()}


@pytest.mark.asyncio
async def test_dry_run_apply_and_repeat_are_safe_for_ordinary_rows(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            _space(10),
            _space(80, tenant_id=8),
            _file(100, knowledge_id=10, user_id=501),
            _file(
                101,
                knowledge_id=10,
                user_id=502,
                deleted_at=datetime(2026, 8, 1),
            ),
            _file(
                102,
                knowledge_id=10,
                user_id=503,
                file_source="favorite_reference",
            ),
            _file(
                103,
                knowledge_id=10,
                user_id=504,
                entry_type=KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
            ),
            _file(
                104,
                knowledge_id=10,
                user_id=505,
                original_uploader_id=505,
            ),
            _file(180, knowledge_id=80, user_id=805, tenant_id=8),
        ]
    )
    await async_db_session.commit()

    dry_run = await backfill_original_origins(async_db_session)
    rows = await _rows(async_db_session, 100, 101, 102, 103, 104, 180)
    assert dry_run.would_update == 4
    assert dry_run.updated == 0
    assert rows[100].original_uploader_id is None
    assert rows[101].original_knowledge_id is None

    scoped = await backfill_original_origins(
        async_db_session,
        knowledge_id=10,
        start_after_id=100,
        limit=1,
    )
    assert scoped.scanned == 1
    assert scoped.would_update == 1
    assert scoped.next_start_after_id == 101

    applied = await backfill_original_origins(async_db_session, apply=True, batch_size=1)
    rows = await _rows(async_db_session, 100, 101, 102, 103, 104, 180)
    assert applied.updated == 4
    assert (rows[100].original_uploader_id, rows[100].original_knowledge_id) == (501, 10)
    assert (rows[101].original_uploader_id, rows[101].original_knowledge_id) == (502, 10)
    assert rows[102].original_uploader_id is None
    assert rows[103].original_uploader_id is None
    assert (rows[104].original_uploader_id, rows[104].original_knowledge_id) == (505, 10)
    assert (rows[180].original_uploader_id, rows[180].original_knowledge_id) == (805, 80)

    repeated = await backfill_original_origins(async_db_session)
    assert repeated.would_update == 0


@pytest.mark.asyncio
async def test_legacy_multilevel_copy_uses_root_upload_origin(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            _space(10),
            _space(20),
            _space(30),
            _file(100, knowledge_id=10, user_id=501),
            _file(
                200,
                knowledge_id=20,
                user_id=601,
                user_metadata={
                    "shougang_portal_publish": {
                        "source_space_id": 10,
                        "source_file_id": 100,
                    }
                },
            ),
            _file(
                300,
                knowledge_id=30,
                user_id=701,
                user_metadata={
                    "shougang_portal_publish": {
                        "source_space_id": 20,
                        "source_file_id": 200,
                    }
                },
            ),
        ]
    )
    await async_db_session.commit()

    report = await backfill_original_origins(async_db_session, apply=True, file_id=300)
    row = (await _rows(async_db_session, 300))[300]

    assert report.updated == 1
    assert (row.original_uploader_id, row.original_knowledge_id) == (501, 10)


@pytest.mark.asyncio
async def test_canonical_predecessor_origin_updates_the_whole_group(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            _space(10),
            _space(20),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=501,
                predecessor_logic_file_id=101,
            ),
            _file(
                100,
                knowledge_id=20,
                user_id=501,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
            ),
            _file(
                101,
                knowledge_id=10,
                user_id=501,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()

    report = await backfill_original_origins(async_db_session, apply=True, file_id=100)
    rows = await _rows(async_db_session, 100, 101)

    assert report.processed_groups == 1
    assert report.updated == 2
    assert {(row.original_uploader_id, row.original_knowledge_id) for row in rows.values()} == {(501, 10)}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "cycle", "cross_tenant"])
async def test_broken_legacy_chains_fail_closed(
    async_db_session: AsyncSession,
    failure: str,
):
    source_id = 999 if failure == "missing" else 100
    source_tenant = 8 if failure == "cross_tenant" else 7
    rows = [_space(10), _space(20)]
    if failure != "missing":
        rows.extend(
            [
                _space(30, tenant_id=source_tenant),
                _file(
                    100,
                    knowledge_id=30,
                    user_id=501,
                    tenant_id=source_tenant,
                    user_metadata=({"shougang_portal_publish": {"source_file_id": 200}} if failure == "cycle" else {}),
                ),
            ]
        )
    rows.append(
        _file(
            200,
            knowledge_id=20,
            user_id=601,
            user_metadata={"shougang_portal_publish": {"source_file_id": source_id}},
        )
    )
    async_db_session.add_all(rows)
    await async_db_session.commit()

    report = await backfill_original_origins(async_db_session, apply=True, file_id=200)
    row = (await _rows(async_db_session, 200))[200]

    assert report.updated == 0
    assert report.broken_chain == 1
    assert row.original_uploader_id is None
    assert row.original_knowledge_id is None


@pytest.mark.asyncio
async def test_canonical_existing_value_conflict_skips_the_entire_group(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            _space(10),
            KnowledgeDocument(id=91, tenant_id=7, knowledge_id=10, primary_version_id=501),
            _file(
                100,
                knowledge_id=10,
                user_id=501,
                original_uploader_id=501,
                original_knowledge_id=10,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
            ),
            _file(
                101,
                knowledge_id=10,
                user_id=501,
                original_uploader_id=999,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=1,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()

    report = await backfill_original_origins(async_db_session, apply=True, file_id=101)
    row = (await _rows(async_db_session, 101))[101]

    assert report.updated == 0
    assert report.conflict == 1
    assert row.original_uploader_id == 999
    assert row.original_knowledge_id is None


@pytest.mark.asyncio
async def test_historical_merge_shaped_canonical_group_is_not_guessed(
    async_db_session: AsyncSession,
):
    async_db_session.add_all(
        [
            _space(10),
            _space(20),
            KnowledgeDocument(
                id=91,
                tenant_id=7,
                knowledge_id=20,
                primary_version_id=502,
                predecessor_logic_file_id=102,
            ),
            _file(100, knowledge_id=20, user_id=801),
            _file(
                101,
                knowledge_id=20,
                user_id=501,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.MANAGER.value,
            ),
            _file(
                102,
                knowledge_id=10,
                user_id=501,
                reference_document_id=91,
                entry_type=KnowledgeFileEntryType.PUBLISH.value,
            ),
            KnowledgeDocumentVersion(
                id=501,
                document_id=91,
                knowledge_file_id=100,
                version_no=1,
                is_primary=False,
            ),
            KnowledgeDocumentVersion(
                id=502,
                document_id=91,
                knowledge_file_id=101,
                version_no=2,
                is_primary=True,
            ),
        ]
    )
    await async_db_session.commit()

    report = await backfill_original_origins(async_db_session, apply=True, file_id=101)
    rows = await _rows(async_db_session, 100, 101, 102)

    assert report.updated == 0
    assert report.broken_chain == 1
    assert report.reason_counts["canonical_merged_origin_ambiguous"] == 1
    assert all(row.original_uploader_id is None for row in rows.values())
