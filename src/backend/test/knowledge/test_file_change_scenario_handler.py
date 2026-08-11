from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_outbox_service import Completed, Deferred
from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
from bisheng.core.context.tenant import current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_upload_stage_repository import (
    KnowledgeSpaceUploadStageRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_scenario_handler import (
    FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeScenarioHandler,
    KnowledgeSpaceFileChangeTerminalCleanupService,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
    FileChangeRequestCommand,
    KnowledgeSpaceFileChangeService,
)


@pytest.fixture(autouse=True)
def tenant_context():
    token = current_tenant_id.set(42)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _gate_request(*, action: str = KnowledgeSpaceFileChangeAction.RENAME) -> ApprovalGateRequest:
    return ApprovalGateRequest(
        tenant_id=42,
        scenario_code=FILE_CHANGE_SCENARIO_CODE,
        business_key="knowledge-space-change:81",
        business_resource_type="knowledge_space_file_change",
        business_resource_id="81",
        business_name="quarterly.pdf",
        applicant_user_id=7,
        applicant_user_name="applicant",
        reason="keep names consistent",
        payload_snapshot={
            "change_request_id": 81,
            "space_id": 8,
            "action": action,
            "resource_type": KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            "resource_id": 99,
            "target_space_id": 8,
            "target_parent_id": 12,
        },
        detail_snapshot={
            "space_name": "Finance",
            "old_name": "q1.pdf",
            "new_name": "quarterly.pdf",
            "nested": {"object_name": "must-not-leak", "old_path": "/q1.pdf"},
            "object_name": "must-not-leak",
        },
    )


def _instance(
    *,
    applicant_user_id: int = 7,
    action: str = KnowledgeSpaceFileChangeAction.RENAME,
) -> ApprovalInstance:
    return ApprovalInstance(
        id=101,
        tenant_id=42,
        scenario_code=FILE_CHANGE_SCENARIO_CODE,
        handler_key=FILE_CHANGE_SCENARIO_CODE,
        business_key="knowledge-space-change:81",
        business_resource_type="knowledge_space_file_change",
        business_resource_id="81",
        business_name="quarterly.pdf",
        applicant_user_id=applicant_user_id,
        applicant_user_name="applicant",
        payload_snapshot={
            "change_request_id": 81,
            "space_id": 8,
            "action": action,
            "resource_type": (
                KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD
                if action == KnowledgeSpaceFileChangeAction.UPLOAD
                else KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE
            ),
            "resource_id": None if action == KnowledgeSpaceFileChangeAction.UPLOAD else 99,
            "upload_id": "01a02c03-0405-4607-8809-0a0b0c0d0e0f" if action == "upload" else None,
        },
    )


async def test_build_title_and_detail_preserve_action_snapshot_without_storage_names():
    handler = KnowledgeSpaceFileChangeScenarioHandler()
    request = _gate_request()

    assert await handler.build_title(request) == "重命名 Finance / quarterly.pdf"
    detail = await handler.build_detail(request)

    assert detail["action"] == "rename"
    assert detail["action_label"] == "重命名"
    assert detail["space_id"] == 8
    assert detail["space_name"] == "Finance"
    assert detail["resource_type"] == "file"
    assert detail["resource_name"] == "quarterly.pdf"
    assert detail["change"]["old_name"] == "q1.pdf"
    assert detail["change"]["new_name"] == "quarterly.pdf"
    assert detail["change"]["nested"] == {"old_path": "/q1.pdf"}
    assert "object_name" not in detail["change"]


def test_public_resource_type_mapping_is_explicit_and_does_not_hide_internal_drift():
    assert KnowledgeSpaceFileChangeScenarioHandler._public_resource_type("knowledge_file") == "file"
    assert KnowledgeSpaceFileChangeScenarioHandler._public_resource_type("staged_upload") == "staged_upload"
    assert (
        KnowledgeSpaceFileChangeScenarioHandler._public_resource_type("knowledge_file_version")
        == "knowledge_file_version"
    )


async def test_resolve_approvers_uses_strict_owner_manager_and_excludes_applicant():
    resolver = AsyncMock(return_value=[9, 11])
    handler = KnowledgeSpaceFileChangeScenarioHandler(approver_resolver=resolver)

    result = await handler.resolve_approvers(
        {
            "sources": [
                {"type": "knowledge_space_owner"},
                {"type": "knowledge_space_manager"},
            ]
        },
        _gate_request(),
    )

    assert result == [9, 11]
    resolver.assert_awaited_once_with(
        tenant_id=42,
        space_id=8,
        applicant_user_id=7,
    )


async def test_resolve_approvers_rejects_mutated_fixed_sources_without_fallback():
    resolver = AsyncMock()
    handler = KnowledgeSpaceFileChangeScenarioHandler(approver_resolver=resolver)

    assert (
        await handler.resolve_approvers({"sources": [{"type": "direct_user", "user_ids": [9]}]}, _gate_request()) == []
    )
    resolver.assert_not_awaited()


async def test_current_approver_is_final_view_and_decision_boundary():
    current_approver = AsyncMock(side_effect=lambda **kwargs: kwargs["user_id"] == 9)
    handler = KnowledgeSpaceFileChangeScenarioHandler(current_approver_checker=current_approver)
    instance = _instance()

    assert await handler.authorize_view(instance=instance, viewer_user_id=7)
    assert await handler.authorize_view(instance=instance, viewer_user_id=9)
    assert not await handler.authorize_view(instance=instance, viewer_user_id=10)
    assert await handler.validate_decision(instance=instance, operator_user_id=9)
    assert not await handler.authorize_decision(instance=instance, operator_user_id=10)

    assert current_approver.await_count == 4


async def test_filter_visibility_resolves_each_candidate_space_once():
    managed_space_loader = AsyncMock(return_value=[8, 9])
    resolver = AsyncMock(side_effect=lambda **kwargs: [9] if kwargs["space_id"] == 8 else [10])
    handler = KnowledgeSpaceFileChangeScenarioHandler(
        managed_space_loader=managed_space_loader,
        approver_resolver=resolver,
    )
    applicant = _instance(applicant_user_id=9)
    same_space_first = _instance(applicant_user_id=7)
    same_space_first.id = 102
    same_space_second = _instance(applicant_user_id=6)
    same_space_second.id = 103
    other_space = _instance(applicant_user_id=5)
    other_space.id = 104
    other_space.payload_snapshot = {**other_space.payload_snapshot, "space_id": 9}

    visible = await handler.filter_visible_instances(
        instances=[applicant, same_space_first, same_space_second, other_space],
        viewer_user_id=9,
        tenant_id=42,
    )

    assert [row.id for row in visible] == [101, 102, 103]
    managed_space_loader.assert_awaited_once_with(tenant_id=42, user_id=9)
    assert resolver.await_count == 2


async def test_discover_candidates_uses_bounded_missing_task_query():
    managed_space_loader = AsyncMock(return_value=[8, 9])
    candidate_loader = AsyncMock(return_value=[101, 102])
    handler = KnowledgeSpaceFileChangeScenarioHandler(
        managed_space_loader=managed_space_loader,
        candidate_instance_loader=candidate_loader,
    )

    result = await handler.discover_candidate_instances(
        tenant_id=42,
        viewer_user_id=9,
        after_instance_id=100,
        limit=10_000,
    )

    assert result == [101, 102]
    candidate_loader.assert_awaited_once_with(
        tenant_id=42,
        space_ids=[8, 9],
        after_instance_id=100,
        limit=500,
        missing_pending_approver_user_id=9,
    )


async def test_reconcile_hooks_only_delegate_to_f025_atomic_service():
    in_uow = AsyncMock(return_value=SimpleNamespace(post_commit_effects=()))
    standalone = AsyncMock(return_value=SimpleNamespace(post_commit_effects=()))
    handler = KnowledgeSpaceFileChangeScenarioHandler(
        reconcile_in_uow=in_uow,
        reconcile_instance=standalone,
        approver_resolver=AsyncMock(return_value=[9]),
    )
    instance = _instance()

    await handler.reconcile_pending_approvers(session="session", instance=instance, trigger="decision")
    await handler.reconcile_candidate_instance(instance_id=101, trigger="list")

    assert in_uow.await_count == 1
    assert standalone.await_count == 1


@pytest.mark.parametrize(
    ("action", "exception_type", "allowed"),
    [
        ("retry", "approver_empty", True),
        ("retry", "execute_failed", True),
        ("retry", "route_missing", False),
        ("cancel", "approver_empty", True),
        ("assign_approvers", "approver_empty", False),
        ("assign_flow", "approver_empty", False),
        ("skip_node", "approver_empty", False),
        ("mark_manually_completed", "execute_failed", False),
    ],
)
async def test_fixed_scene_exception_policy_blocks_bypass_actions(
    action: str,
    exception_type: str,
    allowed: bool,
):
    handler = KnowledgeSpaceFileChangeScenarioHandler()
    exception = SimpleNamespace(exception_type=exception_type)
    assert await handler.exception_action_policy(action=action, exception=exception) is allowed


async def test_fixed_scene_retry_without_locked_exception_context_fails_closed():
    handler = KnowledgeSpaceFileChangeScenarioHandler()
    assert not await handler.exception_action_policy(action="retry")


async def test_approved_execution_requires_explicit_completed_or_deferred_result():
    completed = Completed()
    executor = AsyncMock(return_value=completed)
    handler = KnowledgeSpaceFileChangeScenarioHandler(mutation_executor=executor)
    payload = _instance().payload_snapshot

    assert await handler.on_approved(101, payload) is completed
    executor.assert_awaited_once_with(
        instance_id=101,
        request_id=81,
        payload_snapshot=payload,
    )

    invalid = KnowledgeSpaceFileChangeScenarioHandler(mutation_executor=AsyncMock(return_value=None))
    with pytest.raises(TypeError, match="Completed or Deferred"):
        await invalid.on_approved(101, payload)


async def test_prepare_resume_delegates_session_and_requires_matching_deferred_token():
    deadline = datetime.now(UTC) + timedelta(minutes=30)
    resume = AsyncMock(return_value=Deferred(execution_token="new-token", deadline=deadline))
    handler = KnowledgeSpaceFileChangeScenarioHandler(resume_preparer=resume)

    result = await handler.prepare_resume("session", "new-token")

    assert result.execution_token == "new-token"
    resume.assert_awaited_once_with("session", "new-token")

    invalid = KnowledgeSpaceFileChangeScenarioHandler(
        resume_preparer=AsyncMock(return_value=Deferred(execution_token="stale", deadline=deadline))
    )
    with pytest.raises(ValueError, match="current execution token"):
        await invalid.prepare_resume("session", "new-token")


async def test_resume_dispatcher_requires_explicit_tenant_identity():
    dispatch = AsyncMock()
    handler = KnowledgeSpaceFileChangeScenarioHandler(resume_dispatcher=dispatch)

    await handler.dispatch_resumed_execution(
        outbox_id=17,
        execution_token="generation-2",
        tenant_id=42,
    )

    dispatch.assert_awaited_once_with(
        outbox_id=17,
        execution_token="generation-2",
        tenant_id=42,
    )
    with pytest.raises(ValueError, match="outbox, token and tenant"):
        await handler.dispatch_resumed_execution(
            outbox_id=17,
            execution_token="generation-2",
            tenant_id=0,
        )


@pytest.mark.parametrize("terminal_hook", ["on_rejected", "on_withdrawn", "on_cancelled"])
async def test_upload_terminal_hooks_trigger_recoverable_cleanup(terminal_hook: str):
    cleanup = AsyncMock()
    handler = KnowledgeSpaceFileChangeScenarioHandler(terminal_cleanup=cleanup)
    payload = _instance(action=KnowledgeSpaceFileChangeAction.UPLOAD).payload_snapshot

    await getattr(handler, terminal_hook)(101, payload, "reason")

    cleanup.assert_awaited_once_with(
        tenant_id=42,
        request_id=81,
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        terminal_action=terminal_hook.removeprefix("on_"),
        reason="reason",
    )


async def test_non_upload_terminal_hook_never_cleans_formal_resource():
    cleanup = AsyncMock()
    handler = KnowledgeSpaceFileChangeScenarioHandler(terminal_cleanup=cleanup)

    await handler.on_rejected(101, _instance().payload_snapshot, "reason")

    cleanup.assert_not_awaited()


async def test_terminal_cleanup_marks_pending_before_owner_cleanup_and_success_afterward():
    request = KnowledgeSpaceFileChangeRequest(
        id=81,
        tenant_id=42,
        space_id=8,
        action="upload",
        resource_type="staged_upload",
        applicant_user_id=7,
        cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
    )
    states: list[str] = []

    async def save_request(*, tenant_id: int, request_id: int, upload_id: str, cleanup_state: str):
        assert tenant_id == 42
        assert request_id == 81
        assert upload_id == "01a02c03-0405-4607-8809-0a0b0c0d0e0f"
        request.cleanup_state = cleanup_state
        states.append(cleanup_state)
        return request

    owner_cleanup = AsyncMock(return_value=SimpleNamespace(state="cleaned"))
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=save_request,
        upload_stage_cleanup=owner_cleanup,
    )

    await service.cleanup(
        tenant_id=42,
        request_id=81,
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        terminal_action="rejected",
        reason="no",
    )

    assert states == [KnowledgeSpaceFileChangeCleanupState.PENDING, KnowledgeSpaceFileChangeCleanupState.SUCCESS]
    owner_cleanup.assert_awaited_once_with("01a02c03-0405-4607-8809-0a0b0c0d0e0f")


