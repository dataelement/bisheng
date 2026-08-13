from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusSnapshot
from bisheng.knowledge.api.endpoints import knowledge_space_file_change as endpoint_module
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeCleanupState,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import FileChangeApprovalStatus
from bisheng.knowledge.domain.services import knowledge_space_file_change_application_service as application_module
from bisheng.knowledge.domain.services.knowledge_space_file_change_application_service import (
    KnowledgeSpaceFileChangeApplicationService,
)

TENANT_ID = 42
SPACE_ID = 101
APPLICANT_USER_ID = 7

BUSINESS_STATES = (
    KnowledgeSpaceFileChangeExecutionState.QUEUED,
    KnowledgeSpaceFileChangeExecutionState.APPLYING,
    KnowledgeSpaceFileChangeExecutionState.APPLIED,
    KnowledgeSpaceFileChangeExecutionState.FAILED,
    KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
    KnowledgeSpaceFileChangeExecutionState.CLOSED,
)


class _ApprovalStatusPort:
    def __init__(self, statuses: dict[int, str]) -> None:
        self.statuses = dict(statuses)
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    async def get_statuses(
        self,
        *,
        tenant_id: int,
        approval_instance_ids,
    ) -> dict[int, ApprovalStatusSnapshot]:
        instance_ids = tuple(int(value) for value in approval_instance_ids)
        self.calls.append((tenant_id, instance_ids))
        return {
            instance_id: ApprovalStatusSnapshot(
                instance_id=instance_id,
                status=self.statuses[instance_id],
            )
            for instance_id in instance_ids
            if instance_id in self.statuses
        }


@dataclass(frozen=True)
class _RetryIdentity:
    tenant_id: int
    request_id: int
    execution_token: str


@dataclass(frozen=True)
class _KnowledgeReadRow:
    """Knowledge-owned read DTO; Approval facts are intentionally absent."""

    request: SimpleNamespace
    upload_id: str | None
    stage_state: str | None
    applicant_user_name: str | None
    resource_name: str


class _ExecutionCoordinator:
    def __init__(self, view: _KnowledgeReadRow) -> None:
        self.view = view
        self.calls: list[tuple[int, int]] = []

    async def queue_retry(self, *, tenant_id: int, request_id: int) -> _RetryIdentity:
        self.calls.append((tenant_id, request_id))
        request = self.view.request
        assert request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.QUEUED
        request.execution_token = "generation-2"
        return _RetryIdentity(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token="generation-2",
        )


class _Dispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None:
        self.calls.append((tenant_id, request_id))


def _viewer(*, user_id: int = APPLICANT_USER_ID):
    return SimpleNamespace(
        tenant_id=TENANT_ID,
        user_id=user_id,
        user_name=f"user-{user_id}",
        is_admin=lambda: False,
    )


def _view(
    *,
    request_id: int,
    approval_instance_id: int,
    execution_state: str,
) -> _KnowledgeReadRow:
    request = SimpleNamespace(
        id=request_id,
        tenant_id=TENANT_ID,
        space_id=SPACE_ID,
        action=KnowledgeSpaceFileChangeAction.UPLOAD,
        resource_type=KnowledgeSpaceFileChangeResourceType.STAGED_UPLOAD,
        resource_id=None,
        applicant_user_id=APPLICANT_USER_ID,
        approval_instance_id=approval_instance_id,
        upload_stage_id=request_id + 1000,
        file_name=f"file-{request_id}.pdf",
        file_size=128,
        content_hash=f"hash-{request_id}",
        source_parent_id=None,
        target_space_id=None,
        target_parent_id=None,
        action_snapshot={"relative_path": f"file-{request_id}.pdf"},
        result_snapshot={},
        executed_resource_id=None,
        execution_state=execution_state,
        execution_token="generation-1" if execution_state != "queued" else None,
        execution_checkpoint={"failure_reason": "parser unavailable"}
        if execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED
        else {},
        cleanup_state=KnowledgeSpaceFileChangeCleanupState.NONE,
        create_time=datetime(2026, 8, 13, 9, request_id % 60),
        update_time=datetime(2026, 8, 13, 10, request_id % 60),
    )
    return _KnowledgeReadRow(
        request=request,
        upload_id=f"upload-{request_id}",
        stage_state="attached",
        applicant_user_name="applicant",
        resource_name=request.file_name,
    )


def _service(
    views: list[_KnowledgeReadRow],
    *,
    approval_statuses: dict[int, str] | None = None,
) -> tuple[
    KnowledgeSpaceFileChangeApplicationService,
    SimpleNamespace,
    _ApprovalStatusPort,
    _ExecutionCoordinator,
    _Dispatcher,
]:
    by_request_id = {int(view.request.id): view for view in views}
    repository = SimpleNamespace(
        get_request_view=AsyncMock(
            side_effect=lambda **kwargs: by_request_id.get(int(kwargs["request_id"])),
        ),
        list_upload_request_views=AsyncMock(return_value=(views, False)),
        get_request_views_by_instance_ids=AsyncMock(return_value=views),
        get_request_views_by_request_ids=AsyncMock(return_value=views),
    )
    approval_status_port = _ApprovalStatusPort(
        approval_statuses
        or {
            int(view.request.approval_instance_id): "approved"
            for view in views
        }
    )
    projection_loader = AsyncMock(
        side_effect=lambda view: {
            "status": str(view.request.execution_state),
            "execution_state": str(view.request.execution_state),
            "failure_reason": (view.request.execution_checkpoint or {}).get("failure_reason"),
            "cleanup_state": str(view.request.cleanup_state),
        }
    )
    batch_projection_loader = AsyncMock(
        side_effect=lambda rows: {
            int(view.request.id): {
                "status": str(view.request.execution_state),
                "execution_state": str(view.request.execution_state),
                "failure_reason": (view.request.execution_checkpoint or {}).get("failure_reason"),
                "cleanup_state": str(view.request.cleanup_state),
            }
            for view in rows
        }
    )
    approval_center = SimpleNamespace(
        decide_instance_for_current_approver=AsyncMock(),
        withdraw_instance=AsyncMock(),
    )
    approval_exception = SimpleNamespace(
        retry_execute_failed_api=AsyncMock(side_effect=AssertionError("business retry crossed into Approval")),
        cancel_exception_api=AsyncMock(side_effect=AssertionError("business cleanup crossed into Approval")),
    )
    service = KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=False),
        projection_loader=projection_loader,
        batch_projection_loader=batch_projection_loader,
        stage_preview=AsyncMock(),
        formal_preview=AsyncMock(),
        approval_center=approval_center,
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    )
    coordinator = _ExecutionCoordinator(views[0])
    dispatcher = _Dispatcher()
    # T063 owns the wiring. Assigning the ports explicitly keeps this red test
    # focused on behavior instead of failing every case at constructor binding.
    service.approval_status_port = approval_status_port
    service.execution_coordinator = coordinator
    service.execution_dispatcher = dispatcher
    return service, approval_exception, approval_status_port, coordinator, dispatcher


