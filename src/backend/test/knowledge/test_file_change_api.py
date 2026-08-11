from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalInstance,
    ApprovalOutbox,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import (
    KnowledgeSpaceInvalidCursorError,
    SpaceFileChangeInvalidStateError,
    SpaceFileChangeRequestNotFoundError,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.models.knowledge_space_upload_stage import KnowledgeSpaceUploadStage
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    BatchApprovalItemResult,
    BatchApprovalResp,
    FileChangeAction,
    FileChangeApprovalStatus,
    FileChangeResourceType,
    KnowledgeSpaceFileChangeDetailResp,
    KnowledgeSpacePendingUploadCursorResp,
    KnowledgeSpacePendingUploadItemResp,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_application_service import (
    FileChangeRequestView,
    KnowledgeSpaceFileChangeApplicationService,
)


def _user(*, user_id: int = 7, tenant_id: int = 42):
    return SimpleNamespace(
        user_id=user_id,
        user_name=f"user-{user_id}",
        tenant_id=tenant_id,
        user_role=[],
        is_admin=lambda: False,
    )


def _detail(*, status: str = FileChangeApprovalStatus.PENDING):
    return KnowledgeSpaceFileChangeDetailResp(
        request_id=41,
        space_id=101,
        action=FileChangeAction.UPLOAD,
        resource_type=FileChangeResourceType.STAGED_UPLOAD,
        upload_id="upload-41",
        resource_name="budget.pdf",
        file_size=123,
        content_hash="sha256",
        applicant_user_id=7,
        applicant_user_name="editor",
        approval_instance_id=31,
        status=status,
        can_approve=False,
        create_time=datetime(2026, 8, 11, 9, 0, 0),
    )


def _api_service():
    item = KnowledgeSpacePendingUploadItemResp(
        request_id=41,
        approval_instance_id=31,
        upload_id="upload-41",
        file_name="budget.pdf",
        file_size=123,
        content_hash="sha256",
        applicant_user_id=7,
        applicant_user_name="editor",
        status=FileChangeApprovalStatus.PENDING,
        can_approve=False,
        create_time=datetime(2026, 8, 11, 9, 0, 0),
    )
    return SimpleNamespace(
        list_uploads=AsyncMock(
            return_value=KnowledgeSpacePendingUploadCursorResp(
                data=[item],
                page_size=20,
                has_more=True,
                next_cursor="opaque-cursor",
            )
        ),
        get_detail=AsyncMock(return_value=_detail()),
        create_preview=AsyncMock(return_value={"preview_url": "https://preview.invalid/token"}),
        retry_ingest=AsyncMock(return_value=_detail(status=FileChangeApprovalStatus.PARSING)),
        cleanup_upload=AsyncMock(return_value=_detail(status=FileChangeApprovalStatus.WITHDRAWN)),
        batch_approve=AsyncMock(
            return_value=BatchApprovalResp(
                success_count=1,
                failure_count=1,
                items=[
                    BatchApprovalItemResult(
                        change_request_id=41,
                        approval_instance_id=31,
                        result="approved",
                        latest_status="approved",
                    ),
                    BatchApprovalItemResult(
                        change_request_id=42,
                        approval_instance_id=32,
                        result="failed",
                        latest_status="pending",
                        error_code=18076,
                        error_message="temporarily unavailable",
                        retryable=True,
                    ),
                ],
            )
        ),
    )


def _mount_app(service) -> FastAPI:
    from bisheng.knowledge.api.endpoints import knowledge_space_file_change as endpoint

    app = FastAPI()
    api = APIRouter(prefix="/api/v1")
    api.include_router(endpoint.router)
    app.include_router(api)
    app.dependency_overrides[endpoint.get_file_change_application_service] = lambda: service
    app.dependency_overrides[UserPayload.get_login_user] = lambda: _user()
    return app


def test_upload_cursor_list_and_detail_preview_contracts():
    service = _api_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        listing = client.get(
            "/api/v1/knowledge/space/101/file-changes/uploads",
            params={"status": "pending", "cursor": "cursor-1", "page_size": 20},
        )
        detail = client.get("/api/v1/knowledge/space/101/file-changes/41")
        preview = client.get("/api/v1/knowledge/space/101/file-changes/41/preview")

    assert listing.status_code == 200
    assert listing.json()["data"] == {
        "data": [
            {
                "request_id": 41,
                "approval_instance_id": 31,
                "upload_id": "upload-41",
                "file_name": "budget.pdf",
                "file_size": 123,
                "content_hash": "sha256",
                "applicant_user_id": 7,
                "applicant_user_name": "editor",
                "status": "pending",
                "can_approve": False,
                "failure_reason": None,
                "create_time": "2026-08-11T09:00:00",
                "update_time": None,
            }
        ],
        "page_size": 20,
        "has_more": True,
        "next_cursor": "opaque-cursor",
    }
    assert detail.status_code == 200
    assert detail.json()["data"]["action"] == "upload"
    assert preview.json()["data"] == {"preview_url": "https://preview.invalid/token"}
    list_call = service.list_uploads.await_args.kwargs
    assert {key: list_call[key] for key in ("space_id", "statuses", "cursor", "page_size")} == {
        "space_id": 101,
        "statuses": ["pending"],
        "cursor": "cursor-1",
        "page_size": 20,
    }
    assert (list_call["viewer"].user_id, list_call["viewer"].tenant_id) == (7, 42)
    assert service.get_detail.await_args.kwargs["request_id"] == 41
    assert service.create_preview.await_args.kwargs["request_id"] == 41


def test_upload_cursor_list_accepts_repeated_statuses_as_union():
    service = _api_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/knowledge/space/101/file-changes/uploads",
            params=[("status", "pending"), ("status", "parsing"), ("page_size", "20")],
        )

    assert response.status_code == 200
    assert service.list_uploads.await_args.kwargs["statuses"] == ["pending", "parsing"]


