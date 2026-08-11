from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.approval.domain.services.approval_uow import build_post_commit_effect
from bisheng.common.errcode.approval import ApprovalRequestPermissionDeniedError
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)

SCENARIO = "knowledge_space_file_change_request"


@dataclass
class _User:
    user_id: int
    tenant_id: int = 42
    admin: bool = False

    def is_admin(self) -> bool:
        return self.admin


def _instance(*, applicant_user_id: int = 7) -> ApprovalInstance:
    return ApprovalInstance(
        id=101,
        tenant_id=42,
        scenario_code=SCENARIO,
        scenario_name="知识空间文件变更",
        handler_key=SCENARIO,
        business_key="knowledge-space-change:81",
        business_resource_type="knowledge_space_file_change",
        business_resource_id="81",
        business_name="report.pdf",
        applicant_user_id=applicant_user_id,
        applicant_user_name="applicant",
        flow_version_id=5,
        status=ApprovalInstanceStatus.PENDING,
        current_node_name="空间管理员审核",
        payload_snapshot={"request_id": 81, "space_id": 8},
        detail_snapshot={"action": "rename"},
    )


def _task(*, approver_user_id: int = 9, status: str = ApprovalTaskStatus.PENDING) -> ApprovalTask:
    return ApprovalTask(
        id=201,
        tenant_id=42,
        instance_id=101,
        flow_version_id=5,
        node_code="space_owner_manager_review",
        node_name="空间管理员审核",
        node_order=1,
        approver_user_id=approver_user_id,
        approver_source_type="dynamic_reconciled",
        node_mode="or",
        status=status,
    )


async def test_f046_runtime_factory_exposes_all_optional_hooks():
    handler = await build_runtime_handler(SCENARIO)

    for hook in (
        "discover_candidate_instances",
        "reconcile_pending_approvers",
        "authorize_view",
        "filter_visible_instances",
        "authorize_decision",
        "validate_decision",
        "get_business_status_projection",
        "exception_action_policy",
    ):
        assert callable(getattr(handler, hook))
    approver_empty = ApprovalException(exception_type="approver_empty")
    execute_failed = ApprovalException(exception_type="execute_failed")
    assert await handler.exception_action_policy(action="retry", exception=approver_empty) is True
    assert await handler.exception_action_policy(action="retry", exception=execute_failed) is True
    assert await handler.exception_action_policy(action="cancel") is True
    assert await handler.exception_action_policy(action="skip_node") is False


async def test_list_count_and_unread_discover_and_reconcile_before_query(monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []
    effect = build_post_commit_effect("notify", lambda: events.append("effect"))
    handler = SimpleNamespace(
        discover_candidate_instances=AsyncMock(return_value=[101]),
        reconcile_candidate_instance=AsyncMock(
            return_value=SimpleNamespace(post_commit_effects=(effect,)),
        ),
        filter_visible_instances=AsyncMock(side_effect=lambda *, instances, **_: instances),
    )

    async def build(_scenario_code: str):
        return handler

    query = AsyncMock(side_effect=lambda *_: events.append("query") or [_task(approver_user_id=77)])
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        build,
        raising=False,
    )
    monkeypatch.setattr(ApprovalQueryRepository, "list_tasks_by_approver", query)
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instances_by_ids", AsyncMock(return_value=[_instance()]))
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.user_menu_access_repository.UserMenuAccessRepository.get_revoked_instance_ids",
        AsyncMock(return_value=set()),
    )

    listed = await ApprovalCenterService.list_my_tasks(tenant_id=42, approver_user_id=77)
    counted = await ApprovalCenterService.count_pending_tasks(tenant_id=42, approver_user_id=77)
    unread = await ApprovalCenterService.count_unread_tasks(tenant_id=42, approver_user_id=77)

    assert listed["total"] == counted == unread == 1
    assert events.index("effect") < events.index("query")
    assert handler.discover_candidate_instances.await_count == 3
    assert all(
        call.kwargs["limit"] <= ApprovalCenterService.DYNAMIC_DISCOVERY_LIMIT
        for call in handler.discover_candidate_instances.await_args_list
    )
    assert handler.reconcile_candidate_instance.await_count == 3


