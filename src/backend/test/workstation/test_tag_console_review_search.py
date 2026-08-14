"""F079 T008: review-mode search over pending / rejected tags.

Three things here are easy to get silently wrong, so each has its own test:

- **Grouping.** One tag name produced in several knowledge spaces creates one
  ``review_tag`` row per space. The listing must collapse them into a single row
  keyed by ``(name, resource_type)``, the same unit the approval flow works on.
- **The two hidden filters.** The workbench listing also drops names already
  promoted into a real tag library, and pending rows whose file links are all
  gone. Missing either makes this page show rows the old one does not.
- **Rejection is a soft delete.** It flips ``is_deleted`` on both the tag and its
  links, so applying the orphan/library guards to rejected rows would hide every
  single one of them.
"""

from datetime import datetime

import pytest

from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink, TagResourceTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.workstation.domain.repositories.tag_console_repository import (
    SOURCE_REVIEW,
    SOURCE_TAG,
    TagConsoleRepositoryImpl,
)
from bisheng.workstation.domain.schemas.tag_console_schema import (
    TagConsoleReviewSearchReq,
    TagConsoleReviewStatus,
)

TENANT_ID = 1
SPACE_PUMP, SPACE_ROLL = 900, 901
ALICE, BOB, CAROL = 101, 102, 103
AI = TagResourceTypeEnum.AI_AUTO_TAG.value
MANUAL = TagResourceTypeEnum.MANUAL_TAG.value


def _review_tag(name, *, resource_type=AI, space_id=200, submitter=ALICE, created="2026-08-05", **kwargs):
    return ReviewTag(
        name=name,
        business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
        business_id=str(space_id),
        user_id=submitter,
        tenant_id=TENANT_ID,
        resource_type=resource_type,
        create_time=datetime.fromisoformat(created),
        update_time=datetime.fromisoformat(created),
        **kwargs,
    )


async def _link(session, tag_id, file_id, *, is_deleted=False):
    session.add(
        ReviewTagLink(
            tag_id=tag_id,
            resource_id=str(file_id),
            resource_type=1,
            user_id=ALICE,
            tenant_id=TENANT_ID,
            is_deleted=is_deleted,
            create_time=datetime(2026, 8, 5),
            update_time=datetime(2026, 8, 5),
        )
    )


