"""Tests for ReviewTagDao.aupdate_resource_tags diff update behavior."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.review_tags import ReviewTagDao, ReviewTagLink


@pytest.mark.asyncio
async def test_aupdate_resource_tags_preserves_existing_links():
    existing_link = ReviewTagLink(
        id=1,
        tag_id=10,
        resource_id="99",
        resource_type=ResourceTypeEnum.SPACE_FILE.value,
        user_id=1,
        tenant_id=1,
        is_deleted=False,
        create_time=datetime(2026, 1, 1, 10, 0, 0),
    )
    session = AsyncMock()
    existing_result = MagicMock()
    existing_result.all.return_value = [existing_link]
    session.exec = AsyncMock(side_effect=[existing_result])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "bisheng.database.models.review_tags.get_async_db_session",
        return_value=mock_ctx,
    ):
        await ReviewTagDao.aupdate_resource_tags(
            [10, 11],
            "99",
            ResourceTypeEnum.SPACE_FILE,
            user_id=1,
            tenant_id=1,
        )

    session.add.assert_called_once()
    added_link = session.add.call_args.args[0]
    assert added_link.tag_id == 11
    assert added_link.create_time is not None
    assert session.exec.await_count == 1
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_aupdate_resource_tags_deletes_orphan_review_tags():
    existing_links = [
        ReviewTagLink(
            id=1,
            tag_id=10,
            resource_id="99",
            resource_type=ResourceTypeEnum.SPACE_FILE.value,
            user_id=1,
            tenant_id=1,
            is_deleted=False,
        ),
        ReviewTagLink(
            id=2,
            tag_id=11,
            resource_id="99",
            resource_type=ResourceTypeEnum.SPACE_FILE.value,
            user_id=1,
            tenant_id=1,
            is_deleted=False,
        ),
    ]
    session = AsyncMock()
    existing_result = MagicMock()
    existing_result.all.return_value = existing_links
    still_linked_result = MagicMock()
    still_linked_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[existing_result, None, still_linked_result, None])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "bisheng.database.models.review_tags.get_async_db_session",
        return_value=mock_ctx,
    ):
        await ReviewTagDao.aupdate_resource_tags(
            [],
            "99",
            ResourceTypeEnum.SPACE_FILE,
            user_id=1,
            tenant_id=1,
        )

    assert session.exec.await_count == 4
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_adelete_orphan_review_tags_deletes_unlinked_rows():
    session = AsyncMock()
    still_linked_result = MagicMock()
    still_linked_result.all.return_value = [102]
    session.exec = AsyncMock(side_effect=[still_linked_result, None])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "bisheng.database.models.review_tags.get_async_db_session",
        return_value=mock_ctx,
    ):
        orphan_ids = await ReviewTagDao.adelete_orphan_review_tags([101, 102])

    assert orphan_ids == [101]
    assert session.exec.await_count == 2
    session.commit.assert_awaited_once()
