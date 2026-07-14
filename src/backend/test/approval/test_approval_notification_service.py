from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.approval.domain.models.approval_notification_outbox import (
    ApprovalNotificationEventType,
    ApprovalNotificationOutbox,
    ApprovalNotificationOutboxStatus,
)
from bisheng.approval.domain.services.approval_notification_service import (
    ApprovalNotificationService,
)


def _notification_outbox(*, status=ApprovalNotificationOutboxStatus.PENDING, retry_count=0):
    return ApprovalNotificationOutbox(
        id=1,
        tenant_id=7,
        instance_id=101,
        event_type=ApprovalNotificationEventType.FILE_PUBLISH_SUBMITTED,
        status=status,
        retry_count=retry_count,
        max_retries=3,
        payload_snapshot={
            "task_ids": [201, 202, 203],
            "applicant_user_id": 11,
            "applicant_user_name": "申请人",
            "action_code": "request_knowledge_space_file_publish",
            "business_type": "approval_instance_id",
            "business_id": "101",
            "business_name": "发布文件：制度.pdf",  # noqa: RUF001
            "button_action_code": "request_knowledge_space_file_publish",
        },
    )


@pytest.mark.asyncio
async def test_consume_sends_original_approval_message_and_marks_success():
    outbox = _notification_outbox()
    outbox_repository = SimpleNamespace(
        get=AsyncMock(return_value=outbox),
        mark_success=AsyncMock(return_value=outbox),
        mark_failed=AsyncMock(),
    )
    instance_repository = SimpleNamespace(
        get_tasks_by_ids=AsyncMock(
            return_value=[
                SimpleNamespace(id=201, approver_user_id=31),
                SimpleNamespace(id=202, approver_user_id=32),
                SimpleNamespace(id=203, approver_user_id=31),
            ]
        )
    )
    message_service = SimpleNamespace(send_generic_approval=AsyncMock(return_value=SimpleNamespace(id=99)))
    service = ApprovalNotificationService(
        outbox_repository=outbox_repository,
        instance_repository=instance_repository,
        message_service=message_service,
    )

    assert await service.consume(1) is True

    message_service.send_generic_approval.assert_awaited_once_with(
        applicant_user_id=11,
        applicant_user_name="申请人",
        action_code="request_knowledge_space_file_publish",
        business_type="approval_instance_id",
        business_id="101",
        business_name="发布文件：制度.pdf",  # noqa: RUF001
        button_action_code="request_knowledge_space_file_publish",
        receiver_user_ids=[31, 32],
    )
    outbox_repository.mark_success.assert_awaited_once_with(1)
    outbox_repository.mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_consume_success_outbox_short_circuits():
    outbox_repository = SimpleNamespace(
        get=AsyncMock(return_value=_notification_outbox(status=ApprovalNotificationOutboxStatus.SUCCESS)),
        mark_success=AsyncMock(),
        mark_failed=AsyncMock(),
    )
    message_service = SimpleNamespace(send_generic_approval=AsyncMock())
    service = ApprovalNotificationService(
        outbox_repository=outbox_repository,
        instance_repository=SimpleNamespace(get_tasks_by_ids=AsyncMock()),
        message_service=message_service,
    )

    assert await service.consume(1) is True
    message_service.send_generic_approval.assert_not_called()


@pytest.mark.asyncio
async def test_consume_failure_records_retry_and_propagates():
    outbox_repository = SimpleNamespace(
        get=AsyncMock(return_value=_notification_outbox()),
        mark_success=AsyncMock(),
        mark_failed=AsyncMock(),
    )
    message_service = SimpleNamespace(
        send_generic_approval=AsyncMock(side_effect=RuntimeError("message database unavailable"))
    )
    service = ApprovalNotificationService(
        outbox_repository=outbox_repository,
        instance_repository=SimpleNamespace(
            get_tasks_by_ids=AsyncMock(return_value=[SimpleNamespace(id=201, approver_user_id=31)])
        ),
        message_service=message_service,
    )

    with pytest.raises(RuntimeError, match="message database unavailable"):
        await service.consume(1)

    outbox_repository.mark_failed.assert_awaited_once_with(1, "message database unavailable")
    outbox_repository.mark_success.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_records_dispatch_failure_for_beat_compensation():
    outbox = _notification_outbox()
    outbox_repository = SimpleNamespace(
        create_or_get=AsyncMock(return_value=outbox),
        mark_failed=AsyncMock(),
    )
    dispatcher = Mock(side_effect=RuntimeError("broker unavailable"))
    service = ApprovalNotificationService(
        outbox_repository=outbox_repository,
        instance_repository=SimpleNamespace(),
        dispatcher=dispatcher,
    )

    saved = await service.enqueue_file_publish(
        tenant_id=7,
        instance_id=101,
        task_ids=[201, 202],
        applicant_user_id=11,
        applicant_user_name="申请人",
        business_name="发布文件：制度.pdf",  # noqa: RUF001
    )

    assert saved.id == 1
    dispatcher.assert_called_once_with(1, 7)
    outbox_repository.mark_failed.assert_awaited_once_with(1, "broker unavailable")
