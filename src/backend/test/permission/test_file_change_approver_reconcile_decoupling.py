from __future__ import annotations

import inspect
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.ports.decision_subscriber import ApprovalDecisionPermanentError
from bisheng.approval.domain.ports.scenario_policy import ApprovalDecisionContext
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_dynamic_assignee_service import ApprovalDynamicAssigneeService
from bisheng.approval.domain.services.approval_exception_service import ApprovalExceptionService
from bisheng.common.errcode.knowledge_space import SpaceFileChangeApproverUnavailableError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approval_policy import (
    KnowledgeSpaceFileChangeApprovalPolicy,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem

TENANT_ID = 7
SPACE_ID = 88


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def _build_dispatcher(*, resolver: AsyncMock, reconcile: AsyncMock):
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        FileChangeApproverReconcileDispatcher,
    )

    return FileChangeApproverReconcileDispatcher(
        knowledge_resolver=resolver,
        reconciliation_port=reconcile,
    )


async def test_permission_event_resolves_in_knowledge_then_calls_only_f025_application_port() -> None:
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_permission_change,
    )

    calls: list[str] = []

    async def resolve(**kwargs):
        calls.append("knowledge")
        assert kwargs == {"tenant_id": TENANT_ID, "space_id": SPACE_ID}
        return [
            SimpleNamespace(instance_id=501, approver_user_ids=(201, 202)),
            SimpleNamespace(instance_id=502, approver_user_ids=(203,)),
        ]

    async def reconcile(**kwargs):
        calls.append("f025")
        assert set(kwargs) == {"tenant_id", "instance_id", "approver_user_ids", "reason"}

    resolver = AsyncMock(side_effect=resolve)
    reconciliation_port = AsyncMock(side_effect=reconcile)
    dispatcher = _build_dispatcher(resolver=resolver, reconcile=reconciliation_port)
    manager_grant = AuthorizeGrantItem(subject_type="user", subject_id=201, relation="manager")

    await dispatch_file_change_approver_reconcile_for_permission_change(
        resource_type="knowledge_space",
        resource_id=str(SPACE_ID),
        grants=[manager_grant],
        tenant_id=TENANT_ID,
        dispatcher=dispatcher,
    )

    assert calls == ["knowledge", "f025", "f025"]
    assert [call.kwargs for call in reconciliation_port.await_args_list] == [
        {
            "tenant_id": TENANT_ID,
            "instance_id": 501,
            "approver_user_ids": (201, 202),
            "reason": "permission_event",
        },
        {
            "tenant_id": TENANT_ID,
            "instance_id": 502,
            "approver_user_ids": (203,),
            "reason": "permission_event",
        },
    ]


@pytest.mark.parametrize("reason", ["lazy_page", "beat"])
async def test_lazy_page_and_beat_reuse_the_same_bounded_reconcile_entry(reason: str) -> None:
    resolver = AsyncMock(return_value=[SimpleNamespace(instance_id=501, approver_user_ids=(202, 203))])
    reconciliation_port = AsyncMock()
    dispatcher = _build_dispatcher(resolver=resolver, reconcile=reconciliation_port)

    await dispatcher.reconcile_space(
        tenant_id=TENANT_ID,
        space_id=SPACE_ID,
        reason=reason,
    )

    resolver.assert_awaited_once_with(tenant_id=TENANT_ID, space_id=SPACE_ID)
    reconciliation_port.assert_awaited_once_with(
        tenant_id=TENANT_ID,
        instance_id=501,
        approver_user_ids=(202, 203),
        reason=reason,
    )


async def test_openfga_failure_is_not_converted_to_an_authoritative_empty_set() -> None:
    unavailable = SpaceFileChangeApproverUnavailableError()
    resolver = AsyncMock(side_effect=unavailable)
    reconciliation_port = AsyncMock()
    dispatcher = _build_dispatcher(resolver=resolver, reconcile=reconciliation_port)

    with pytest.raises(SpaceFileChangeApproverUnavailableError) as raised:
        await dispatcher.reconcile_space(
            tenant_id=TENANT_ID,
            space_id=SPACE_ID,
            reason="beat",
        )

    assert raised.value is unavailable
    reconciliation_port.assert_not_awaited()