def test_public_business_status_vocabulary_is_knowledge_owned() -> None:
    public_values = {member.value for member in FileChangeApprovalStatus}

    assert set(BUSINESS_STATES) <= public_values
    assert not {
        "executing",
        "executed",
        "execute_failed",
        "parsing",
        "parse_failed",
        "published",
    } & public_values


async def test_internal_not_started_is_visible_as_queued_with_pending_approval() -> None:
    view = _view(
        request_id=41,
        approval_instance_id=301,
        execution_state=KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
    )
    service, _approval_exception, status_port, _coordinator, _dispatcher = _service(
        [view],
        approval_statuses={301: "pending"},
    )

    detail = await service.get_detail(space_id=SPACE_ID, request_id=41, viewer=_viewer())
    listing = await service.list_uploads(space_id=SPACE_ID, viewer=_viewer(), status="queued")

    assert detail.status == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert detail.approval_status == "pending"
    assert listing.data[0].status == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert listing.data[0].approval_status == "pending"
    assert set(service.repository_factory().list_upload_request_views.await_args.kwargs["execution_states"]) == {
        KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
        KnowledgeSpaceFileChangeExecutionState.QUEUED,
    }
    assert status_port.calls


@pytest.mark.parametrize("execution_state", BUSINESS_STATES)
async def test_detail_exposes_knowledge_state_separately_from_approval_status(
    execution_state: str,
) -> None:
    view = _view(
        request_id=41,
        approval_instance_id=301,
        execution_state=execution_state,
    )
    service, _approval_exception, status_port, _coordinator, _dispatcher = _service([view])

    detail = await service.get_detail(
        space_id=SPACE_ID,
        request_id=41,
        viewer=_viewer(),
    )

    assert detail.status == execution_state
    assert detail.approval_status == "approved"
    assert status_port.calls == [(TENANT_ID, (301,))]
    if execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED:
        assert detail.failure_reason == "parser unavailable"


async def test_list_batches_approval_status_but_projects_each_knowledge_request() -> None:
    views = [
        _view(
            request_id=index + 1,
            approval_instance_id=301 + index,
            execution_state=execution_state,
        )
        for index, execution_state in enumerate(BUSINESS_STATES)
    ]
    service, _approval_exception, status_port, _coordinator, _dispatcher = _service(views)

    result = await service.list_uploads(
        space_id=SPACE_ID,
        viewer=_viewer(),
        page_size=20,
    )

    assert [item.status for item in result.data] == list(BUSINESS_STATES)
    assert [item.approval_status for item in result.data] == ["approved"] * len(BUSINESS_STATES)
    assert status_port.calls == [(TENANT_ID, tuple(301 + index for index in range(len(BUSINESS_STATES))))]


async def test_failed_business_retry_reuses_request_and_approval_but_rotates_knowledge_token() -> None:
    view = _view(
        request_id=41,
        approval_instance_id=301,
        execution_state=KnowledgeSpaceFileChangeExecutionState.FAILED,
    )
    service, approval_exception, status_port, coordinator, dispatcher = _service([view])
    original_instance_id = int(view.request.approval_instance_id)
    original_token = str(view.request.execution_token)

    result = await service.retry_ingest(
        space_id=SPACE_ID,
        request_id=41,
        viewer=_viewer(),
    )

    assert result.request_id == 41
    assert result.approval_instance_id == original_instance_id
    assert result.status == KnowledgeSpaceFileChangeExecutionState.QUEUED
    assert result.approval_status == "approved"
    assert view.request.execution_token != original_token
    assert view.request.execution_token == "generation-2"
    assert coordinator.calls == [(TENANT_ID, 41)]
    assert dispatcher.calls == [(TENANT_ID, 41)]
    assert status_port.calls
    assert set(status_port.calls) == {(TENANT_ID, (301,))}
    approval_exception.retry_execute_failed_api.assert_not_awaited()
    service.approval_center.decide_instance_for_current_approver.assert_not_awaited()


def test_knowledge_api_does_not_import_approval_execution_owners() -> None:
    application_source = inspect.getsource(application_module)
    endpoint_source = inspect.getsource(endpoint_module.get_file_change_application_service)
    forbidden = (
        "approval.domain.models",
        "approval.domain.repositories",
        "ApprovalOutbox",
        "ApprovalExceptionService",
        "retry_execute_failed_api",
        "view.instance",
        "outbox_status",
        "outbox_error",
    )

    for token in forbidden:
        assert token not in application_source
        assert token not in endpoint_source
