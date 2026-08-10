"""F079 T006: library-mode search over approved tags.

Library mode lists rows from ``tag`` only — pending and rejected tags live in
``review_tag`` and belong to the other mode, so they must never leak in here.

Visibility is tenant-only (AD-12): a tag library is tenant-level vocabulary, not
a per-space asset, and the left panel's library list is already tenant-scoped.
Filtering these rows by which files happen to carry the tag would make the left
panel's tag_count disagree with the right panel, and would hide a freshly added
tag until someone used it.
"""

from datetime import datetime

import pytest
from sqlmodel import select

from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.tag_console_repository import TagConsoleRepositoryImpl
from bisheng.workstation.domain.schemas.tag_console_schema import TagConsoleSearchReq

TENANT_ID = 1
LIB_PROCESS = 10
LIB_DEFECT = 20
ALICE, BOB, CAROL = 101, 102, 103


async def _seed(session):
    """Two libraries, six approved tags, plus one row that must stay invisible."""
    rows = [
        # name, library, resource_type, submitter, reviewer, created, reviewed
        ("漏水", LIB_PROCESS, TagResourceTypeEnum.AI_AUTO_TAG, ALICE, CAROL, "2026-08-01", "2026-08-02"),
        ("轴承过热", LIB_PROCESS, TagResourceTypeEnum.MANUAL_TAG, ALICE, None, "2026-08-03", None),
        ("振动异常", LIB_PROCESS, TagResourceTypeEnum.SYSTEM_TAG, BOB, CAROL, "2026-08-05", "2026-08-06"),
        ("结垢", LIB_DEFECT, TagResourceTypeEnum.AI_AUTO_TAG, BOB, CAROL, "2026-08-04", "2026-08-07"),
        ("表面裂纹", LIB_DEFECT, TagResourceTypeEnum.AI_AUTO_TAG, BOB, None, "2026-08-06", None),
        ("边裂", LIB_DEFECT, TagResourceTypeEnum.MANUAL_TAG, ALICE, CAROL, "2026-08-07", "2026-08-07"),
    ]
    for name, library_id, resource_type, submitter, reviewer, created, reviewed in rows:
        session.add(
            Tag(
                name=name,
                business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                business_id=str(library_id),
                user_id=submitter,
                tenant_id=TENANT_ID,
                resource_type=resource_type.value,
                create_time=datetime.fromisoformat(created),
                update_time=datetime.fromisoformat(created),
                reviewer_id=reviewer,
                review_time=datetime.fromisoformat(reviewed) if reviewed else None,
            )
        )
    # An application tag: same table, different business_type. Must not show up.
    session.add(
        Tag(
            name="不该出现的应用标签",
            business_type=TagBusinessTypeEnum.APPLICATION.value,
            business_id="999",
            user_id=ALICE,
            tenant_id=TENANT_ID,
            resource_type=TagResourceTypeEnum.MANUAL_TAG.value,
            create_time=datetime(2026, 8, 8),
            update_time=datetime(2026, 8, 8),
        )
    )
    await session.commit()

    tags = (await session.exec(select(Tag).where(Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value))).all()
    by_name = {tag.name: tag for tag in tags}
    # "漏水" is applied to two files, "结垢" to one, the rest to none.
    for tag_name, file_ids in (("漏水", [501, 502]), ("结垢", [503])):
        for file_id in file_ids:
            session.add(
                TagLink(
                    tag_id=by_name[tag_name].id,
                    resource_id=str(file_id),
                    resource_type=1,
                    user_id=ALICE,
                    tenant_id=TENANT_ID,
                    create_time=datetime(2026, 8, 8),
                    update_time=datetime(2026, 8, 8),
                )
            )
    await session.commit()
    return by_name


async def _search(session, **overrides):
    repository = TagConsoleRepositoryImpl(session=session)
    req = TagConsoleSearchReq(**overrides)
    return await repository.search_library_tags(req, tenant_id=TENANT_ID)


@pytest.mark.asyncio
async def test_search_all_libraries_when_ids_empty(async_db_session):
    await _seed(async_db_session)

    rows, total = await _search(async_db_session)

    assert total == 6
    assert {row.name for row in rows} == {"漏水", "轴承过热", "振动异常", "结垢", "表面裂纹", "边裂"}


@pytest.mark.asyncio
async def test_search_filters_by_selected_libraries(async_db_session):
    await _seed(async_db_session)

    rows, total = await _search(async_db_session, library_ids=[LIB_DEFECT])
    assert total == 3
    assert {row.name for row in rows} == {"结垢", "表面裂纹", "边裂"}

    rows, total = await _search(async_db_session, library_ids=[LIB_PROCESS, LIB_DEFECT])
    assert total == 6