async def test_dynamic_discovery_advances_cursor_across_two_batches(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []

    async def discover(**kwargs):
        calls.append(kwargs["after_instance_id"])
        if kwargs["after_instance_id"] == 0:
            return [101, 102]
        if kwargs["after_instance_id"] == 102:
            return [103]
        return []

    handler = SimpleNamespace(
        discover_candidate_instances=AsyncMock(side_effect=discover),
        reconcile_candidate_instance=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        AsyncMock(return_value=handler),
    )
    monkeypatch.setattr(ApprovalCenterService, "DYNAMIC_DISCOVERY_LIMIT", 2)

    await ApprovalCenterService._prepare_dynamic_tasks(
        tenant_id=42,
        approver_user_id=9,
        trigger="approval_center_query",
    )

    assert calls == [0, 102]
    assert [call.kwargs["instance_id"] for call in handler.reconcile_candidate_instance.await_args_list] == [
        101,
        102,
        103,
    ]


async def test_dynamic_discovery_restarts_at_zero_without_starving_later_instances(
    monkeypatch: pytest.MonkeyPatch,
):
    remaining = [101, 102, 103]
    after_values: list[int] = []

    async def discover(**kwargs):
        after_values.append(kwargs["after_instance_id"])
        return [instance_id for instance_id in remaining if instance_id > kwargs["after_instance_id"]][
            : kwargs["limit"]
        ]

    async def reconcile(*, instance_id: int, **_kwargs):
        remaining.remove(instance_id)

    handler = SimpleNamespace(
        discover_candidate_instances=AsyncMock(side_effect=discover),
        reconcile_candidate_instance=AsyncMock(side_effect=reconcile),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        AsyncMock(return_value=handler),
    )
    monkeypatch.setattr(ApprovalCenterService, "DYNAMIC_DISCOVERY_LIMIT", 2)
    monkeypatch.setattr(ApprovalCenterService, "DYNAMIC_DISCOVERY_MAX_BATCHES", 1)

    await ApprovalCenterService._prepare_dynamic_tasks(
        tenant_id=42,
        approver_user_id=9,
        trigger="first_worker",
    )
    await ApprovalCenterService._prepare_dynamic_tasks(
        tenant_id=42,
        approver_user_id=9,
        trigger="second_worker_or_restart",
    )

    assert after_values == [0, 0]
    assert remaining == []


def test_candidate_query_excludes_viewer_who_already_has_pending_task():
    statement = KnowledgeSpaceFileChangeRequestRepository.build_reconcilable_instance_statement(
        tenant_id=42,
        space_ids=[8],
        after_instance_id=0,
        limit=100,
        missing_pending_approver_user_id=9,
    )
    sql = str(statement)

    assert "approval_task" in sql
    assert "NOT (EXISTS" in sql
    assert "approval_task.approver_user_id" in sql
    assert "approval_task.status" in sql


async def test_visibility_resolves_same_space_strictly_once(monkeypatch: pytest.MonkeyPatch):
    handler = await build_runtime_handler(SCENARIO)
    first = _instance()
    second = first.model_copy(update={"id": 102, "business_key": "knowledge-space-change:82"})
    managed = AsyncMock(return_value=[8])
    strict_resolve = AsyncMock(return_value=[9])
    monkeypatch.setattr(type(handler), "_current_managed_space_ids", managed)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver."
        "KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids",
        strict_resolve,
    )

    visible = await handler.filter_visible_instances(
        instances=[first, second],
        viewer_user_id=9,
        tenant_id=42,
    )

    assert [instance.id for instance in visible] == [101, 102]
    managed.assert_awaited_once()
    strict_resolve.assert_awaited_once_with(
        tenant_id=42,
        space_id=8,
        applicant_user_id=None,
    )


async def test_former_cancelled_task_does_not_grant_list_or_detail_visibility(monkeypatch: pytest.MonkeyPatch):
    instance = _instance()
    former_task = _task(approver_user_id=9, status=ApprovalTaskStatus.CANCELLED)
    handler = SimpleNamespace(
        discover_candidate_instances=AsyncMock(return_value=[]),
        filter_visible_instances=AsyncMock(return_value=[]),
        authorize_view=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        AsyncMock(return_value=handler),
        raising=False,
    )
    monkeypatch.setattr(ApprovalQueryRepository, "list_tasks_by_approver", AsyncMock(return_value=[former_task]))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instances_by_ids", AsyncMock(return_value=[instance]))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_task", AsyncMock(return_value=former_task))
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))

    listed = await ApprovalCenterService.list_my_tasks(tenant_id=42, approver_user_id=9)
    assert listed == {"data": [], "total": 0}
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await ApprovalCenterService.get_task_detail(task_id=former_task.id, login_user=_User(9, admin=True))
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await ApprovalCenterService.get_instance_detail(instance_id=instance.id, login_user=_User(9, admin=True))


async def test_applicant_keeps_detail_visibility(monkeypatch: pytest.MonkeyPatch):
    instance = _instance(applicant_user_id=7)
    handler = SimpleNamespace(authorize_view=AsyncMock(return_value=True))
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        AsyncMock(return_value=handler),
        raising=False,
    )
    monkeypatch.setattr(ApprovalInstanceRepository, "get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(ApprovalInstanceRepository, "list_tasks", AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalInstanceRepository, "list_action_logs", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_scenario_repository.ApprovalScenarioRepository.list_node_definitions",
        AsyncMock(return_value=[]),
    )

    detail = await ApprovalCenterService.get_instance_detail(instance_id=101, login_user=_User(7))

    assert detail["instance_id"] == 101
    handler.authorize_view.assert_awaited_once()