@pytest.mark.parametrize("context_tenant_id", [None, 8])
async def test_dispatcher_requires_matching_tenant_context(context_tenant_id: int | None) -> None:
    resolver = AsyncMock(return_value=[])
    dispatcher = _build_dispatcher(resolver=resolver, reconcile=AsyncMock())
    token = current_tenant_id.set(context_tenant_id)
    try:
        with pytest.raises(ValueError, match="matching tenant"):
            await dispatcher.reconcile_space(
                tenant_id=TENANT_ID,
                space_id=SPACE_ID,
                reason="beat",
            )
    finally:
        current_tenant_id.reset(token)

    resolver.assert_not_awaited()


def test_permission_dispatcher_has_no_approval_storage_or_approval_worker_dependency() -> None:
    import bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher as dispatcher_module

    source = inspect.getsource(dispatcher_module)
    forbidden_dependencies = (
        "bisheng.approval.domain.models",
        "bisheng.approval.domain.repositories",
        "approval_instance_repository",
        "bisheng.worker.approval",
    )

    assert [dependency for dependency in forbidden_dependencies if dependency in source] == []


def test_ordinary_approval_queries_do_not_scan_knowledge_for_current_approvers() -> None:
    query_methods = (
        ApprovalCenterService.list_my_tasks,
        ApprovalCenterService.list_my_requests,
        ApprovalCenterService.get_task_detail,
        ApprovalCenterService.get_instance_detail,
    )
    forbidden_fragments = (
        "bisheng.knowledge",
        "KnowledgeSpaceFileChange",
        "build_runtime_handler",
        "resolve_approver",
        "reconcile_pending_approvers",
    )

    for method in query_methods:
        source = inspect.getsource(method)
        used = [fragment for fragment in forbidden_fragments if fragment in source]
        assert used == [], f"{method.__name__} scans Knowledge: {used}"


class _FakeSession:
    def __init__(self) -> None:
        self.add = Mock()
        self.flush = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def begin(self) -> AbstractAsyncContextManager[object]:
        return self


async def test_former_pending_task_is_cancelled_and_realtime_policy_rejects_decision() -> None:
    former_task = ApprovalTask(
        id=601,
        tenant_id=TENANT_ID,
        instance_id=501,
        flow_version_id=1,
        node_code="space_owner_manager",
        node_name="space owner or manager",
        node_order=1,
        approver_user_id=201,
        approver_source_type="business_policy",
        node_mode="or",
        status=ApprovalTaskStatus.PENDING,
    )
    instance = ApprovalInstance(
        id=501,
        tenant_id=TENANT_ID,
        scenario_code="knowledge_space_file_change_request",
        scenario_name="file change",
        handler_key="knowledge_space_file_change_request_subscriber",
        business_key="space:88:request:41",
        business_resource_type=KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
        business_resource_id="41",
        business_name="report.pdf",
        applicant_user_id=101,
        applicant_user_name="applicant",
        flow_version_id=1,
        status=ApprovalInstanceStatus.PENDING,
        current_node_name="space owner or manager",
    )
    approval_session = _FakeSession()
    with patch.object(
        ApprovalExceptionService,
        "resolve_approver_empty_locked",
        new=AsyncMock(return_value=False),
    ):
        result = await ApprovalDynamicAssigneeService._reconcile_resolved_locked(
            session=approval_session,
            instance=instance,
            tasks=[former_task],
            open_exceptions=[],
            node=SimpleNamespace(
                flow_version_id=1,
                code="space_owner_manager",
                name="space owner or manager",
                order=1,
                mode="or",
            ),
            approver_user_ids=(202,),
            trigger="permission_event",
            operator_user_id=None,
        )

    assert former_task.status == ApprovalTaskStatus.CANCELLED
    assert result.removed_user_ids == (201,)
    assert result.added_user_ids == (202,)

    knowledge_row = SimpleNamespace(
        id=41,
        tenant_id=TENANT_ID,
        space_id=SPACE_ID,
        approval_instance_id=501,
        request_fingerprint="fingerprint:41",
    )
    policy_session = _FakeSession()
    policy = KnowledgeSpaceFileChangeApprovalPolicy(
        session_factory=lambda: policy_session,
        approver_resolver=AsyncMock(return_value=[202]),
    )
    context = ApprovalDecisionContext(
        tenant_id=TENANT_ID,
        approval_instance_id=501,
        business_request_type=KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
        business_request_id="41",
        request_fingerprint="fingerprint:41",
        operator_user_id=201,
        decision="approved",
    )
    with (
        patch.object(policy, "_load_for_update", new=AsyncMock(return_value=knowledge_row)),
        pytest.raises(ApprovalDecisionPermanentError, match="current owner or manager"),
    ):
        await policy.authorize_decision(context)
