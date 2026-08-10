from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService
from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
    ApprovalInviteRetryableExecutionError,
)


class FakeOutboxRepo:
    def __init__(self) -> None:
        self.outboxes: dict[int, ApprovalOutbox] = {}
        self.instances: dict[int, ApprovalInstance] = {}
        self.exceptions: list[ApprovalException] = []

    async def get_outbox(self, outbox_id: int) -> ApprovalOutbox | None:
        return self.outboxes.get(outbox_id)

    async def claim_outbox(self, *, outbox_id: int, claim_ttl_seconds: int) -> ApprovalOutbox | None:
        outbox = self.outboxes.get(outbox_id)
        stale = (
            outbox is not None
            and outbox.status == ApprovalOutboxStatus.PROCESSING
            and outbox.update_time is not None
            and outbox.update_time < datetime.utcnow() - timedelta(seconds=claim_ttl_seconds)
        )
        if outbox is None or (
            outbox.status not in (ApprovalOutboxStatus.PENDING, ApprovalOutboxStatus.FAILED) and not stale
        ):
            return None
        outbox.status = ApprovalOutboxStatus.PROCESSING
        self.instances[outbox.instance_id].status = ApprovalInstanceStatus.EXECUTING
        return outbox

    async def release_outbox_claim(self, *, outbox_id: int, claim_ttl_seconds: int, error_summary: str | None) -> bool:
        outbox = self.outboxes[outbox_id]
        if outbox.status != ApprovalOutboxStatus.PROCESSING:
            return False
        outbox.retry_count += 1
        outbox.error_summary = error_summary
        outbox.update_time = datetime.utcnow() - timedelta(seconds=claim_ttl_seconds + 1)
        return True

    async def finalize_outbox_success(self, *, outbox_id: int):
        outbox = self.outboxes[outbox_id]
        instance = self.instances[outbox.instance_id]
        outbox.status = ApprovalOutboxStatus.SUCCESS
        outbox.error_summary = None
        instance.status = ApprovalInstanceStatus.EXECUTED
        return outbox, instance

    async def finalize_outbox_failure(self, *, outbox_id: int, error_summary: str | None):
        outbox = self.outboxes[outbox_id]
        instance = self.instances[outbox.instance_id]
        outbox.status = ApprovalOutboxStatus.FAILED
        outbox.retry_count += 1
        outbox.error_summary = error_summary
        instance.status = ApprovalInstanceStatus.EXECUTE_FAILED
        self.exceptions.append(
            ApprovalException(
                tenant_id=instance.tenant_id,
                instance_id=instance.id,
                exception_type="execute_failed",
                detail={"error_summary": error_summary},
            )
        )
        return outbox, instance

    async def update_outbox(self, outbox: ApprovalOutbox) -> ApprovalOutbox:
        self.outboxes[outbox.id] = outbox
        return outbox

    async def get_instance(self, instance_id: int) -> ApprovalInstance | None:
        return self.instances.get(instance_id)

    async def update_instance(self, instance: ApprovalInstance) -> ApprovalInstance:
        self.instances[instance.id] = instance
        return instance

    async def create_exception(self, exception: ApprovalException) -> ApprovalException:
        self.exceptions.append(exception)
        return exception


def _instance() -> ApprovalInstance:
    return ApprovalInstance(
        id=1,
        tenant_id=1,
        scenario_code="menu_access_request",
        scenario_name="菜单权限申请",
        handler_key="menu_access_request",
        business_key="menu:model:user:7",
        business_resource_type="web_menu",
        business_resource_id="model",
        business_name="模型管理",
        applicant_user_id=7,
        applicant_user_name="alice",
        status=ApprovalInstanceStatus.APPROVED,
        payload_snapshot={"menu_key": "model"},
        detail_snapshot={"menu_name": "模型管理"},
    )


def _outbox() -> ApprovalOutbox:
    return ApprovalOutbox(
        id=1,
        tenant_id=1,
        instance_id=1,
        handler_key="menu_access_request",
        status=ApprovalOutboxStatus.PENDING,
        retry_count=0,
        payload_snapshot={"menu_key": "model"},
    )


