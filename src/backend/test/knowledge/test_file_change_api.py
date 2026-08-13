from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
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


def _user(*, user_id: int = 7, tenant_id: int = 42):
    return SimpleNamespace(
        user_id=user_id,
        user_name=f"user-{user_id}",
        tenant_id=tenant_id,
        user_role=[],
        is_admin=lambda: False,
    )


def _detail(*, status: str = FileChangeApprovalStatus.QUEUED):
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
        approval_status="approved",
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
        parent_id=55,
        applicant_user_id=7,
        applicant_user_name="editor",
        status=FileChangeApprovalStatus.QUEUED,
        approval_status="approved",
        can_approve=False,
        create_time=datetime(2026, 8, 11, 9, 0, 0),
    )
    return SimpleNamespace(
        list_uploads=AsyncMock(
            return_value=KnowledgeSpacePendingUploadCursorResp(
                data=[item], page_size=20, has_more=True, next_cursor="opaque-cursor"
            )
        ),
        get_detail=AsyncMock(return_value=_detail()),
        create_preview=AsyncMock(return_value={"preview_url": "https://preview.invalid/token"}),
        retry_ingest=AsyncMock(return_value=_detail(status=FileChangeApprovalStatus.QUEUED)),
        cleanup_upload=AsyncMock(return_value=_detail(status=FileChangeApprovalStatus.CLOSED)),
        decide_upload=AsyncMock(return_value=_detail()),
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


def test_upload_list_and_detail_keep_business_and_approval_status_separate():
    service = _api_service()
    with TestClient(_mount_app(service)) as client:
        listing = client.get(
            "/api/v1/knowledge/space/101/file-changes/uploads",
            params={"parent_id": 55, "status": "queued", "page_size": 20},
        )
        detail = client.get("/api/v1/knowledge/space/101/file-changes/41")

    assert listing.status_code == 200
    item = listing.json()["data"]["data"][0]
    assert item["status"] == "queued"
    assert item["approval_status"] == "approved"
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "queued"
    assert detail.json()["data"]["approval_status"] == "approved"
    service.list_uploads.assert_awaited_once_with(
        space_id=101,
        parent_id=55,
        viewer=ANY,
        statuses=["queued"],
        cursor=None,
        page_size=20,
    )


def test_preview_retry_cleanup_and_decision_routes_delegate_to_application_service():
    service = _api_service()
    with TestClient(_mount_app(service)) as client:
        preview = client.get("/api/v1/knowledge/space/101/file-changes/41/preview")
        retry = client.post("/api/v1/knowledge/space/101/file-changes/41/retry-ingest")
        cleanup = client.delete("/api/v1/knowledge/space/101/file-changes/41")
        decision = client.post(
            "/api/v1/knowledge/space/101/file-changes/41/decision",
            json={"action": "approve", "comment": "ok"},
        )

    assert preview.status_code == retry.status_code == cleanup.status_code == decision.status_code == 200
    assert retry.json()["data"]["status"] == "queued"
    assert cleanup.json()["data"]["status"] == "closed"
    service.retry_ingest.assert_awaited_once()
    service.cleanup_upload.assert_awaited_once()
    service.decide_upload.assert_awaited_once()


def test_batch_approval_contract_remains_approval_fact_only():
    service = _api_service()
    with TestClient(_mount_app(service)) as client:
        response = client.post(
            "/api/v1/knowledge/space/101/file-changes/batch-approve",
            json={"change_request_ids": [41, 42]},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["successCount"] == 1
    assert payload["failureCount"] == 1
    assert "business_status_projection" not in str(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"approval_instance_ids": [31], "change_request_ids": [41]},
        {"approval_instance_ids": [31, 31]},
    ],
)
def test_batch_approve_requires_one_nonempty_unique_id_source(payload):
    service = _api_service()
    with TestClient(_mount_app(service)) as client:
        response = client.post(
            "/api/v1/knowledge/space/101/file-changes/batch-approve",
            json=payload,
        )

    assert response.status_code == 422
    service.batch_approve.assert_not_awaited()


def test_caller_controlled_tenant_is_rejected():
    service = _api_service()
    with TestClient(_mount_app(service)) as client:
        response = client.get(
            "/api/v1/knowledge/space/101/file-changes/41",
            params={"tenant_id": 99},
        )

    assert response.status_code == 422
    service.get_detail.assert_not_awaited()
