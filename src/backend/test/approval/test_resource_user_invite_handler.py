from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
    ApprovalInviteRetryableExecutionError,
    ResourceUserInviteScenarioHandler,
)
from bisheng.approval.domain.services.resource_user_invite_service import ResourceUserInviteService
from bisheng.common.errcode.approval import ApprovalRequestAlreadyProcessedError
from bisheng.core.lock.token_safe_redis_lock import RedisLockBusyError


def _payload(**overrides):
    role, fingerprint = ResourceUserInviteService.normalize_role_snapshot({"id": "model-1", "permissions": ["view"]})
    values = {
        "schema_version": 1,
        "tenant_id": 1,
        "resource_type": "knowledge_space",
        "resource_id": "88",
        "resource_name": "docs",
        "inviter_user_id": 7,
        "target_user_id": 9,
        "target_user_name": "bob",
        "relation": "viewer",
        "model_id": "model-1",
        "include_children": False,
        "role_snapshot": role,
        "role_fingerprint": fingerprint,
    }
    values.update(overrides)
    return values


async def test_resolve_only_target_user():
    handler = ResourceUserInviteScenarioHandler(instance_repository=SimpleNamespace())
    req = SimpleNamespace(payload_snapshot=_payload())

    assert await handler.resolve_approvers({"sources": [{"type": "invited_user"}]}, req) == [9]
    assert await handler.resolve_approvers({"sources": [{"type": "direct_user", "user_ids": [7]}]}, req) == []


async def test_execute_requires_target_approved_task():
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.APPROVED, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.PENDING)]),
        find_blocking_invite=AsyncMock(return_value=None),
    )
    handler = ResourceUserInviteScenarioHandler(instance_repository=repository, knowledge_grant=AsyncMock())

    with pytest.raises(ApprovalRequestAlreadyProcessedError):
        await handler.on_approved(1, _payload())


async def test_role_fingerprint_must_match():
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.APPROVED, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.APPROVED)]),
        find_blocking_invite=AsyncMock(return_value=None),
    )
    handler = ResourceUserInviteScenarioHandler(instance_repository=repository, knowledge_grant=AsyncMock())

    with pytest.raises(ValueError, match="fingerprint"):
        await handler.on_approved(1, _payload(role_fingerprint="tampered"))


@pytest.mark.parametrize("resource_type", ["knowledge_space", "channel"])
async def test_dispatches_to_resource_owner_service(resource_type):
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.APPROVED, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.APPROVED)]),
        find_blocking_invite=AsyncMock(return_value=None),
    )
    knowledge_grant = AsyncMock(return_value={"status": "applied"})
    channel_grant = AsyncMock(return_value={"status": "applied"})
    handler = ResourceUserInviteScenarioHandler(
        instance_repository=repository,
        knowledge_grant=knowledge_grant,
        channel_grant=channel_grant,
    )

    await handler.on_approved(1, _payload(resource_type=resource_type))

    expected = knowledge_grant if resource_type == "knowledge_space" else channel_grant
    expected.assert_awaited_once()


async def test_success_logs_execution_identifiers_and_validation_stages():
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.APPROVED, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.APPROVED)]),
        find_blocking_invite=AsyncMock(return_value=None),
    )
    handler = ResourceUserInviteScenarioHandler(instance_repository=repository, knowledge_grant=AsyncMock())

    with patch("bisheng.approval.domain.services.resource_user_invite_scenario_handler.logger") as mocked_logger:
        await handler.on_approved(1, _payload())

    mocked_logger.bind.assert_called_once_with(
        instance_id=1,
        resource_type="knowledge_space",
        resource_id="88",
        target_user_id=9,
    )
    execution_logger = mocked_logger.bind.return_value
    assert execution_logger.bind.call_args_list == [
        call(validation_stage="instance_and_task"),
        call(validation_stage="grant_applied", compensation_result="not_required"),
    ]
    execution_logger.bind.return_value.info.assert_any_call("resource user invite execution started")
    execution_logger.bind.return_value.info.assert_any_call("resource user invite execution succeeded")


async def test_newer_invite_blocks_old_retry():
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.EXECUTING, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.APPROVED)]),
        find_blocking_invite=AsyncMock(return_value=SimpleNamespace(id=2)),
    )
    handler = ResourceUserInviteScenarioHandler(instance_repository=repository, knowledge_grant=AsyncMock())

    with pytest.raises(ApprovalRequestAlreadyProcessedError):
        await handler.on_approved(1, _payload())


async def test_binding_lock_contention_is_retryable():
    repository = SimpleNamespace(
        get_instance=AsyncMock(
            return_value=SimpleNamespace(id=1, status=ApprovalInstanceStatus.EXECUTING, business_key="key")
        ),
        list_tasks=AsyncMock(return_value=[SimpleNamespace(approver_user_id=9, status=ApprovalTaskStatus.APPROVED)]),
        find_blocking_invite=AsyncMock(return_value=None),
    )
    command = AsyncMock(side_effect=RedisLockBusyError("busy"))
    handler = ResourceUserInviteScenarioHandler(instance_repository=repository, knowledge_grant=command)

    with pytest.raises(ApprovalInviteRetryableExecutionError):
        await handler.on_approved(1, _payload())