async def test_decision_reconcile_effects_are_merged_and_strict_authorization_is_final(
    monkeypatch: pytest.MonkeyPatch,
):
    events: list[str] = []
    effect = build_post_commit_effect("reconcile-notify", lambda: events.append("post-commit"))
    handler = SimpleNamespace(
        reconcile_pending_approvers=AsyncMock(
            return_value=SimpleNamespace(post_commit_effects=(effect,)),
        ),
        authorize_decision=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.build_runtime_handler",
        AsyncMock(return_value=handler),
        raising=False,
    )

    effects = await ApprovalCenterService._reconcile_pending_approvers_locked(
        session=object(),
        instance=_instance(),
        trigger="decision",
    )
    assert effects == (effect,)
    with pytest.raises(ApprovalRequestPermissionDeniedError):
        await ApprovalCenterService._authorize_decision(
            handler=handler,
            instance=_instance(),
            operator_user_id=9,
        )
    assert events == []


async def test_f046_exception_policy_blocks_bypass_actions_before_write(monkeypatch: pytest.MonkeyPatch):
    exception = ApprovalException(id=301, tenant_id=42, instance_id=101, exception_type="approver_empty")
    instance = _instance()
    monkeypatch.setattr(ApprovalExceptionService, "_get_exception", AsyncMock(return_value=exception))
    monkeypatch.setattr(ApprovalExceptionService, "_get_instance", AsyncMock(return_value=instance))
    forbidden_write = AsyncMock()
    monkeypatch.setattr(ApprovalExceptionService, "assign_approvers", forbidden_write)
    monkeypatch.setattr(ApprovalExceptionService, "assign_flow", forbidden_write)
    monkeypatch.setattr(ApprovalExceptionService, "skip_node", forbidden_write)
    monkeypatch.setattr(ApprovalExceptionService, "mark_manually_completed", forbidden_write)

    for action in ("assign_approvers", "assign_flow", "skip_node", "mark_manually_completed"):
        with pytest.raises(PermissionError, match="not allowed"):
            await ApprovalExceptionService.retry_exception_api(
                exception_id=301,
                action=action,
                operator_user_id=1,
                approver_user_ids=[9],
            )

    forbidden_write.assert_not_awaited()


async def test_f046_retry_uses_strict_reconcile_in_instance_first_transaction(monkeypatch: pytest.MonkeyPatch):
    instance = _instance()
    exception = ApprovalException(id=301, tenant_id=42, instance_id=101, exception_type="approver_empty")
    events: list[str] = []

    class _Session:
        @asynccontextmanager
        async def begin(self):
            events.append("begin")
            yield
            events.append("commit")

    @asynccontextmanager
    async def session_factory():
        yield _Session()

    async def lock_instance(_session, _instance_id):
        events.append("lock-instance")
        return instance

    async def lock_related(_session, _instance_id):
        events.append("lock-related")
        return [exception], []

    async def reconcile(**_kwargs):
        events.append("strict-reconcile")
        exception.status = "resolved"
        return SimpleNamespace(post_commit_effects=())

    handler = SimpleNamespace(
        exception_action_policy=AsyncMock(return_value=True),
        reconcile_pending_approvers=AsyncMock(side_effect=reconcile),
    )
    monkeypatch.setattr(ApprovalInstanceRepository, "decision_session", session_factory)
    monkeypatch.setattr(ApprovalInstanceRepository, "lock_instance_in_session", lock_instance)
    monkeypatch.setattr(ApprovalInstanceRepository, "lock_tasks_in_session", AsyncMock(return_value=[]))
    monkeypatch.setattr(ApprovalInstanceRepository, "lock_open_exceptions_and_outboxes_in_session", lock_related)
    monkeypatch.setattr(ApprovalInstanceRepository, "flush_decision_in_session", AsyncMock())
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_exception_service.build_runtime_handler",
        AsyncMock(return_value=handler),
    )
    monkeypatch.setattr(
        ApprovalExceptionService,
        "_get_exception",
        AsyncMock(return_value=exception),
    )
    monkeypatch.setattr(ApprovalExceptionService, "_get_instance", AsyncMock(return_value=instance))
    monkeypatch.setattr(ApprovalExceptionService, "_write_audit_log", AsyncMock())

    result = await ApprovalExceptionService.retry_exception_api(
        exception_id=301,
        action="retry",
        operator_user_id=1,
    )

    assert result["status"] == "resolved"
    assert events == ["begin", "lock-instance", "lock-related", "strict-reconcile", "commit"]


def test_exception_outbox_dispatch_carries_explicit_tenant_header():
    with patch(
        "bisheng.worker.approval.tasks.execute_approval_outbox.apply_async",
    ) as apply_async:
        ApprovalExceptionService._dispatch_outbox(901, tenant_id=42)

    apply_async.assert_called_once_with(
        args=[901],
        headers={"tenant_id": 42},
    )
