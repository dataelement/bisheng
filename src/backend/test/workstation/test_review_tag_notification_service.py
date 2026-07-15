"""Tests for review tag approve/reject submitter notifications."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.database.models.tag import TagBusinessTypeEnum, TagResourceTypeEnum
from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagSubmitterTarget
from bisheng.workstation.domain.services.review_tag_notification_service import (
    ACTION_APPROVED_REVIEW_TAG,
    ACTION_REJECTED_REVIEW_TAG,
    ReviewTagNotificationService,
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
async def test_notify_after_decision_uses_file_metadata_when_available():
    submitter_targets = [
        ReviewTagSubmitterTarget(
            user_id=42,
            knowledge_space_id=214,
            file_id=501,
            file_name="report.pdf",
            file_type="pdf",
        )
    ]
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
            tag_name="测试哈哈哈",
            status=ApproveOrRejectEnum.APPROVE,
            submitter_targets=submitter_targets,
            fallback_knowledge_id=214,
        )

    business_url = next(item for item in send_notify.await_args.kwargs["content_item_list"] if item["type"] == "target")
    assert business_url["content"] == "「测试哈哈哈」"
    assert "business_type" not in (business_url.get("metadata") or {})


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
            submitter_targets=[
                ReviewTagSubmitterTarget(
                    user_id=7,
                    knowledge_space_id=55,
                    file_id=88,
                    file_name="notes.docx",
                    file_type="docx",
                )
            ],
            reject_reason="与系统标签重复",
        )

    kwargs = send_notify.await_args.kwargs
    assert kwargs["action_code"] == ACTION_REJECTED_REVIEW_TAG
    tooltip_parts = [item for item in kwargs["content_item_list"] if item.get("type") == "tooltip_text"]
    assert tooltip_parts
    assert "重复" in tooltip_parts[0]["content"]
    target_part = next(item for item in kwargs["content_item_list"] if item["type"] == "target")
    assert target_part["content"] == "「重复标签」"


@pytest.mark.asyncio
async def test_list_submitter_notification_targets_dedupes_and_excludes_reviewer():
    repo = ReviewTagsRepositoryImpl(session=AsyncMock(), tags_repository=AsyncMock())
    tags = [
        SimpleNamespace(
            id=1,
            user_id=10,
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
            business_id="100",
        ),
        SimpleNamespace(
            id=2,
            user_id=20,
            business_type=TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
            business_id="200",
        ),
    ]
    links = [SimpleNamespace(tag_id=1, user_id=30, resource_id="900")]

    async def _links_for_tags(tag_ids, tenant_id):
        return [link for link in links if link.tag_id in tag_ids]

    repo.get_review_tag_list_by_tag_name = AsyncMock(return_value=tags)
    repo.get_review_tag_link_list_by_tag_id = AsyncMock(side_effect=_links_for_tags)
    repo.tags_repository.get_knowledgefile_by_resource_id = AsyncMock(
        return_value=SimpleNamespace(id=900, knowledge_id=100, file_name="a.pdf", file_type="pdf")
    )

    targets = await repo.list_submitter_notification_targets(
        "安全生产",
        TagResourceTypeEnum.MANUAL_TAG,
        tenant_id=1,
        exclude_user_id=10,
    )

    assert targets == [
        ReviewTagSubmitterTarget(user_id=20, knowledge_space_id=200),
        ReviewTagSubmitterTarget(
            user_id=30,
            knowledge_space_id=100,
            file_id=900,
            file_name="a.pdf",
            file_type="pdf",
        ),
    ]


@pytest.mark.asyncio
async def test_list_submitter_notification_targets_resolves_file_from_tag_library_tag():
    repo = ReviewTagsRepositoryImpl(session=AsyncMock(), tags_repository=AsyncMock())
    tags = [
        SimpleNamespace(
            id=1,
            user_id=10,
            business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
            business_id="1",
        ),
    ]
    links = [SimpleNamespace(tag_id=1, user_id=10, resource_id="501")]

    repo.get_review_tag_list_by_tag_name = AsyncMock(return_value=tags)
    repo.get_review_tag_link_list_by_tag_id = AsyncMock(return_value=links)
    repo.tags_repository.get_knowledgefile_by_resource_id = AsyncMock(
        return_value=SimpleNamespace(id=501, knowledge_id=214, file_name="doc.pdf", file_type="pdf")
    )

    targets = await repo.list_submitter_notification_targets(
        "测试哈哈哈",
        TagResourceTypeEnum.MANUAL_TAG,
        tenant_id=1,
    )

    assert targets == [
        ReviewTagSubmitterTarget(
            user_id=10,
            knowledge_space_id=214,
            file_id=501,
            file_name="doc.pdf",
            file_type="pdf",
        )
    ]