async def test_execute_outbox_marks_success():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(outbox_id=1, executor=lambda outbox: (True, None))

    assert result is True
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTED
    assert repo.exceptions == []


async def test_execute_outbox_marks_failed_and_creates_exception():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(outbox_id=1, executor=lambda outbox: (False, "boom"))

    assert result is False
    assert repo.outboxes[1].status == ApprovalOutboxStatus.FAILED
    assert repo.outboxes[1].retry_count == 1
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert repo.exceptions[0].detail["error_summary"] == "boom"


async def test_retry_outbox_resets_pending_before_reexecute():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    failed_outbox = _outbox()
    failed_outbox.status = ApprovalOutboxStatus.FAILED
    failed_outbox.retry_count = 1
    repo.outboxes[1] = failed_outbox
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.retry_outbox(outbox_id=1, executor=lambda outbox: (True, None))

    assert result is True
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS


async def test_execute_outbox_supports_async_executor():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    async def executor(outbox):
        return True, None

    result = await service.execute_outbox(outbox_id=1, executor=executor)

    assert result is True
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS


async def test_duplicate_success_is_idempotent():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    repo.outboxes[1].status = ApprovalOutboxStatus.SUCCESS
    repo.instances[1].status = ApprovalInstanceStatus.EXECUTED
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(outbox_id=1, executor=lambda outbox: (_ for _ in ()).throw(AssertionError()))

    assert result is True


async def test_success_outbox_repairs_executing_instance_without_rerunning_handler():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.instances[1].status = ApprovalInstanceStatus.EXECUTING
    repo.outboxes[1] = _outbox()
    repo.outboxes[1].status = ApprovalOutboxStatus.SUCCESS
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(
        outbox_id=1,
        executor=lambda _outbox: (_ for _ in ()).throw(AssertionError("must not rerun")),
    )

    assert result is True
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTED


async def test_retryable_releases_claim_for_immediate_retry():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    def retryable(_outbox):
        raise ApprovalInviteRetryableExecutionError("compensation is uncertain")

    import pytest

    with pytest.raises(ApprovalInviteRetryableExecutionError):
        await service.execute_outbox(outbox_id=1, executor=retryable)

    assert repo.outboxes[1].status == ApprovalOutboxStatus.PROCESSING
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTING
    assert await service.execute_outbox(outbox_id=1, executor=lambda _outbox: (True, None)) is True


async def test_invite_success_notification_failure_keeps_success_terminal():
    repo = FakeOutboxRepo()
    instance = _instance()
    instance.scenario_code = "resource_user_invite_confirmation"
    instance.payload_snapshot = {"target_user_id": 9}
    repo.instances[1] = instance
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    with patch(
        "bisheng.approval.domain.services.approval_notification_service.ApprovalNotificationService.notify_user",
        new=AsyncMock(side_effect=RuntimeError("message unavailable")),
    ):
        result = await service.execute_outbox(outbox_id=1, executor=lambda _outbox: (True, None))

    assert result is True
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTED


async def test_invite_failure_notification_failure_keeps_failed_terminal():
    repo = FakeOutboxRepo()
    instance = _instance()
    instance.scenario_code = "resource_user_invite_confirmation"
    instance.payload_snapshot = {"target_user_id": 9}
    repo.instances[1] = instance
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    with (
        patch(
            "bisheng.approval.domain.services.approval_notification_service.ApprovalNotificationService.notify_admins",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.approval.domain.services.approval_notification_service.ApprovalNotificationService.notify_user",
            new=AsyncMock(side_effect=RuntimeError("message unavailable")),
        ),
    ):
        result = await service.execute_outbox(outbox_id=1, executor=lambda _outbox: (False, "grant failed"))

    assert result is False
    assert repo.outboxes[1].status == ApprovalOutboxStatus.FAILED
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTE_FAILED
