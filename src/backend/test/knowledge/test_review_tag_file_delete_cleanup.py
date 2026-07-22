"""Tests for ReviewTagDao.acleanup_for_deleted_space_files."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.database.models.review_tags import ReviewTagDao


@pytest.mark.asyncio
async def test_cleanup_for_deleted_space_files_noop_on_empty_ids():
    with patch("bisheng.database.models.review_tags.get_async_db_session") as mock_session_ctx:
        await ReviewTagDao.acleanup_for_deleted_space_files([])
    mock_session_ctx.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_for_deleted_space_files_deletes_orphan_tags_only():
    session = AsyncMock()
    affected_result = MagicMock()
    affected_result.all.return_value = [101, 102]
    still_linked_result = MagicMock()
    still_linked_result.all.return_value = [102]
    session.exec = AsyncMock(side_effect=[affected_result, None, still_linked_result, None])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "bisheng.database.models.review_tags.get_async_db_session",
        return_value=mock_ctx,
    ):
        await ReviewTagDao.acleanup_for_deleted_space_files([11, 12])

    assert session.exec.await_count == 4
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_for_deleted_space_files_skips_tag_delete_when_no_links_removed():
    session = AsyncMock()
    affected_result = MagicMock()
    affected_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[affected_result, None])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "bisheng.database.models.review_tags.get_async_db_session",
        return_value=mock_ctx,
    ):
        await ReviewTagDao.acleanup_for_deleted_space_files([99])

    assert session.exec.await_count == 2
    session.commit.assert_awaited_once()