async def test_terminal_cleanup_failure_stays_pending_and_is_retryable():
    request = KnowledgeSpaceFileChangeRequest(
        id=81,
        tenant_id=42,
        space_id=8,
        action="upload",
        resource_type="staged_upload",
        applicant_user_id=7,
        cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
    )
    states: list[str] = []

    async def save_request(*, tenant_id: int, request_id: int, upload_id: str, cleanup_state: str):
        assert tenant_id == 42
        assert request_id == 81
        assert upload_id == "01a02c03-0405-4607-8809-0a0b0c0d0e0f"
        request.cleanup_state = cleanup_state
        states.append(cleanup_state)
        return request

    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=save_request,
        upload_stage_cleanup=AsyncMock(side_effect=OSError("storage unavailable")),
    )

    with pytest.raises(OSError, match="storage unavailable"):
        await service.cleanup(
            tenant_id=42,
            request_id=81,
            upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
            terminal_action="withdrawn",
            reason=None,
        )

    assert states == [KnowledgeSpaceFileChangeCleanupState.PENDING]


async def test_terminal_cleanup_rejects_unbound_upload_before_owner_cleanup():
    owner_cleanup = AsyncMock()
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=None),
        cleanup_state_saver=AsyncMock(),
        upload_stage_cleanup=owner_cleanup,
    )

    with pytest.raises(LookupError, match="bound stage"):
        await service.cleanup(
            tenant_id=42,
            request_id=81,
            upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
            terminal_action="rejected",
            reason=None,
        )

    owner_cleanup.assert_not_awaited()