@pytest.mark.asyncio
async def test_search_ignores_missing_library_ids(async_db_session):
    """A library another admin deleted must not blow up the query."""
    await _seed(async_db_session)

    rows, total = await _search(async_db_session, library_ids=[LIB_DEFECT, 99999])

    assert total == 3
    assert {row.name for row in rows} == {"结垢", "表面裂纹", "边裂"}


@pytest.mark.asyncio
async def test_search_excludes_non_library_tags(async_db_session):
    """Application/knowledge tags share the table but belong to other features."""
    await _seed(async_db_session)

    rows, _ = await _search(async_db_session, page_size=200)

    assert all(row.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value for row in rows)
    assert "不该出现的应用标签" not in {row.name for row in rows}


@pytest.mark.asyncio
async def test_search_filter_by_tag_name(async_db_session):
    await _seed(async_db_session)

    rows, total = await _search(async_db_session, tag_name="裂")

    assert total == 2
    assert {row.name for row in rows} == {"表面裂纹", "边裂"}


@pytest.mark.asyncio
async def test_search_filter_by_resource_type(async_db_session):
    await _seed(async_db_session)

    rows, total = await _search(async_db_session, resource_type=TagResourceTypeEnum.AI_AUTO_TAG.value)

    assert total == 3
    assert {row.name for row in rows} == {"漏水", "结垢", "表面裂纹"}


@pytest.mark.asyncio
async def test_search_filter_by_submitter_and_reviewer(async_db_session):
    await _seed(async_db_session)

    _, submitted_by_alice = await _search(async_db_session, submitter_id=ALICE)
    assert submitted_by_alice == 3

    rows, reviewed_by_carol = await _search(async_db_session, reviewer_id=CAROL)
    assert reviewed_by_carol == 4
    # Never-reviewed rows must drop out when filtering on reviewer.
    assert "轴承过热" not in {row.name for row in rows}


@pytest.mark.asyncio
async def test_search_filter_by_date_range_and_single_side(async_db_session):
    await _seed(async_db_session)

    _, both_sides = await _search(
        async_db_session,
        create_time_start=datetime(2026, 8, 3),
        create_time_end=datetime(2026, 8, 5, 23, 59, 59),
    )
    assert both_sides == 3  # 轴承过热 / 结垢 / 振动异常

    _, start_only = await _search(async_db_session, create_time_start=datetime(2026, 8, 6))
    assert start_only == 2  # 表面裂纹 / 边裂

    _, end_only = await _search(async_db_session, create_time_end=datetime(2026, 8, 1, 23, 59, 59))
    assert end_only == 1  # 漏水

    _, reviewed = await _search(async_db_session, review_time_start=datetime(2026, 8, 7))
    assert reviewed == 2  # 结垢 / 边裂


@pytest.mark.asyncio
async def test_search_pagination_total_and_stable_order(async_db_session):
    """Newest first, id as tiebreak; paging must not repeat or drop a row."""
    await _seed(async_db_session)

    page1, total = await _search(async_db_session, page=1, page_size=4)
    page2, _ = await _search(async_db_session, page=2, page_size=4)

    assert total == 6
    assert len(page1) == 4
    assert len(page2) == 2

    seen = [row.name for row in page1] + [row.name for row in page2]
    assert len(set(seen)) == 6, "paging repeated or dropped rows"
    # 边裂 (08-07) is newest, 漏水 (08-01) oldest.
    assert seen[0] == "边裂"
    assert seen[-1] == "漏水"


@pytest.mark.asyncio
async def test_search_is_tenant_scoped_not_department_scoped(async_db_session):
    """AD-12: another tenant's tags stay invisible, but no per-space narrowing."""
    await _seed(async_db_session)
    async_db_session.add(
        Tag(
            name="他租户标签",
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id=str(LIB_PROCESS),
            user_id=ALICE,
            tenant_id=999,
            resource_type=TagResourceTypeEnum.MANUAL_TAG.value,
            create_time=datetime(2026, 8, 9),
            update_time=datetime(2026, 8, 9),
        )
    )
    await async_db_session.commit()

    rows, total = await _search(async_db_session, page_size=200)

    assert total == 6
    assert "他租户标签" not in {row.name for row in rows}


@pytest.mark.asyncio
async def test_marked_knowledge_counts_are_batched(async_db_session):
    """Counts come from tag_link; unused tags legitimately report zero."""
    by_name = await _seed(async_db_session)
    repository = TagConsoleRepositoryImpl(session=async_db_session)

    counts = await repository.count_marked_knowledge([tag.id for tag in by_name.values()], tenant_id=TENANT_ID)

    assert counts[by_name["漏水"].id] == 2
    assert counts[by_name["结垢"].id] == 1
    assert counts.get(by_name["边裂"].id, 0) == 0