def test_retry_cleanup_and_batch_approve_return_latest_per_item_status():
    service = _api_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        retried = client.post("/api/v1/knowledge/space/101/file-changes/41/retry-ingest")
        cleaned = client.delete("/api/v1/knowledge/space/101/file-changes/41")
        batched = client.post(
            "/api/v1/knowledge/space/101/file-changes/batch-approve",
            json={"change_request_ids": [41, 42]},
        )

    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "parsing"
    assert cleaned.status_code == 200
    assert cleaned.json()["data"]["status"] == "withdrawn"
    assert batched.status_code == 200
    assert batched.json()["data"] == {
        "successCount": 1,
        "failureCount": 1,
        "items": [
            {
                "changeRequestId": 41,
                "approvalInstanceId": 31,
                "result": "approved",
                "latestStatus": "approved",
                "errorCode": None,
                "errorMessage": None,
                "retryable": False,
            },
            {
                "changeRequestId": 42,
                "approvalInstanceId": 32,
                "result": "failed",
                "latestStatus": "pending",
                "errorCode": 18076,
                "errorMessage": "temporarily unavailable",
                "retryable": True,
            },
        ],
    }
    assert service.retry_ingest.await_args.kwargs["request_id"] == 41
    assert service.cleanup_upload.await_args.kwargs["request_id"] == 41
    batch_call = service.batch_approve.await_args.kwargs
    assert batch_call["space_id"] == 101
    assert batch_call["approval_instance_ids"] is None
    assert batch_call["change_request_ids"] == [41, 42]
    assert (batch_call["viewer"].user_id, batch_call["viewer"].tenant_id) == (7, 42)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"approval_instance_ids": [], "change_request_ids": []},
        {"approval_instance_ids": [31], "change_request_ids": [41]},
        {"approval_instance_ids": [31, 31]},
    ],
)
def test_batch_approve_requires_one_nonempty_unique_id_source(payload):
    service = _api_service()
    app = _mount_app(service)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/knowledge/space/101/file-changes/batch-approve",
            json=payload,
        )

    assert response.status_code == 422
    service.batch_approve.assert_not_awaited()


