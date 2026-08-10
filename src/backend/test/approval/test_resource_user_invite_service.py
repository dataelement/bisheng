from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateResult
from bisheng.approval.domain.services.resource_user_invite_service import ResourceUserInviteService
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError


@asynccontextmanager
async def _lock(_key):
    yield SimpleNamespace(ensure_owned=lambda: None)


def _service(*, scenario=None, duplicate=None):
    scenario_repository = SimpleNamespace(get_scenario_by_code=AsyncMock(return_value=scenario))
    instance_repository = SimpleNamespace(
        find_blocking_invite=AsyncMock(return_value=duplicate),
        list_resource_invites=AsyncMock(return_value=[]),
    )
    gate = SimpleNamespace(
        request_or_pass=AsyncMock(
            return_value=ApprovalGateResult(
                decision=ApprovalGateDecision.PENDING,
                instance_id=41,
                task_ids=[91],
            )
        )
    )
    return (
        ResourceUserInviteService(
            scenario_repository=scenario_repository,
            instance_repository=instance_repository,
            gate=gate,
            lock_factory=_lock,
        ),
        scenario_repository,
        instance_repository,
        gate,
    )


def _kwargs(**overrides):
    values = {
        "tenant_id": 1,
        "resource_type": "knowledge_space",
        "resource_id": "88",
        "resource_name": "docs",
        "inviter_user_id": 7,
        "inviter_user_name": "alice",
        "target_user_id": 9,
        "target_user_name": "bob",
        "relation": "editor",
        "model_id": "model-1",
        "role_snapshot": {"permissions": ["view", "edit"], "name": "编辑者"},
    }
    values.update(overrides)
    return values


async def test_business_key_excludes_inviter():
    service, _, _, gate = _service(scenario=SimpleNamespace(enabled=True))

    await service.request_invite(**_kwargs(inviter_user_id=99))

    request = gate.request_or_pass.await_args.args[0]
    assert request.business_key == "resource-user-invite:knowledge_space:88:user:9"
    assert request.applicant_user_id == 99


async def test_duplicate_returns_first_instance_and_role():
    duplicate = SimpleNamespace(
        id=20,
        status=ApprovalInstanceStatus.PENDING,
        payload_snapshot={"target_user_id": 9, "relation": "viewer", "model_id": "model-0"},
    )
    service, _, _, gate = _service(scenario=SimpleNamespace(enabled=True), duplicate=duplicate)

    result = await service.request_invite(**_kwargs(relation="editor"))

    assert result["outcome"] == "invite_existing"
    assert result["relation"] == "viewer"
    assert result["model_id"] == "model-0"
    gate.request_or_pass.assert_not_awaited()


async def test_duplicate_logs_only_structured_identifiers():
    duplicate = SimpleNamespace(
        id=20,
        status=ApprovalInstanceStatus.PENDING,
        payload_snapshot={"target_user_id": 9, "relation": "viewer", "model_id": "model-0"},
    )
    service, _, _, _ = _service(scenario=SimpleNamespace(enabled=True), duplicate=duplicate)

    with patch("bisheng.approval.domain.services.resource_user_invite_service.logger") as mocked_logger:
        await service.request_invite(**_kwargs())

    mocked_logger.bind.assert_called_once_with(
        tenant_id=1,
        scenario_code="resource_user_invite_confirmation",
        business_key="resource-user-invite:knowledge_space:88:user:9",
        instance_id=20,
        outcome="invite_existing",
    )
    mocked_logger.bind.return_value.info.assert_called_once_with("resource user invite request resolved")


async def test_terminal_invite_allows_new_instance():
    service, _, repository, gate = _service(scenario=SimpleNamespace(enabled=True))

    result = await service.request_invite(**_kwargs())

    assert result["outcome"] == "invite_created"
    repository.find_blocking_invite.assert_awaited_once()
    gate.request_or_pass.assert_awaited_once()


async def test_created_logs_only_structured_identifiers():
    service, _, _, _ = _service(scenario=SimpleNamespace(enabled=True))

    with patch("bisheng.approval.domain.services.resource_user_invite_service.logger") as mocked_logger:
        await service.request_invite(**_kwargs())

    mocked_logger.bind.assert_called_once_with(
        tenant_id=1,
        scenario_code="resource_user_invite_confirmation",
        business_key="resource-user-invite:knowledge_space:88:user:9",
        instance_id=41,
        outcome="invite_created",
    )
    mocked_logger.bind.return_value.info.assert_called_once_with("resource user invite request resolved")


@pytest.mark.parametrize("scenario", [None, SimpleNamespace(enabled=False)])
async def test_missing_or_disabled_scenario_returns_18106_before_side_effect(scenario):
    service, _, repository, gate = _service(scenario=scenario)

    with pytest.raises(ApprovalScenarioDisabledError) as exc:
        await service.request_invite(**_kwargs())

    assert exc.value.code == 18106
    assert exc.value.message == "个人用户邀请确认场景未启用，无法新增个人用户权限"  # noqa: RUF001
    repository.find_blocking_invite.assert_not_awaited()
    gate.request_or_pass.assert_not_awaited()


async def test_role_snapshot_has_stable_fingerprint():
    service, _, _, gate = _service(scenario=SimpleNamespace(enabled=True))

    await service.request_invite(**_kwargs(role_snapshot={"b": 2, "a": 1}))
    first = gate.request_or_pass.await_args.args[0].payload_snapshot["role_fingerprint"]
    gate.request_or_pass.reset_mock()
    await service.request_invite(**_kwargs(role_snapshot={"a": 1, "b": 2}))
    second = gate.request_or_pass.await_args.args[0].payload_snapshot["role_fingerprint"]

    assert first == second


async def test_scenario_guard_keeps_lock_session_open_for_operation():
    events: list[str] = []
    scenario = SimpleNamespace(enabled=True)

    class _Result:
        def first(self):
            return scenario

    class _Session:
        async def exec(self, _statement):
            events.append("select_for_update")
            return _Result()

    @asynccontextmanager
    async def session_context():
        events.append("session_enter")
        yield _Session()
        events.append("session_exit")

    service, _, _, _ = _service(scenario=scenario)
    with patch(
        "bisheng.approval.domain.services.resource_user_invite_service.get_async_db_session",
        side_effect=session_context,
    ):
        async with service.scenario_guard(tenant_id=1):
            events.append("operation")

    assert events == ["session_enter", "select_for_update", "operation", "session_exit"]