async def _seed(session):
    """Four visible rows plus two that must stay hidden."""
    # 结垢: same name produced in three spaces -> must collapse to one row.
    scale = [
        _review_tag("结垢", space_id=200, created="2026-08-05"),
        _review_tag("结垢", space_id=201, created="2026-08-06"),
        _review_tag("结垢", space_id=202, created="2026-08-04"),
    ]
    pending_others = [
        _review_tag("表面裂纹", space_id=200, created="2026-08-03"),
        _review_tag("边裂", resource_type=MANUAL, space_id=201, submitter=BOB, created="2026-08-07"),
    ]
    rejected = _review_tag(
        "翘曲",
        space_id=200,
        submitter=BOB,
        created="2026-08-02",
        review_status=2,
        is_deleted=True,
        reject_reason="不建议新增",
        reviewer_id=CAROL,
        review_time=datetime(2026, 8, 8),
    )
    # Hidden #1: name already promoted into a real tag library.
    already_in_library = _review_tag("漏水", space_id=200, created="2026-08-06")
    # Hidden #2: pending but every link is gone.
    orphan = _review_tag("孤儿标签", space_id=200, created="2026-08-06")

    for row in [*scale, *pending_others, rejected, already_in_library, orphan]:
        session.add(row)
    # 漏水 went through review and was approved: the review row above is the
    # leftover the library-name guard exists to hide, and the tag below is what
    # the reviewed listing must show instead.
    session.add(
        Tag(
            name="漏水",
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id="10",
            user_id=ALICE,
            tenant_id=TENANT_ID,
            resource_type=AI,
            reviewer_id=CAROL,
            review_time=datetime(2026, 8, 9),
            create_time=datetime(2026, 8, 1),
            update_time=datetime(2026, 8, 1),
        )
    )
    # Typed straight into a library by an admin — never reviewed, so it must not
    # appear in the reviewed listing.
    session.add(
        Tag(
            name="手工录入",
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id="10",
            user_id=ALICE,
            tenant_id=TENANT_ID,
            resource_type=TagResourceTypeEnum.SYSTEM_TAG.value,
            create_time=datetime(2026, 8, 1),
            update_time=datetime(2026, 8, 1),
        )
    )
    await session.commit()

    # Files carry the source knowledge base — neither table records it, so
    # 标签来源库 has to be matched through this chain.
    for file_id, space_id in (
        (500, SPACE_PUMP),
        (501, SPACE_PUMP),
        (502, SPACE_ROLL),
        (510, SPACE_ROLL),
        (511, SPACE_PUMP),
        (512, SPACE_PUMP),
        (513, SPACE_ROLL),
        (514, SPACE_ROLL),
    ):
        session.add(
            KnowledgeFile(
                id=file_id,
                knowledge_id=space_id,
                file_name=f"{file_id}.docx",
                tenant_id=TENANT_ID,
                user_id=ALICE,
                create_time=datetime(2026, 8, 5),
                update_time=datetime(2026, 8, 5),
            )
        )
    await session.commit()

    for index, row in enumerate(scale):
        await _link(session, row.id, 500 + index)
    await _link(session, pending_others[0].id, 510)
    await _link(session, pending_others[1].id, 511)
    # Rejected: links soft-deleted, mirroring what reject_review_tag does.
    await _link(session, rejected.id, 512, is_deleted=True)
    await _link(session, already_in_library.id, 513)
    # orphan: intentionally no active link
    await _link(session, orphan.id, 514, is_deleted=True)
    # Approving copies the file links onto the real tag, which is what gives an
    # approved row its source knowledge base in the reviewed listing.
    approved = (
        await session.exec(
            __import__("sqlmodel").select(Tag).where(Tag.name == "漏水"),
        )
    ).first()
    session.add(
        TagLink(
            tag_id=approved.id,
            resource_id="513",
            resource_type=1,
            user_id=ALICE,
            tenant_id=TENANT_ID,
            create_time=datetime(2026, 8, 9),
            update_time=datetime(2026, 8, 9),
        )
    )
    await session.commit()
    return {"scale": scale, "rejected": rejected, "orphan": orphan}


async def _search(session, *, space_ids=None, **overrides):
    repository = TagConsoleRepositoryImpl(session=session)
    req = TagConsoleReviewSearchReq(**overrides)
    return await repository.search_review_tags(req, tenant_id=TENANT_ID, space_ids=space_ids)


@pytest.mark.asyncio
async def test_groups_by_name_and_resource_type(async_db_session):
    await _seed(async_db_session)

    pairs, total = await _search(async_db_session, status=TagConsoleReviewStatus.PENDING)

    assert total == 3, "结垢 spans three spaces but must count once"
    assert {name for name, _ in pairs} == {"结垢", "表面裂纹", "边裂"}


@pytest.mark.asyncio
async def test_same_name_different_resource_type_stays_separate(async_db_session):
    """The pair is the identity — an AI 结垢 and a manual 结垢 are two rows."""
    await _seed(async_db_session)
    async_db_session.add(_review_tag("结垢", resource_type=MANUAL, space_id=203, created="2026-08-06"))
    await async_db_session.commit()
    rows = (await async_db_session.exec(__import__("sqlmodel").select(ReviewTag))).all()
    await _link(async_db_session, max(row.id for row in rows), 520)
    await async_db_session.commit()

    pairs, total = await _search(async_db_session, status=TagConsoleReviewStatus.PENDING)

    assert total == 4
    assert ("结垢", AI) in pairs
    assert ("结垢", MANUAL) in pairs


@pytest.mark.asyncio
async def test_excludes_names_already_in_library(async_db_session):
    await _seed(async_db_session)

    pairs, _ = await _search(async_db_session, status=TagConsoleReviewStatus.PENDING)

    assert "漏水" not in {name for name, _ in pairs}


@pytest.mark.asyncio
async def test_excludes_orphan_without_active_link(async_db_session):
    await _seed(async_db_session)

    pairs, _ = await _search(async_db_session, status=TagConsoleReviewStatus.PENDING)

    assert "孤儿标签" not in {name for name, _ in pairs}