def _request_view(
    *,
    applicant_user_id: int = 7,
    instance_status: str = "pending",
    outbox_status: str | None = None,
    exception_id: int | None = None,
    action: str = "upload",
    upload_id: str | None = "upload-41",
    executed_resource_id: int | None = None,
):
    request = SimpleNamespace(
        id=41,
        tenant_id=42,
        space_id=101,
        action=action,
        resource_type="staged_upload" if action == "upload" else "knowledge_file",
        resource_id=None if action == "upload" else 501,
        applicant_user_id=applicant_user_id,
        approval_instance_id=31,
        upload_stage_id=51 if upload_id else None,
        file_name="budget.pdf",
        file_size=123,
        content_hash="sha256",
        source_parent_id=None,
        target_space_id=None,
        target_parent_id=None,
        action_snapshot={"new_name": "budget-v2.pdf"},
        executed_resource_id=executed_resource_id,
        execution_state="failed" if instance_status == "execute_failed" else "not_started",
        execution_checkpoint={"failure_reason": "parser failed"},
        cleanup_state="none",
        create_time=datetime(2026, 8, 11, 9, 0, 0),
        update_time=datetime(2026, 8, 11, 9, 5, 0),
    )
    instance = SimpleNamespace(
        id=31,
        tenant_id=42,
        scenario_code="knowledge_space_file_change_request",
        applicant_user_id=applicant_user_id,
        applicant_user_name="editor",
        business_name="budget.pdf",
        status=instance_status,
        payload_snapshot={"space_id": 101, "change_request_id": 41},
    )
    return FileChangeRequestView(
        request=request,
        instance=instance,
        upload_id=upload_id,
        stage_state="attached" if upload_id else None,
        outbox_id=61 if outbox_status else None,
        outbox_status=outbox_status,
        outbox_error="parser failed" if outbox_status == "failed" else None,
        open_exception_id=exception_id,
        open_exception_type="execute_failed" if exception_id else None,
    )


def _application_service(*, view, current_approver: bool = False):
    repository = SimpleNamespace(
        get_request_view=AsyncMock(return_value=view),
        list_upload_request_views=AsyncMock(return_value=([view], False)),
        get_request_views_by_instance_ids=AsyncMock(return_value=[view]),
        get_request_views_by_request_ids=AsyncMock(return_value=[view]),
    )
    projection = AsyncMock(
        return_value={
            "status": "parse_failed" if view.instance.status == "execute_failed" else view.instance.status,
            "failure_reason": view.outbox_error,
        }
    )
    batch_projection = AsyncMock(
        return_value={
            int(view.request.id): {
                "status": "parse_failed" if view.instance.status == "execute_failed" else view.instance.status,
                "failure_reason": view.outbox_error,
            }
        }
    )
    return KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=current_approver),
        projection_loader=projection,
        batch_projection_loader=batch_projection,
        stage_preview=AsyncMock(return_value="https://preview.invalid/token"),
        formal_preview=AsyncMock(return_value={"preview_url": "https://formal.invalid/token"}),
        approval_center=SimpleNamespace(
            withdraw_instance=AsyncMock(return_value={"status": "withdrawn"}),
            decide_instance_for_current_approver=AsyncMock(return_value={"status": "approved"}),
        ),
        approval_exception=SimpleNamespace(
            cancel_exception_api=AsyncMock(return_value={"status": "cancelled"}),
            retry_execute_failed_api=AsyncMock(return_value=True),
        ),
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    ), repository


async def test_application_visibility_is_applicant_or_current_approver_and_former_is_denied():
    view = _request_view(applicant_user_id=8)
    former_service, _ = _application_service(view=view, current_approver=False)

    with pytest.raises(SpaceFileChangeRequestNotFoundError):
        await former_service.get_detail(space_id=101, request_id=41, viewer=_user(user_id=9))
    with pytest.raises(SpaceFileChangeRequestNotFoundError):
        await former_service.create_preview(space_id=101, request_id=41, viewer=_user(user_id=9))

    current_service, _ = _application_service(view=view, current_approver=True)
    detail = await current_service.get_detail(space_id=101, request_id=41, viewer=_user(user_id=9))
    assert detail.can_approve is True


