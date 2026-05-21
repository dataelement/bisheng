from __future__ import annotations

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalOutbox,
    ApprovalOutboxStatus,
)
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService


class FakeOutboxRepo:
    def __init__(self) -> None:
        self.outboxes: dict[int, ApprovalOutbox] = {}
        self.instances: dict[int, ApprovalInstance] = {}
        self.exceptions: list[ApprovalException] = []

    async def get_outbox(self, outbox_id: int) -> ApprovalOutbox | None:
        return self.outboxes.get(outbox_id)

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
        scenario_code='menu_access_request',
        scenario_name='菜单权限申请',
        handler_key='menu_access_request',
        business_key='menu:model:user:7',
        business_resource_type='web_menu',
        business_resource_id='model',
        business_name='模型管理',
        applicant_user_id=7,
        applicant_user_name='alice',
        status=ApprovalInstanceStatus.APPROVED,
        payload_snapshot={'menu_key': 'model'},
        detail_snapshot={'menu_name': '模型管理'},
    )


def _outbox() -> ApprovalOutbox:
    return ApprovalOutbox(
        id=1,
        tenant_id=1,
        instance_id=1,
        handler_key='menu_access_request',
        status=ApprovalOutboxStatus.PENDING,
        retry_count=0,
        payload_snapshot={'menu_key': 'model'},
    )


async def test_execute_outbox_marks_success():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(outbox_id=1, executor=lambda outbox: (True, None))

    assert result is True
    assert repo.outboxes[1].status == ApprovalOutboxStatus.SUCCESS
    assert repo.exceptions == []


async def test_execute_outbox_marks_failed_and_creates_exception():
    repo = FakeOutboxRepo()
    repo.instances[1] = _instance()
    repo.outboxes[1] = _outbox()
    service = ApprovalOutboxService(instance_repository=repo)

    result = await service.execute_outbox(outbox_id=1, executor=lambda outbox: (False, 'boom'))

    assert result is False
    assert repo.outboxes[1].status == ApprovalOutboxStatus.FAILED
    assert repo.outboxes[1].retry_count == 1
    assert repo.instances[1].status == ApprovalInstanceStatus.EXECUTE_FAILED
    assert repo.exceptions[0].detail['error_summary'] == 'boom'


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
