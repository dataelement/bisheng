from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bisheng.approval.api.dependencies import (
    get_approval_decision_application_service,
    get_approval_status_read_port,
)
from bisheng.approval.domain.ports.approval_status_reader import ApprovalStatusReadPort
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge_space import SpaceFileChangeRequestNotFoundError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.knowledge.api.dependencies import (
    get_knowledge_space_service,
    get_knowledge_space_upload_stage_service,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    BatchApprovalReq,
    BatchApprovalResp,
    KnowledgeSpaceFileChangeConfigurationResp,
    KnowledgeSpaceFileChangeConfigurationUpdateReq,
    KnowledgeSpaceFileChangeDecisionReq,
    KnowledgeSpaceFileChangeDetailResp,
    KnowledgeSpaceFileChangePolicyResp,
    KnowledgeSpaceFileChangePolicyUpdateReq,
    KnowledgeSpaceFileChangeSettingResp,
    KnowledgeSpaceFileChangeSettingsResp,
    KnowledgeSpaceFileChangeSettingUpdateReq,
    KnowledgeSpacePendingUploadCursorResp,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_application_service import (
    KnowledgeSpaceFileChangeApplicationService,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_policy_service import (
    KnowledgeSpaceFileChangePolicyService,
)

router = APIRouter()
admin_router = APIRouter(
    prefix="/knowledge/space/admin",
    tags=["knowledge_space_file_change_policy"],
)
file_change_router = APIRouter(
    prefix="/knowledge/space/{space_id}/file-changes",
    tags=["knowledge_space_file_change"],
)


def get_file_change_policy_service() -> KnowledgeSpaceFileChangePolicyService:
    return KnowledgeSpaceFileChangePolicyService()


async def get_file_change_application_service(
    owner_service=Depends(get_knowledge_space_service),
    stage_service=Depends(get_knowledge_space_upload_stage_service),
    approval_decision_service=Depends(get_approval_decision_application_service),
    approval_status_port: ApprovalStatusReadPort = Depends(get_approval_status_read_port),
) -> KnowledgeSpaceFileChangeApplicationService:
    """Compose F046 views with Knowledge owners and F025 public commands."""

    from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
        KnowledgeSpaceFileChangeApproverResolver,
    )
    from bisheng.knowledge.domain.services.knowledge_space_file_change_execution_coordinator import (
        KnowledgeSpaceFileChangeExecutionCoordinator,
    )
    from bisheng.knowledge.domain.services.knowledge_space_file_change_terminal_cleanup_service import (
        KnowledgeSpaceFileChangeTerminalCleanupService,
    )
    from bisheng.worker.knowledge.file_change_tasks import (
        CeleryKnowledgeSpaceFileChangeDispatcher,
    )

    async def cleanup_failed_upload(
        *,
        tenant_id: int,
        space_id: int,
        request_id: int,
        executed_resource_id: int,
    ) -> None:
        await owner_service.cleanup_failed_file_change_upload(
            tenant_id=int(tenant_id),
            space_id=int(space_id),
            request_id=int(request_id),
            executed_resource_id=int(executed_resource_id),
        )

    return KnowledgeSpaceFileChangeApplicationService(
        current_approver_checker=KnowledgeSpaceFileChangeApproverResolver.is_current_approver,
        projection_loader=None,
        stage_preview=stage_service.create_preview_url,
        formal_preview=owner_service.get_file_preview,
        approval_center=approval_decision_service,
        approval_status_port=approval_status_port,
        execution_coordinator=KnowledgeSpaceFileChangeExecutionCoordinator(),
        execution_dispatcher=CeleryKnowledgeSpaceFileChangeDispatcher(),
        terminal_cleanup=KnowledgeSpaceFileChangeTerminalCleanupService().cleanup,
        failed_upload_cleanup=cleanup_failed_upload,
    )


def reject_caller_tenant(request: Request) -> None:
    if "tenant_id" in request.query_params:
        raise HTTPException(status_code=422, detail="tenant_id is server controlled")


AdminUser = Depends(UserPayload.get_tenant_admin_user)
RejectCallerTenant = Depends(reject_caller_tenant)


@admin_router.get(
    "/file-change-policy",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangePolicyResp],
)
async def get_file_change_policy(
    _: UserPayload = AdminUser,
    __: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangePolicyService = Depends(get_file_change_policy_service),
) -> Any:
    return resp_200(await service.get_policy())