async def test_applicant_who_later_becomes_manager_remains_visible_but_cannot_approve_own_request():
    service, _ = _application_service(view=_request_view(applicant_user_id=7), current_approver=True)

    detail = await service.get_detail(space_id=101, request_id=41, viewer=_user(user_id=7))
    listing = await service.list_uploads(
        space_id=101,
        viewer=_user(user_id=7),
        status=None,
        cursor=None,
        page_size=20,
    )

    assert detail.can_approve is False
    assert listing.data[0].can_approve is False


@pytest.mark.parametrize(
    ("instance_status", "exception_id", "expected"),
    [
        ("approved", None, "approved"),
        ("rejected", None, "rejected"),
        ("withdrawn", None, "withdrawn"),
        ("cancelled", None, "cancelled"),
        ("exception", 71, "approver_empty"),
    ],
)
async def test_f025_pre_execution_status_is_not_collapsed_by_business_projection(
    instance_status,
    exception_id,
    expected,
):
    view = _request_view(instance_status=instance_status, exception_id=exception_id)
    if exception_id is not None:
        view = FileChangeRequestView(
            request=view.request,
            instance=view.instance,
            upload_id=view.upload_id,
            stage_state=view.stage_state,
            outbox_id=view.outbox_id,
            outbox_status=view.outbox_status,
            outbox_error=view.outbox_error,
            open_exception_id=exception_id,
            open_exception_type="approver_empty",
        )
    service, _ = _application_service(view=view)
    service.projection_loader = AsyncMock(return_value={"status": "pending"})

    detail = await service.get_detail(space_id=101, request_id=41, viewer=_user())

    assert detail.status == expected


async def test_application_tenant_and_space_are_explicit_on_every_read():
    service, repository = _application_service(view=_request_view())

    await service.get_detail(space_id=101, request_id=41, viewer=_user())
    repository.get_request_view.assert_awaited_once_with(
        tenant_id=42,
        space_id=101,
        request_id=41,
    )


async def test_upload_list_rejects_malformed_or_cross_context_cursor():
    service, repository = _application_service(view=_request_view())

    with pytest.raises(KnowledgeSpaceInvalidCursorError):
        await service.list_uploads(
            space_id=101,
            viewer=_user(),
            status=None,
            cursor="not-a-valid-cursor",
            page_size=20,
        )

    repository.list_upload_request_views.assert_not_awaited()


async def test_upload_list_uses_one_batch_projection_for_multiple_rows_without_per_row_loader():
    first = _request_view(applicant_user_id=8, instance_status="executing")
    second = _request_view(applicant_user_id=9, instance_status="execute_failed")
    second.request.id = 42
    second.instance.id = 32
    repository = SimpleNamespace(
        get_request_view=AsyncMock(),
        list_upload_request_views=AsyncMock(return_value=([first, second], False)),
    )
    per_row_loader = AsyncMock(side_effect=AssertionError("list projection must be batched"))
    batch_loader = AsyncMock(
        return_value={
            41: {"status": "parsing"},
            42: {"status": "parse_failed", "failure_reason": "parser failed"},
        }
    )
    service = KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=True),
        projection_loader=per_row_loader,
        batch_projection_loader=batch_loader,
        stage_preview=AsyncMock(),
        formal_preview=AsyncMock(),
        approval_center=SimpleNamespace(),
        approval_exception=SimpleNamespace(),
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    )

    result = await service.list_uploads(
        space_id=101,
        viewer=_user(user_id=10),
        status=None,
        cursor=None,
        page_size=20,
    )

    assert [row.status for row in result.data] == ["parsing", "parse_failed"]
    batch_loader.assert_awaited_once_with([first, second])
    per_row_loader.assert_not_awaited()