async def test_default_cleanup_loader_checks_request_to_stage_binding(monkeypatch: pytest.MonkeyPatch):
    request = KnowledgeSpaceFileChangeRequest(
        id=81,
        tenant_id=42,
        space_id=8,
        action="upload",
        resource_type="staged_upload",
        applicant_user_id=7,
        upload_stage_id=501,
    )
    request_lookup = AsyncMock(return_value=request)
    mismatched_stage_lookup = AsyncMock(return_value=SimpleNamespace(id=999))
    monkeypatch.setattr(KnowledgeSpaceFileChangeRequestRepository, "get_by_id", request_lookup)
    monkeypatch.setattr(KnowledgeSpaceUploadStageRepository, "get_by_upload_id", mismatched_stage_lookup)

    result = await KnowledgeSpaceFileChangeTerminalCleanupService._load_bound_request(
        tenant_id=42,
        request_id=81,
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        for_update=True,
        session=object(),
    )

    assert result is None
    request_lookup.assert_awaited_once_with(tenant_id=42, request_id=81, for_update=True)
    mismatched_stage_lookup.assert_awaited_once_with(
        tenant_id=42,
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        for_update=True,
    )


async def test_terminal_cleanup_success_is_idempotent():
    request = KnowledgeSpaceFileChangeRequest(
        id=81,
        tenant_id=42,
        space_id=8,
        action="upload",
        resource_type="staged_upload",
        applicant_user_id=7,
        cleanup_state=KnowledgeSpaceFileChangeCleanupState.SUCCESS,
    )
    save = AsyncMock()
    owner_cleanup = AsyncMock()
    service = KnowledgeSpaceFileChangeTerminalCleanupService(
        request_loader=AsyncMock(return_value=request),
        cleanup_state_saver=save,
        upload_stage_cleanup=owner_cleanup,
    )

    await service.cleanup(
        tenant_id=42,
        request_id=81,
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        terminal_action="cancelled",
        reason=None,
    )

    save.assert_not_awaited()
    owner_cleanup.assert_not_awaited()