@pytest.mark.asyncio
async def test_rejected_rows_survive_the_pending_guards(async_db_session):
    """Reject soft-deletes tag and links, so those guards must not apply here."""
    await _seed(async_db_session)

    pairs, total = await _search(async_db_session, status=TagConsoleReviewStatus.REJECTED)

    assert total == 1
    assert pairs == [("翘曲", AI)]


@pytest.mark.asyncio
async def test_status_all_returns_both(async_db_session):
    await _seed(async_db_session)

    pairs, total = await _search(async_db_session)

    assert total == 4
    assert {name for name, _ in pairs} == {"结垢", "表面裂纹", "边裂", "翘曲"}


@pytest.mark.asyncio
async def test_counts_ignore_status_filter(async_db_session):
    await _seed(async_db_session)
    repository = TagConsoleRepositoryImpl(session=async_db_session)

    narrowed = TagConsoleReviewSearchReq(status=TagConsoleReviewStatus.PENDING)
    pending, rejected, approved = await repository.count_review_by_status(narrowed, tenant_id=TENANT_ID, space_ids=None)

    assert pending == 3
    assert rejected == 1, "rejected total must stay real while viewing pending"
    assert approved == 1, "漏水 is the only tag carrying a reviewer"


@pytest.mark.asyncio
async def test_other_filters(async_db_session):
    await _seed(async_db_session)

    _, by_name = await _search(async_db_session, tag_name="裂")
    assert by_name == 2  # 表面裂纹 / 边裂

    _, by_type = await _search(async_db_session, resource_type=MANUAL)
    assert by_type == 1  # 边裂

    _, by_submitter = await _search(async_db_session, submitter_id=BOB)
    assert by_submitter == 2  # 边裂 / 翘曲

    _, by_reviewer = await _search(async_db_session, reviewer_id=CAROL)
    assert by_reviewer == 1  # 翘曲

    _, by_created = await _search(async_db_session, create_time_start=datetime(2026, 8, 6))
    assert by_created == 2  # 结垢(最新 08-06) / 边裂


@pytest.mark.asyncio
async def test_stable_order_and_paging(async_db_session):
    """MAX(create_time) desc, then the pair itself — a total order under GROUP BY."""
    await _seed(async_db_session)

    page1, total = await _search(async_db_session, page=1, page_size=2)
    page2, _ = await _search(async_db_session, page=2, page_size=2)

    assert total == 4
    seen = page1 + page2
    assert len(set(seen)) == 4, "paging repeated or dropped a group"
    # 边裂 08-07 newest; 结垢 takes its newest member 08-06.
    assert seen[0][0] == "边裂"
    assert seen[1][0] == "结垢"


@pytest.mark.asyncio
async def test_department_scope_narrows_rows(async_db_session):
    """Review rows do have per-space provenance, unlike library-mode tags."""
    await _seed(async_db_session)

    _, in_scope = await _search(async_db_session, space_ids={201}, status=TagConsoleReviewStatus.PENDING)
    assert in_scope == 2  # 结垢 (has a row in 201) / 边裂

    _, empty_scope = await _search(async_db_session, space_ids=set())
    assert empty_scope == 0


async def _search_reviewed(session, *, space_ids=None, **overrides):
    repository = TagConsoleRepositoryImpl(session=session)
    req = TagConsoleReviewSearchReq(**overrides)
    return await repository.search_reviewed_tags(req, tenant_id=TENANT_ID, space_ids=space_ids)


@pytest.mark.asyncio
async def test_reviewed_spans_both_tables(async_db_session):
    """Approved history lives in ``tag``, rejected history in ``review_tag``."""
    await _seed(async_db_session)

    refs, total = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED)

    assert total == 2
    assert {(source, name) for source, name, _ in refs} == {(SOURCE_TAG, "漏水"), (SOURCE_REVIEW, "翘曲")}


@pytest.mark.asyncio
async def test_reviewed_orders_by_review_time_across_tables(async_db_session):
    """Rows interleave by review time rather than clumping per source table."""
    await _seed(async_db_session)

    refs, _ = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED)

    assert [name for _, name, _ in refs] == ["漏水", "翘曲"], "08-09 approval outranks the 08-08 rejection"