async def test_upload_list_status_union_refills_from_raw_cursor_without_n_plus_one():
    first = _request_view(applicant_user_id=8, instance_status="executing")
    second = _request_view(applicant_user_id=8, instance_status="pending")
    second.request.id = 42
    second.instance.id = 32
    batches = [([first], True), ([second], False)]
    repository = SimpleNamespace(
        list_upload_request_views=AsyncMock(side_effect=batches),
    )
    batch_loader = AsyncMock(
        side_effect=[
            {41: {"status": "executing"}},
            {42: {"status": "pending"}},
        ]
    )
    service = KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=True),
        projection_loader=AsyncMock(side_effect=AssertionError("must use batch projection")),
        batch_projection_loader=batch_loader,
        stage_preview=AsyncMock(),
        formal_preview=AsyncMock(),
        approval_center=SimpleNamespace(),
        approval_exception=SimpleNamespace(),
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    )

    result = await service.list_uploads(
        space_id=101,
        viewer=_user(user_id=10),
        statuses=["pending", "parsing"],
        cursor=None,
        page_size=20,
    )

    assert [row.request_id for row in result.data] == [42]
    assert repository.list_upload_request_views.await_count == 2
    assert batch_loader.await_count == 2
    second_call = repository.list_upload_request_views.await_args_list[1].kwargs
    assert second_call["after_request_id"] == 41
    assert second_call["after_create_time"] == first.request.create_time


async def test_cleanup_withdraws_pending_then_cleans_without_delete_approval():
    service, _ = _application_service(view=_request_view(instance_status="pending"))

    result = await service.cleanup_upload(space_id=101, request_id=41, viewer=_user())

    service.approval_center.withdraw_instance.assert_awaited_once()
    service.terminal_cleanup.assert_awaited_once()
    service.failed_upload_cleanup.assert_not_awaited()
    assert result.status == FileChangeApprovalStatus.WITHDRAWN


async def test_cleanup_cancels_approver_empty_through_f025_exception_api():
    service, _ = _application_service(
        view=_request_view(instance_status="exception", exception_id=71),
    )

    result = await service.cleanup_upload(space_id=101, request_id=41, viewer=_user())

    service.approval_exception.cancel_exception_api.assert_awaited_once_with(
        exception_id=71,
        operator_user_id=7,
        reason="upload stage cleanup",
    )
    service.terminal_cleanup.assert_awaited_once()
    assert result.status == FileChangeApprovalStatus.CANCELLED


async def test_parse_failed_cleanup_uses_owner_cleanup_then_cancels_f025_exception():
    service, _ = _application_service(
        view=_request_view(
            instance_status="execute_failed",
            outbox_status="failed",
            exception_id=71,
            executed_resource_id=501,
        )
    )

    result = await service.cleanup_upload(space_id=101, request_id=41, viewer=_user())

    service.failed_upload_cleanup.assert_awaited_once_with(
        tenant_id=42,
        space_id=101,
        request_id=41,
        executed_resource_id=501,
    )
    service.approval_center.decide_instance_for_current_approver.assert_not_awaited()
    service.approval_exception.cancel_exception_api.assert_awaited_once_with(
        exception_id=71,
        operator_user_id=7,
        reason="upload stage cleanup",
    )
    assert result.status == FileChangeApprovalStatus.CANCELLED


async def test_retry_ingest_reuses_execute_failed_exception_and_original_approval():
    service, _ = _application_service(
        view=_request_view(
            instance_status="execute_failed",
            outbox_status="failed",
            exception_id=71,
            executed_resource_id=501,
        )
    )

    result = await service.retry_ingest(space_id=101, request_id=41, viewer=_user())

    service.approval_exception.retry_execute_failed_api.assert_awaited_once_with(
        exception_id=71,
        resolved_by_user_id=7,
        scenario_code="knowledge_space_file_change_request",
    )
    assert result.approval_instance_id == 31
    assert result.status == FileChangeApprovalStatus.PARSING


async def test_retry_and_cleanup_reject_non_upload_or_running_upload():
    rename_service, _ = _application_service(view=_request_view(action="rename", upload_id=None))
    with pytest.raises(SpaceFileChangeInvalidStateError):
        await rename_service.retry_ingest(space_id=101, request_id=41, viewer=_user())

    running_service, _ = _application_service(view=_request_view(instance_status="executing", outbox_status="deferred"))
    with pytest.raises(SpaceFileChangeInvalidStateError):
        await running_service.cleanup_upload(space_id=101, request_id=41, viewer=_user())