async def test_business_projection_uses_change_request_id_and_does_not_mutate_approval():
    request_loader = AsyncMock(
        return_value=KnowledgeSpaceFileChangeRequest(
            id=81,
            tenant_id=42,
            space_id=8,
            action="upload",
            resource_type="staged_upload",
            applicant_user_id=7,
            execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
            execution_checkpoint={"failure_reason": "parser failed"},
        )
    )
    handler = KnowledgeSpaceFileChangeScenarioHandler(request_loader=request_loader)

    projection = await handler.get_business_status_projection(instance=_instance(action="upload"))

    assert projection == {
        "status": "execute_failed",
        "action": KnowledgeSpaceFileChangeAction.UPLOAD,
        "execution_state": KnowledgeSpaceFileChangeExecutionState.FAILED,
        "failure_reason": "parser failed",
        "cleanup_state": KnowledgeSpaceFileChangeCleanupState.NONE,
    }
    request_loader.assert_awaited_once_with(tenant_id=42, request_id=81)


async def test_runtime_factory_registers_complete_f046_handler():
    handler = await build_runtime_handler(FILE_CHANGE_SCENARIO_CODE)
    assert isinstance(handler, KnowledgeSpaceFileChangeScenarioHandler)
    assert callable(handler.on_approved)
    assert callable(handler.prepare_resume)