@admin_router.put(
    "/file-change-policy",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangePolicyResp],
)
async def update_file_change_policy(
    request: KnowledgeSpaceFileChangePolicyUpdateReq,
    _: UserPayload = AdminUser,
    __: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangePolicyService = Depends(get_file_change_policy_service),
) -> Any:
    return resp_200(
        await service.save_policy(
            enabled=request.enabled,
            scope=request.scope.value,
        )
    )


@admin_router.put(
    "/file-change-configuration",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeConfigurationResp],
)
async def update_file_change_configuration(
    request: KnowledgeSpaceFileChangeConfigurationUpdateReq,
    _: UserPayload = AdminUser,
    __: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangePolicyService = Depends(get_file_change_policy_service),
) -> Any:
    try:
        return resp_200(
            await service.save_configuration(
                policy=request.policy,
                settings=request.settings,
            )
        )
    except LookupError:
        error = SpaceFileChangeRequestNotFoundError()
        return JSONResponse(
            status_code=404,
            content=error.return_resp_instance().model_dump(mode="json"),
        )


@admin_router.get(
    "/file-change-settings",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeSettingsResp],
)
async def list_file_change_settings(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: UserPayload = AdminUser,
    __: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangePolicyService = Depends(get_file_change_policy_service),
) -> Any:
    return resp_200(
        await service.get_space_settings_page(
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )


@admin_router.put(
    "/file-change-settings/{space_id}",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeSettingResp],
)
async def update_file_change_setting(
    space_id: int,
    request: KnowledgeSpaceFileChangeSettingUpdateReq,
    _: UserPayload = AdminUser,
    __: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangePolicyService = Depends(get_file_change_policy_service),
) -> Any:
    try:
        return resp_200(
            await service.update_space_setting(
                space_id=space_id,
                approval_required=request.approval_required,
            )
        )
    except LookupError:
        error = SpaceFileChangeRequestNotFoundError()
        return JSONResponse(
            status_code=404,
            content=error.return_resp_instance().model_dump(mode="json"),
        )


CurrentUser = Depends(UserPayload.get_login_user)


@file_change_router.get(
    "/uploads",
    response_model=UnifiedResponseModel[KnowledgeSpacePendingUploadCursorResp],
)
async def list_pending_uploads(
    space_id: int,
    parent_id: int | None = Query(default=None, ge=1),
    status: list[str] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(
        await service.list_uploads(
            space_id=space_id,
            parent_id=parent_id,
            viewer=viewer,
            statuses=status,
            cursor=cursor,
            page_size=page_size,
        )
    )


@file_change_router.post(
    "/{request_id}/decision",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeDetailResp],
)
async def decide_file_change_upload(
    space_id: int,
    request_id: int,
    body: KnowledgeSpaceFileChangeDecisionReq,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(
        await service.decide_upload(
            space_id=space_id,
            request_id=request_id,
            action=body.action,
            comment=body.comment,
            viewer=viewer,
        )
    )


@file_change_router.post(
    "/batch-approve",
    response_model=UnifiedResponseModel[BatchApprovalResp],
)
async def batch_approve_file_changes(
    space_id: int,
    body: BatchApprovalReq,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(
        await service.batch_approve(
            space_id=space_id,
            viewer=viewer,
            approval_instance_ids=body.approval_instance_ids,
            change_request_ids=body.change_request_ids,
        )
    )


@file_change_router.get(
    "/{request_id}",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeDetailResp],
)
async def get_file_change_detail(
    space_id: int,
    request_id: int,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(await service.get_detail(space_id=space_id, request_id=request_id, viewer=viewer))


@file_change_router.get("/{request_id}/preview")
async def preview_file_change_upload(
    space_id: int,
    request_id: int,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(await service.create_preview(space_id=space_id, request_id=request_id, viewer=viewer))


@file_change_router.post(
    "/{request_id}/retry-ingest",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeDetailResp],
)
async def retry_file_change_ingest(
    space_id: int,
    request_id: int,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(await service.retry_ingest(space_id=space_id, request_id=request_id, viewer=viewer))


@file_change_router.delete(
    "/{request_id}",
    response_model=UnifiedResponseModel[KnowledgeSpaceFileChangeDetailResp],
)
async def cleanup_file_change_upload(
    space_id: int,
    request_id: int,
    viewer: UserPayload = CurrentUser,
    _: None = RejectCallerTenant,
    service: KnowledgeSpaceFileChangeApplicationService = Depends(get_file_change_application_service),
) -> Any:
    return resp_200(await service.cleanup_upload(space_id=space_id, request_id=request_id, viewer=viewer))


router.include_router(admin_router)
router.include_router(file_change_router)