async def test_batch_approve_is_item_isolated_and_rereads_latest_status():
    first = _request_view(instance_status="pending")
    second = _request_view(instance_status="pending")
    second.request.id = 42
    second.request.approval_instance_id = 32
    second.instance.id = 32
    second.instance.payload_snapshot = {"space_id": 101, "change_request_id": 42}
    repository = SimpleNamespace(
        get_request_views_by_request_ids=AsyncMock(return_value=[first, second]),
        get_request_views_by_instance_ids=AsyncMock(),
        get_request_view=AsyncMock(
            side_effect=[
                _request_view(instance_status="approved"),
                second,
            ]
        ),
    )
    center = SimpleNamespace(
        decide_instance_for_current_approver=AsyncMock(
            side_effect=[{"status": "approved"}, SpaceFileChangeInvalidStateError()]
        )
    )
    service = KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=True),
        projection_loader=AsyncMock(side_effect=[{"status": "approved"}, {"status": "pending"}]),
        stage_preview=AsyncMock(),
        formal_preview=AsyncMock(),
        approval_center=center,
        approval_exception=SimpleNamespace(),
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    )

    result = await service.batch_approve(
        space_id=101,
        viewer=_user(user_id=9),
        approval_instance_ids=None,
        change_request_ids=[41, 42],
    )

    assert result.success_count == 1
    assert result.failure_count == 1
    assert [item.latest_status for item in result.items] == ["approved", "pending"]
    assert result.items[1].error_code == 18074
    assert result.items[1].retryable is True
    assert center.decide_instance_for_current_approver.await_count == 2


async def test_batch_approve_hides_known_request_from_former_approver_without_center_call():
    row = _request_view(applicant_user_id=8, instance_status="pending")
    repository = SimpleNamespace(
        get_request_views_by_request_ids=AsyncMock(return_value=[row]),
        get_request_views_by_instance_ids=AsyncMock(),
        get_request_view=AsyncMock(),
    )
    center = SimpleNamespace(decide_instance_for_current_approver=AsyncMock())
    service = KnowledgeSpaceFileChangeApplicationService(
        repository_factory=lambda: repository,
        current_approver_checker=AsyncMock(return_value=False),
        projection_loader=AsyncMock(),
        stage_preview=AsyncMock(),
        formal_preview=AsyncMock(),
        approval_center=center,
        approval_exception=SimpleNamespace(),
        terminal_cleanup=AsyncMock(),
        failed_upload_cleanup=AsyncMock(),
    )

    result = await service.batch_approve(
        space_id=101,
        viewer=_user(user_id=9),
        approval_instance_ids=None,
        change_request_ids=[41],
    )

    assert result.success_count == 0
    assert result.failure_count == 1
    assert result.items[0].latest_status == "not_found"
    assert result.items[0].error_code == 18073
    assert result.items[0].approval_instance_id == 0
    assert result.items[0].retryable is False
    center.decide_instance_for_current_approver.assert_not_awaited()
    repository.get_request_view.assert_not_awaited()


@pytest_asyncio.fixture
async def file_change_api_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        KnowledgeSpaceUploadStage.__table__,
        KnowledgeFile.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
        KnowledgeSpaceFileChangeExecutionStep.__table__,
        ApprovalInstance.__table__,
        ApprovalOutbox.__table__,
        ApprovalException.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))
    yield engine
    await engine.dispose()