def test_root_change_request_rejects_version_resource_type():
    command = FileChangeRequestCommand(
        action=KnowledgeSpaceFileChangeAction.DELETE,
        space_id=8,
        applicant_user_id=7,
        applicant_user_name="applicant",
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE_VERSION,
        resource_name="version.pdf",
        resource_id=99,
    )

    with pytest.raises(ValueError, match="unsupported file change resource type"):
        KnowledgeSpaceFileChangeService._validate_command(command)


def test_gate_payload_keeps_opaque_upload_id_without_storage_reference():
    command = FileChangeRequestCommand(
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        space_id=8,
        applicant_user_id=7,
        applicant_user_name="applicant",
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        resource_name="upload.pdf",
        upload_id="01a02c03-0405-4607-8809-0a0b0c0d0e0f",
        action_snapshot={"relative_path": "reports/upload.pdf"},
    )
    request = KnowledgeSpaceFileChangeRequest(
        id=81,
        tenant_id=42,
        space_id=8,
        action="upload",
        resource_type="staged_upload",
        applicant_user_id=7,
    )

    gate_request = KnowledgeSpaceFileChangeService._build_gate_request(
        tenant_id=42,
        request=request,
        command=command,
    )

    assert gate_request.payload_snapshot["upload_id"] == command.upload_id
    assert gate_request.detail_snapshot == {"relative_path": "reports/upload.pdf"}
    assert "object_name" not in gate_request.payload_snapshot


def test_request_rejects_nested_storage_reference_in_action_snapshot():
    command = FileChangeRequestCommand(
        action=KnowledgeSpaceFileChangeAction.RENAME,
        space_id=8,
        applicant_user_id=7,
        applicant_user_name="applicant",
        resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
        resource_name="renamed.pdf",
        resource_id=99,
        action_snapshot={"change": [{"storage_path": "secret/internal/key"}]},
    )

    with pytest.raises(ValueError, match="storage object names"):
        KnowledgeSpaceFileChangeService._validate_command(command)