@pytest.mark.asyncio
async def test_reviewed_paging_is_stable(async_db_session):
    await _seed(async_db_session)

    page1, total = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED, page=1, page_size=1)
    page2, _ = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED, page=2, page_size=1)

    assert total == 2
    assert len({(name, resource_type) for _, name, resource_type in page1 + page2}) == 2


@pytest.mark.asyncio
async def test_approved_only_needs_a_reviewer(async_db_session):
    await _seed(async_db_session)

    refs, total = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.APPROVED)

    assert total == 1
    assert [name for _, name, _ in refs] == ["漏水"]


@pytest.mark.asyncio
async def test_reviewed_honours_the_shared_filters(async_db_session):
    await _seed(async_db_session)

    _, by_reviewer = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED, reviewer_id=CAROL)
    assert by_reviewer == 2  # both were handled by Carol

    _, by_name = await _search_reviewed(async_db_session, status=TagConsoleReviewStatus.REVIEWED, tag_name="漏")
    assert by_name == 1

    _, by_review_time = await _search_reviewed(
        async_db_session,
        status=TagConsoleReviewStatus.REVIEWED,
        review_time_start=datetime(2026, 8, 9),
    )
    assert by_review_time == 1  # only the approval


@pytest.mark.asyncio
async def test_load_group_and_source_files(async_db_session):
    seeded = await _seed(async_db_session)
    repository = TagConsoleRepositoryImpl(session=async_db_session)

    grouped = await repository.load_review_group([("结垢", AI)], tenant_id=TENANT_ID, space_ids=None)
    assert len(grouped[("结垢", AI)]) == 3

    files = await repository.list_review_source_files(
        [row.id for row in seeded["scale"]],
        tenant_id=TENANT_ID,
    )
    assert sorted(file_id for ids in files.values() for file_id in ids) == [500, 501, 502]

    # Rejected links are soft-deleted but must still be listed.
    rejected_files = await repository.list_review_source_files([seeded["rejected"].id], tenant_id=TENANT_ID)
    assert rejected_files[seeded["rejected"].id] == [512]


@pytest.mark.asyncio
async def test_filters_pending_by_source_knowledge_base(async_db_session):
    """标签来源库 over review rows, matched through their file links."""
    await _seed(async_db_session)

    pairs, total = await _search(
        async_db_session,
        status=TagConsoleReviewStatus.PENDING,
        source_knowledge_id=SPACE_PUMP,
    )
    # 结垢 has files in both spaces (500/501 pump, 502 roll); 边裂 sits on 511.
    assert {name for name, _ in pairs} == {"结垢", "边裂"}
    assert total == 2

    pairs, _ = await _search(
        async_db_session,
        status=TagConsoleReviewStatus.PENDING,
        source_knowledge_id=SPACE_ROLL,
    )
    assert {name for name, _ in pairs} == {"结垢", "表面裂纹"}


@pytest.mark.asyncio
async def test_source_knowledge_filter_still_finds_rejected_rows(async_db_session):
    """Rejecting soft-deletes the links, so the filter must not skip them."""
    await _seed(async_db_session)

    pairs, total = await _search(
        async_db_session,
        status=TagConsoleReviewStatus.REJECTED,
        source_knowledge_id=SPACE_PUMP,
    )

    assert total == 1
    assert pairs == [("翘曲", AI)]


@pytest.mark.asyncio
async def test_reviewed_listing_honours_the_source_filter(async_db_session):
    await _seed(async_db_session)

    _, from_pump = await _search_reviewed(
        async_db_session, status=TagConsoleReviewStatus.REVIEWED, source_knowledge_id=SPACE_PUMP
    )
    _, from_roll = await _search_reviewed(
        async_db_session, status=TagConsoleReviewStatus.REVIEWED, source_knowledge_id=SPACE_ROLL
    )

    assert from_pump == 1, "只有已驳回的 翘曲 来自 pump"
    assert from_roll == 1, "已通过的 漏水 来自 roll (file 513)"
