"""Tests for review tag approve/reject submitter notifications."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import TagResourceTypeEnum
from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
from bisheng.workstation.domain.services.review_tag_notification_service import (
    ACTION_APPROVED_REVIEW_TAG,
    ACTION_REJECTED_REVIEW_TAG,
    ReviewTagNotificationService,
    ReviewTagSubmitterTarget,
)


@pytest.mark.asyncio
async def test_notify_after_decision_sends_approve_message():
    submitter_targets = [ReviewTagSubmitterTarget(user_id=42, knowledge_space_id=137)]
    send_notify = AsyncMock()

    with (
        patch(
            "bisheng.message.api.dependencies.get_message_service",
            new=AsyncMock(return_value=SimpleNamespace(send_generic_notify=send_notify)),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.get_async_db_session"
        ) as mock_session,
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        await ReviewTagNotificationService.notify_after_decision(
            sender=1,
            sender_user_name="admin",
            tag_name="安全生产",
            status=ApproveOrRejectEnum.APPROVE,
            submitter_targets=submitter_targets,
            fallback_knowledge_id=100,
        )

    send_notify.assert_awaited_once()
    kwargs = send_notify.await_args.kwargs
    assert kwargs["receiver_user_ids"] == [42]
    assert kwargs["action_code"] == ACTION_APPROVED_REVIEW_TAG
    assert kwargs["content_item_list"][1]["content"] == ACTION_APPROVED_REVIEW_TAG


@pytest.mark.asyncio
async def test_notify_after_decision_includes_reject_reason():
    send_notify = AsyncMock()

    with (
        patch(
            "bisheng.message.api.dependencies.get_message_service",
            new=AsyncMock(return_value=SimpleNamespace(send_generic_notify=send_notify)),
        ),
        patch(
            "bisheng.workstation.domain.services.review_tag_notification_service.get_async_db_session"
        ) as mock_session,
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        await ReviewTagNotificationService.notify_after_decision(
            sender=1,
            sender_user_name="admin",
            tag_name="重复标签",
            status=ApproveOrRejectEnum.REJECT,
            submitter_targets=[ReviewTagSubmitterTarget(user_id=7, knowledge_space_id=55)],
            reject_reason="与系统标签重复",
        )

    kwargs = send_notify.await_args.kwargs
    assert kwargs["action_code"] == ACTION_REJECTED_REVIEW_TAG
    tooltip_parts = [item for item in kwargs["content_item_list"] if item.get("type") == "tooltip_text"]
    assert tooltip_parts
    assert "重复" in tooltip_parts[0]["content"]


@pytest.mark.asyncio
async def test_list_submitter_notification_targets_dedupes_and_excludes_reviewer():
    repo = ReviewTagsRepositoryImpl(session=AsyncMock(), tags_repository=AsyncMock())
    tags = [
        SimpleNamespace(id=1, user_id=10, business_id="100"),
        SimpleNamespace(id=2, user_id=20, business_id="200"),
    ]
    links = [SimpleNamespace(tag_id=1, user_id=30)]

    repo.get_review_tag_list_by_tag_name = AsyncMock(return_value=tags)
    repo.get_review_tag_link_list_by_tag_id = AsyncMock(return_value=links)

    targets = await repo.list_submitter_notification_targets(
        "安全生产",
        TagResourceTypeEnum.MANUAL_TAG,
        tenant_id=1,
        exclude_user_id=10,
    )

    assert sorted(targets) == [(20, 200), (30, 100)]