async def _seed_read_view(engine, *, tenant_id: int, space_id: int, suffix: int):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        stage = KnowledgeSpaceUploadStage(
            tenant_id=tenant_id,
            upload_id=f"upload-{suffix}",
            space_id=space_id,
            uploader_user_id=7,
            object_name=f"private/object-{suffix}",
            file_name=f"file-{suffix}.pdf",
            file_size=10,
            content_hash=f"hash-{suffix}",
            state="attached",
            expire_at=datetime(2026, 9, 1),
        )
        session.add(stage)
        await session.flush()
        instance = ApprovalInstance(
            tenant_id=tenant_id,
            scenario_code="knowledge_space_file_change_request",
            scenario_name="file change",
            handler_key="knowledge_space_file_change_request",
            business_key=f"change:{suffix}",
            business_resource_type="knowledge_space_file_change",
            business_resource_id=str(suffix),
            business_name=f"file-{suffix}.pdf",
            applicant_user_id=7,
            applicant_user_name="editor",
            status="execute_failed",
            payload_snapshot={"space_id": space_id, "change_request_id": suffix},
            detail_snapshot={},
        )
        session.add(instance)
        await session.flush()
        request = KnowledgeSpaceFileChangeRequest(
            tenant_id=tenant_id,
            space_id=space_id,
            action="upload",
            resource_type="staged_upload",
            applicant_user_id=7,
            approval_instance_id=instance.id,
            upload_stage_id=stage.id,
            file_name=stage.file_name,
            file_size=stage.file_size,
            content_hash=stage.content_hash,
        )
        session.add(request)
        session.add(
            ApprovalOutbox(
                tenant_id=tenant_id,
                instance_id=instance.id,
                handler_key="knowledge_space_file_change_request",
                status="failed",
                error_summary="old failure",
            )
        )
        await session.flush()
        session.add(
            ApprovalOutbox(
                tenant_id=tenant_id,
                instance_id=instance.id,
                handler_key="knowledge_space_file_change_request",
                status="failed",
                error_summary="latest failure",
            )
        )
        session.add(
            ApprovalException(
                tenant_id=tenant_id,
                instance_id=instance.id,
                exception_type="execute_failed",
                status="open",
                detail={},
            )
        )
        await session.commit()
        return int(request.id), int(instance.id)


async def test_repository_read_projection_is_tenant_space_bound_and_uses_latest_outbox(file_change_api_engine):
    own_request_id, _ = await _seed_read_view(file_change_api_engine, tenant_id=42, space_id=101, suffix=41)
    await _seed_read_view(file_change_api_engine, tenant_id=43, space_id=101, suffix=42)
    factory = async_sessionmaker(file_change_api_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        own = await repository.get_request_view(tenant_id=42, space_id=101, request_id=own_request_id)
        foreign = await repository.get_request_view(tenant_id=42, space_id=101, request_id=own_request_id + 1)
        page, has_more = await repository.list_upload_request_views(
            tenant_id=42,
            space_id=101,
            applicant_user_id=7,
            instance_statuses=("execute_failed",),
            after_create_time=None,
            after_request_id=0,
            limit=1,
        )
        file_statuses, steps = await repository.load_business_projection_facts(
            tenant_id=42,
            requests=[page[0].request],
        )

    assert own is not None
    assert own.upload_id == "upload-41"
    assert own.outbox_error == "latest failure"
    assert own.open_exception_type == "execute_failed"
    assert foreign is None
    assert [row.request.id for row in page] == [own_request_id]
    assert has_more is False
    assert file_statuses == {}
    assert steps == {own_request_id: []}


async def test_repository_batch_projection_ignores_same_tenant_file_from_another_space(file_change_api_engine):
    request_id, _ = await _seed_read_view(file_change_api_engine, tenant_id=42, space_id=101, suffix=51)
    factory = async_sessionmaker(file_change_api_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        wrong_space_file = KnowledgeFile(
            tenant_id=42,
            knowledge_id=202,
            file_name="wrong-space.pdf",
            status=2,
        )
        session.add(wrong_space_file)
        await session.flush()
        request = await session.get(KnowledgeSpaceFileChangeRequest, request_id)
        assert request is not None
        request.executed_resource_id = wrong_space_file.id
        session.add(request)
        await session.commit()

    async with factory() as session:
        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        view = await repository.get_request_view(tenant_id=42, space_id=101, request_id=request_id)
        assert view is not None
        file_statuses, _ = await repository.load_business_projection_facts(
            tenant_id=42,
            requests=[view.request],
        )

    assert file_statuses == {}
