"""Which library an approved tag lands in, and how many rows it leaves behind.

Regression for a defect seen on a live environment: approving one tag produced
**two** rows in `tag` —

- one in the library the reviewer picked, created by registering the name into
  that library, carrying the reviewer as its creator and no audit trail;
- one in the library recorded on the `review_tag` row, carrying the real
  proposer and the audit trail but filed in the wrong place.

The move used to read its target from `review_tag.business_id`, which records
where the tag was *proposed*, not where the reviewer decided it belongs. The
duplicate survived because the "already exists" guard also looked in the
proposing library and so never saw the row in the chosen one.
"""

from datetime import datetime

import pytest
from sqlmodel import select

from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl

TENANT_ID = 1
PROPOSING_LIBRARY = 1  # what review_tag.business_id says
CHOSEN_LIBRARY = 2  # what the reviewer picked
PROPOSER, REVIEWER = 23, 5
MANUAL = TagResourceTypeEnum.MANUAL_TAG.value


def _review_tag(name="66"):
    return ReviewTag(
        name=name,
        # The shape seen in production: the business fields point at a tag
        # library, not at the knowledge space.
        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
        business_id=str(PROPOSING_LIBRARY),
        user_id=PROPOSER,
        tenant_id=TENANT_ID,
        resource_type=MANUAL,
        create_time=datetime(2026, 8, 11, 16, 35),
        update_time=datetime(2026, 8, 11, 16, 35),
    )


def _link(tag_id, resource_id):
    return ReviewTagLink(
        tag_id=tag_id,
        resource_id=str(resource_id),
        resource_type=1,
        user_id=PROPOSER,
        tenant_id=TENANT_ID,
        create_time=datetime(2026, 8, 11, 16, 35),
        update_time=datetime(2026, 8, 11, 16, 35),
    )


def _placeholder_in_chosen_library(name="66"):
    """What registering the name into the chosen library leaves behind.

    Creator is the reviewer and the timestamp is the moment of approval — both
    wrong for the tag itself, which is why the move has to correct them.
    """
    return Tag(
        name=name,
        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
        business_id=str(CHOSEN_LIBRARY),
        user_id=REVIEWER,
        tenant_id=TENANT_ID,
        resource_type=MANUAL,
        create_time=datetime(2026, 8, 11, 16, 40),
        update_time=datetime(2026, 8, 11, 16, 40),
    )


async def _library_tags(session, name="66"):
    return (
        await session.exec(
            select(Tag).where(Tag.name == name, Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value)
        )
    ).all()


@pytest.mark.asyncio
async def test_approval_lands_in_the_chosen_library(async_db_session):
    review_tag = _review_tag()
    async_db_session.add(review_tag)
    async_db_session.add(_placeholder_in_chosen_library())
    await async_db_session.commit()
    async_db_session.add(_link(review_tag.id, 1461))
    await async_db_session.commit()

    repository = TagRepositoryImpl(session=async_db_session)
    await repository.approve_tag_to_move(
        review_tag,
        [_link(review_tag.id, 1461)],
        reviewer_id=REVIEWER,
        review_time=datetime(2026, 8, 11, 16, 40),
        target_library_id=CHOSEN_LIBRARY,
    )
    await async_db_session.commit()

    rows = await _library_tags(async_db_session)
    assert len(rows) == 1, "one approval must not leave two tag rows"
    assert rows[0].business_id == str(CHOSEN_LIBRARY), "must not fall back to the proposing library"


@pytest.mark.asyncio
async def test_approval_corrects_the_placeholder_instead_of_inserting(async_db_session):
    """The row left by the library registration is filled in, not duplicated."""
    review_tag = _review_tag()
    async_db_session.add(review_tag)
    async_db_session.add(_placeholder_in_chosen_library())
    await async_db_session.commit()

    repository = TagRepositoryImpl(session=async_db_session)
    await repository.approve_tag_to_move(
        review_tag,
        [_link(review_tag.id, 1461)],
        reviewer_id=REVIEWER,
        review_time=datetime(2026, 8, 11, 16, 40),
        target_library_id=CHOSEN_LIBRARY,
    )
    await async_db_session.commit()

    row = (await _library_tags(async_db_session))[0]
    assert row.user_id == PROPOSER, "提报者 must stay the proposer, not become the reviewer"
    assert row.create_time == datetime(2026, 8, 11, 16, 35), "创建时间 must stay the submission time"
    assert row.reviewer_id == REVIEWER
    assert row.review_time == datetime(2026, 8, 11, 16, 40)

    links = (await async_db_session.exec(select(TagLink).where(TagLink.tag_id == row.id))).all()
    assert [link.resource_id for link in links] == ["1461"], "the source file must follow the tag"


@pytest.mark.asyncio
async def test_reapproving_the_same_file_does_not_stack_links(async_db_session):
    """Otherwise 已标识知识数 climbs every time the tag is touched again."""
    review_tag = _review_tag()
    async_db_session.add(review_tag)
    await async_db_session.commit()

    repository = TagRepositoryImpl(session=async_db_session)
    for _ in range(2):
        await repository.approve_tag_to_move(
            review_tag,
            [_link(review_tag.id, 1461)],
            reviewer_id=REVIEWER,
            review_time=datetime(2026, 8, 11, 16, 40),
            target_library_id=CHOSEN_LIBRARY,
        )
    await async_db_session.commit()

    row = (await _library_tags(async_db_session))[0]
    links = (await async_db_session.exec(select(TagLink).where(TagLink.tag_id == row.id))).all()
    assert len(links) == 1


@pytest.mark.asyncio
async def test_without_a_chosen_library_the_recorded_one_still_applies(async_db_session):
    """Callers that never pick a library keep the previous behaviour."""
    review_tag = _review_tag()
    async_db_session.add(review_tag)
    await async_db_session.commit()

    repository = TagRepositoryImpl(session=async_db_session)
    await repository.approve_tag_to_move(review_tag, [], reviewer_id=REVIEWER)
    await async_db_session.commit()

    rows = await _library_tags(async_db_session)
    assert [row.business_id for row in rows] == [str(PROPOSING_LIBRARY)]
