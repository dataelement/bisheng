from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from loguru import logger
from starlette.responses import StreamingResponse

from bisheng.admin.application.tenant_scope import require_expected_management_tenant, resolve_management_scope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.admin_scope import AdminScopeChangedError
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.api import SSEResponse, resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.api.dependencies import (
    get_knowledge_document_version_repository,
    get_knowledge_space_chat_service,
    get_knowledge_space_service,
)
from bisheng.knowledge.application import provider_upload_v1 as uploads
from bisheng.knowledge.application import provider_v1_runtime as provider
from bisheng.knowledge.application.creation_settings import get_space_creation_settings
from bisheng.knowledge.application.provider_folder_upload import (
    ProviderFolderPrepareRequest,
    prepare_folder_tree,
)
from bisheng.knowledge.application.provider_provisioning import SpaceSpec
from bisheng.knowledge.application.provider_reads import ReadHandle
from bisheng.knowledge.application.provider_v1_listing import listing as provider_listing
from bisheng.knowledge.application.upload_registration import register_owned_upload
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileOrderField, SpaceFileOrderSort
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    BatchDeleteReq,
    BatchDownloadReq,
    ChatFolderReq,
    ChatReq,
    CreationSettingsPreviewReq,
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceVisibilityReq,
    DepartmentProviderBatchStatusReq,
    DepartmentProviderPreviewReq,
    FileCreateReq,
    FileEncodingUpdateReq,
    FileMoveReq,
    FileRenameReq,
    FolderCreateReq,
    FolderRenameReq,
    FolderUploadReq,
    KnowledgeChatSessionResponse,
    KnowledgeSpaceCreateReq,
    KnowledgeSpaceUpdateReq,
    ProviderSettingsPatch,
    WebLinkCreateReq,
)
from bisheng.knowledge.domain.schemas.work_retrieval import WorkRetrievalRequest
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService,
)
from bisheng.knowledge.domain.services.knowledge_creation_policy import KnowledgeCreationPolicy
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)
from bisheng.knowledge.domain.services.knowledge_space_service import (
    KnowledgeSpaceService,
)
from bisheng.knowledge.domain.services.work_retrieval import retrieve_workspace_chunks
from bisheng.workstation.domain.services.workstation_service import WorkStationService

router = APIRouter(prefix="/knowledge/space", tags=["knowledge_space"])

SPACE_FILE_PREVIEW_PERMISSION_ACTION = "visible"
SPACE_FILE_DOWNLOAD_PERMISSION_ACTION = "download"


async def require_native_space(space_id: int, _: UserPayload = Depends(UserPayload.get_login_user)):
    if await provider.resolve_space_route(space_id):
        raise provider.ProviderFeatureUnavailable()


@router.post("/retrieve")
async def retrieve_workspace_context(
    req: WorkRetrievalRequest,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
    version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
) -> Any:
    """Return permission-filtered context to an authenticated workspace task."""
    from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService

    await WorkCapabilitiesService(svc.login_user).ensure_tool_key_enabled("bisheng_knowledge_search")
    svc.version_repo = version_repo
    return resp_200(await retrieve_workspace_chunks(svc, req))


# ──────────────────────────── Space CRUD ──────────────────────────────────────


@router.get("/provider-models")
async def list_provider_models(login_user: UserPayload = Depends(UserPayload.get_login_user)) -> Any:
    from bisheng.knowledge.application.provider_external_token import provider_external_identity
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, list_models

    tenant = get_current_tenant_id()
    engine = await build_provisioning(login_user)
    try:
        if await engine.authorize(tenant, login_user.user_id, "create_personal", None) is not True:
            raise PermissionError("space action denied")
        with provider_external_identity(login_user.user_id):
            models = await list_models(tenant)
    except (ValueError, PermissionError, ConnectionError, TimeoutError) as exc:
        raise provider.ProviderFeatureUnavailable() from exc
    return resp_200(models)


@router.get("/provider-extract-templates")
async def list_provider_extract_templates(login_user: UserPayload = Depends(UserPayload.get_login_user)) -> Any:
    from bisheng.knowledge.application.provider_external_token import provider_external_identity
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, list_extract_templates

    tenant = get_current_tenant_id()
    engine = await build_provisioning(login_user)
    try:
        if await engine.authorize(tenant, login_user.user_id, "create_personal", None) is not True:
            raise PermissionError("space action denied")
        with provider_external_identity(login_user.user_id):
            templates = await list_extract_templates(tenant)
    except (ValueError, PermissionError, ConnectionError, TimeoutError) as exc:
        raise provider.ProviderFeatureUnavailable() from exc
    return resp_200(templates)


@router.get("/creation-settings")
async def get_creation_settings(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    provider_key: Literal["native"] = "native",
) -> Any:
    async with get_async_db_session() as session:
        return resp_200(await get_space_creation_settings(login_user, session=session))


@router.post("/creation-settings")
async def preview_creation_settings(
    req: CreationSettingsPreviewReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, load_preset

    tenant = get_current_tenant_id()
    provisioning = await build_provisioning(login_user)
    try:
        summary = await provisioning.preview(
            tenant_id=tenant,
            actor=login_user.user_id,
            space=SpaceSpec(name="preview"),
            preset=await load_preset(tenant, req.provider_selection),
        )
    except (ValueError, PermissionError, ConnectionError, TimeoutError) as exc:
        logger.opt(exception=True).warning(
            "weknora creation-settings probe failed tenant={} actor={} extract_template={} err={}",
            tenant,
            login_user.user_id,
            req.provider_selection.extract_template_kb_id,
            exc,
        )
        raise provider.ProviderFeatureUnavailable() from exc
    return resp_200(summary)


# No `@require_quota` here, unlike assistant / workflow / tool. Those have no
# domain-level quota check, so the decorator is their only gate. Knowledge spaces
# gate inside `KnowledgeSpaceService._assert_space_creation_quota`, which also
# covers the two paths the decorator cannot reach (the v2 open API in
# `open_endpoints/filelib.py` and the F050 prospective-grant GETs). Keeping the
# decorator would only duplicate the COUNT and — because it runs first — replace
# the domain error 18001 ("创建知识空间数量已达上限") with the generic 19402
# ("当前角色配额已用尽"), losing which resource actually ran out.
@router.post("")
async def create_space(
    req: KnowledgeSpaceCreateReq,
    request: Request,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    if req.provider_key == "weknora":
        from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, load_preset

        tenant = await _expected_provider_tenant(request, login_user)
        if (
            not req.creation_request_id
            or req.preset_summary is None
            or req.provider_selection is None
            or req.embedding_model_id is not None
            or req.processing_defaults is not None
            or req.initial_permissions is not None
            or req.auto_tag_enabled
            or req.auto_tag_library_id is not None
            or req.auto_tag_custom_tags is not None
        ):
            raise provider.ProviderFeatureUnavailable()
        engine = await build_provisioning(login_user)
        receipt = await engine.create(
            tenant_id=tenant,
            expected_tenant=tenant,
            actor=login_user.user_id,
            key=req.creation_request_id,
            space=SpaceSpec(
                name=req.name,
                description=req.description,
                icon=req.icon,
                auth_type=req.auth_type.value,
                is_released=req.is_released,
            ),
            preset=await load_preset(tenant, req.provider_selection),
            summary=req.preset_summary,
        )
        return resp_200(_receipt(receipt))
    if req.preset_summary is not None or req.provider_selection is not None:
        raise provider.ProviderFeatureUnavailable()
    advanced = {}
    if req.embedding_model_id is not None or req.processing_defaults is not None:
        scope = await resolve_management_scope(login_user.user_id, is_super=login_user.is_global_super, for_write=True)
        require_expected_management_tenant(request.headers.get("X-Management-Tenant"), scope)
        if scope.tenant_id != get_current_tenant_id():
            raise AdminScopeChangedError(scope_tenant_id=scope.tenant_id)
        advanced = {
            "embedding_model_id": req.embedding_model_id,
            "processing_defaults": req.processing_defaults,
            "web_creation_context": await KnowledgeCreationPolicy.prepare(login_user),
        }
    space = await svc.create_knowledge_space(
        name=req.name,
        description=req.description,
        icon=req.icon,
        auth_type=req.auth_type,
        is_released=req.is_released,
        auto_tag_enabled=req.auto_tag_enabled,
        auto_tag_library_id=req.auto_tag_library_id,
        auto_tag_custom_tags=req.auto_tag_custom_tags,
        creation_request_id=req.creation_request_id,
        initial_permissions=req.initial_permissions,
        **advanced,
    )
    return resp_200(space)


@router.get("/list")
async def list_visible_spaces(
    keyword: str | None = None,
    page_size: int = Query(default=20, ge=1, le=200),
    cursor: str | None = None,
    has_abnormal: bool | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(
        await svc.list_visible_spaces(keyword=keyword, page_size=page_size, cursor=cursor, has_abnormal=has_abnormal)
    )


@router.get("/admin/list")
async def list_admin_spaces(
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    has_abnormal: bool | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(
        await svc.list_admin_spaces(keyword=keyword, page=page, page_size=page_size, has_abnormal=has_abnormal)
    )


@router.get("/auto-tag-visibility")
async def get_auto_tag_visibility(
    _: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    """Whether the knowledge-space auto-tag UI is enabled for the current tenant.

    Read-only for any logged-in user; respects the same root→tenant inheritance
    as the rest of the workstation knowledge-space config.
    """
    (
        cfg,
        _inherited,
        _src,
        _has_override,
    ) = await WorkStationService.get_knowledge_space_config_with_meta()
    visible = bool(getattr(cfg, "auto_tag_visible", False)) if cfg else False
    return resp_200({"visible": visible})


@router.get("/creation-permission-context")
async def get_creation_permission_context(
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.get_creation_permission_context())


@router.get("/creation-grant-subjects/users")
async def list_creation_grant_users(
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.list_creation_grant_users(keyword=keyword, page=page, page_size=page_size))


@router.get("/creation-grant-subjects/user-groups")
async def list_creation_grant_user_groups(
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.list_creation_grant_user_groups(keyword=keyword, page=page, page_size=page_size))


@router.get("/creation-grant-subjects/departments/children")
async def list_creation_grant_department_children(
    parent_id: int | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.list_creation_grant_department_children(parent_id=parent_id))


@router.get("/creation-grant-subjects/departments/search")
async def search_creation_grant_departments(
    keyword: str = "",
    limit: int = Query(50, ge=1, le=200),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.search_creation_grant_departments(keyword=keyword, limit=limit))


@router.get("/creation-grant-subjects/departments/{department_id}/path-tree")
async def get_creation_grant_department_path(
    department_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.get_creation_grant_department_path(department_id))


def _receipt(op):
    return {"operation_id": op.operation_id, "space_id": op.space_id, "state": op.state}


async def _expected_provider_tenant(request, login_user):
    scope = await resolve_management_scope(login_user.user_id, is_super=login_user.is_global_super, for_write=True)
    require_expected_management_tenant(request.headers.get("X-Management-Tenant"), scope)
    if scope.tenant_id != get_current_tenant_id():
        raise AdminScopeChangedError(scope_tenant_id=scope.tenant_id)
    return scope.tenant_id


@router.post("/department/provider-preview")
async def preview_department_provider(
    req: DepartmentProviderPreviewReq, request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)
) -> Any:
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, load_preset

    tenant = await _expected_provider_tenant(request, login_user)
    await DepartmentKnowledgeSpaceService._ensure_tenant_admin(login_user)
    engine = await build_provisioning(login_user)
    try:
        summary = await engine.preview(
            tenant_id=tenant,
            actor=login_user.user_id,
            space=SpaceSpec(name="preview", department_id=req.department_id),
            preset=await load_preset(tenant, req.provider_selection),
        )
    except (ValueError, PermissionError, ConnectionError, TimeoutError) as exc:
        raise provider.ProviderFeatureUnavailable() from exc
    return resp_200({"preset_summary": summary})


@router.post("/department/batch-status")
async def read_department_batch_status(
    req: DepartmentProviderBatchStatusReq,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    tenant = await _expected_provider_tenant(request, login_user)
    items = await DepartmentKnowledgeSpaceService.read_external_batch_status(
        login_user=login_user, tenant_id=tenant, key=req.request_key, department_ids=req.department_ids
    )
    return resp_200({"items": items})


_UploadKey = Annotated[str, Path(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]


@router.post(
    "/{space_id}/provider-uploads/{request_key}",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_provider_item(
    space_id: int,
    request_key: _UploadKey,
    request: Request,
    file_name: Annotated[str, Query(min_length=1, max_length=255, pattern=r"^[^/\\\\\x00-\x1f\x7f]+$")],
    byte_count: Annotated[int, Query(ge=0, lt=2**63)],
    sha256: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")],
    parent_id: Annotated[int | None, Query(gt=0)] = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/octet-stream":
        raise HTTPException(status_code=415, detail="Expected application/octet-stream")
    if file_name in (".", "..") or not file_name.strip():
        raise HTTPException(status_code=422, detail="Invalid file name")
    return resp_200(
        await uploads.create_upload(
            svc,
            space_id,
            request_key,
            parent_id=parent_id,
            file_name=file_name,
            byte_count=byte_count,
            sha256=sha256,
            stream=request.stream,
        )
    )


@router.get("/{space_id}/provider-uploads/{request_key}")
async def read_provider_upload_item(
    space_id: int,
    request_key: _UploadKey,
    parent_id: Annotated[int | None, Query(gt=0)] = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    return resp_200(await uploads.read_upload(svc, space_id, request_key, parent_id=parent_id))


@router.post("/{space_id}/provider-folder-uploads/prepare")
async def prepare_provider_folder_upload(
    space_id: int,
    body: ProviderFolderPrepareRequest,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    return resp_200(await prepare_folder_tree(svc, space_id, body))


@router.get("/{space_id}/capabilities")
async def get_capabilities(space_id: int, svc: KnowledgeSpaceService = Depends(get_knowledge_space_service)):
    await svc._require_action("knowledge_space", space_id, "visible")
    route = await provider.resolve_space_route(space_id)
    if route is None:
        states = {"preview": "supported", "download": "supported", "bbox": "conditional", "listing": "supported"}
    else:
        upload_state = "supported" if await uploads.upload_admission(svc, route) else "unverified"
        states = {
            "preview": "conditional",
            "preview_representation": "text_excerpt",
            "download": "conditional",
            "bbox": "unsupported",
            "listing": "supported",
            "body_search": "unsupported",
            "tag_filter": "unsupported",
            "tag_vocabulary": "conditional",
            "tag_selection": "conditional",
            "tag_edit": "conditional",  # Requires a verified file-specific manual-tags-v1 contract.
            "batch_download": "unsupported",
            "settings_write": "unverified",
            "upload": upload_state,
            "folder_upload": upload_state,
            "preview_edit": "unsupported",
        }
    return resp_200(
        {
            "provider_key": route.provider_key if route else "native",
            "capability_revision": route.capability_revision if route else 1,
            **({"generation": route.generation} if route else {}),
            "capabilities": states,
        }
    )


@router.get("/{space_id}/settings")
async def read_provider_settings(space_id: int, svc: KnowledgeSpaceService = Depends(get_knowledge_space_service)):
    await svc._require_action("knowledge_space", space_id, "visible")
    if await provider.resolve_space_route(space_id) is None:
        raise provider.ProviderFeatureUnavailable()
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning

    engine = await build_provisioning(svc.login_user)
    return resp_200(
        await engine.read_settings(tenant_id=get_current_tenant_id(), actor=svc.login_user.user_id, space_id=space_id)
    )


@router.put("/{space_id}/settings")
async def change_provider_settings(
    space_id: int,
    req: ProviderSettingsPatch,
    request: Request,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    tenant = await _expected_provider_tenant(request, svc.login_user)
    await svc._require_action("knowledge_space", space_id, "edit")
    if await provider.resolve_space_route(space_id) is None:
        raise provider.ProviderFeatureUnavailable()
    from bisheng.knowledge.application.provider_provision_runtime import build_provisioning

    engine = await build_provisioning(svc.login_user)
    return resp_200(
        _receipt(
            await engine.settings(
                tenant_id=tenant,
                expected_tenant=tenant,
                actor=svc.login_user.user_id,
                space_id=space_id,
                key=req.request_key,
                expected_revision=req.expected_revision,
                patch=req.patch,
            )
        )
    )


@router.get("/{space_id}/info")
async def get_space_info(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space_info = await svc.get_space_info(space_id)
    return resp_200(space_info)


@router.put("/{space_id}", dependencies=[Depends(require_native_space)])
async def update_space(
    space_id: int,
    req: KnowledgeSpaceUpdateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    space = await svc.update_knowledge_space(
        space_id=space_id,
        name=req.name,
        description=req.description,
        icon=req.icon,
        auth_type=req.auth_type,
        is_released=req.is_released,
        auto_tag_enabled=req.auto_tag_enabled,
        auto_tag_library_id=req.auto_tag_library_id,
        auto_tag_custom_tags=req.auto_tag_custom_tags,
    )
    return resp_200(space)


@router.post("/{space_id}/set-pin")
async def set_channel_pin(
    space_id: int,
    is_pined: bool = Body(default=True, embed=True),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    """Set channel pin status."""
    await svc.pin_space(space_id, is_pined)
    return resp_200(data=True)


@router.delete("/{space_id}", dependencies=[Depends(require_native_space)])
async def delete_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    await svc.delete_space(space_id)
    return resp_200()


# ──────────────────────────── Space Listings ───────────────────────────────────


@router.get("/uploadable")
async def list_uploadable_spaces(
    keyword: str | None = Query(default=None, description="substring filter on space name"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """F028: list knowledge spaces where the user has ``upload_file`` permission.

    Powers the ``AddToKnowledgeModal`` data source for the workstation
    conversation-export flow. Returns a flat list (no cursor pagination —
    INV-6 豁免, see spec §3): per-user uploadable spaces typically number
    in the dozens. Body returns ``{"data": [{"id", "name", "icon", "description"}]}``.
    """
    spaces = await svc.list_uploadable_spaces(keyword=keyword)
    return resp_200(
        {
            "data": [
                {
                    "id": s.id,
                    "name": s.name or "",
                    "icon": None,
                    "description": s.description,
                }
                for s in spaces
            ]
        }
    )


@router.get("/mine")
async def get_my_created_spaces(
    order_by: str = "update_time",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_created_spaces(order_by)
    return resp_200(spaces)


@router.get("/managed")
async def get_my_managed_spaces(
    order_by: str = "name",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_managed_spaces(order_by)
    return resp_200(spaces)


@router.get("/joined")
async def get_my_followed_spaces(
    order_by: str = "update_time",
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_my_followed_spaces(order_by)
    return resp_200(spaces)


@router.get("/department")
async def get_my_department_spaces(
    request: Request,
    order_by: str = "update_time",
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    spaces = await DepartmentKnowledgeSpaceService.get_user_department_spaces(
        request=request,
        login_user=login_user,
        order_by=order_by,
    )
    return resp_200(spaces)


@router.get("/department/all")
async def get_all_department_spaces(
    request: Request,
    order_by: str = "update_time",
    include_hidden: bool = False,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        spaces = await DepartmentKnowledgeSpaceService.get_all_department_spaces(
            request=request,
            login_user=login_user,
            order_by=order_by,
            include_hidden=include_hidden,
        )
        return resp_200(spaces)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post("/department/visibility")
async def set_department_spaces_visibility(
    req: DepartmentKnowledgeSpaceVisibilityReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        changed = await DepartmentKnowledgeSpaceService.set_spaces_hidden(
            login_user=login_user,
            req=req,
        )
        return resp_200({"changed": changed})
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post("/department/batch-create")
async def batch_create_department_spaces(
    req: DepartmentKnowledgeSpaceBatchCreateReq,
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    try:
        if req.provider_key == "weknora":
            from bisheng.knowledge.application.provider_provision_runtime import build_provisioning, load_preset

            tenant = await _expected_provider_tenant(request, login_user)
            if not req.request_key or req.preset_summary is None or req.provider_selection is None or not req.items:
                raise provider.ProviderFeatureUnavailable()
            await DepartmentKnowledgeSpaceService._ensure_tenant_admin(login_user)
            items = [
                (
                    SpaceSpec(
                        name=item.name or f"部门知识空间-{item.department_id}",
                        department_id=item.department_id,
                        description=item.description,
                        icon=item.icon,
                        auth_type=(item.auth_type or DepartmentKnowledgeSpaceService.DEFAULT_AUTH_TYPE).value,
                        is_released=DepartmentKnowledgeSpaceService.DEFAULT_IS_RELEASED
                        if item.is_released is None
                        else item.is_released,
                    ),
                    req.preset_summary,
                )
                for item in req.items
            ]
            results = await DepartmentKnowledgeSpaceService.accept_external_spaces(
                login_user=login_user,
                expected_tenant=str(tenant),
                items=items,
                preset=await load_preset(tenant, req.provider_selection),
                key=req.request_key,
                provisioning=await build_provisioning(login_user),
            )
            return resp_200({"items": results})
        if req.request_key is not None or req.preset_summary is not None or req.provider_selection is not None:
            raise provider.ProviderFeatureUnavailable()
        spaces = await DepartmentKnowledgeSpaceService.batch_create_spaces(
            request=request,
            login_user=login_user,
            req=req,
        )
        return resp_200(spaces)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get("/square")
async def get_knowledge_square(
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_knowledge_square(keyword, page, page_size)
    return resp_200(result)


@router.get("/{space_id}/children")
async def list_space_children(
    space_id: int,
    parent_id: int | None = None,
    file_ids: list[int] = Query(default=None, description="精确文件ID列表"),
    order_field: SpaceFileOrderField = "file_type",
    order_sort: SpaceFileOrderSort = "asc",
    file_status: list[int] = Query(default=None, description="文件状态列表"),
    page_size: int = 40,
    cursor: str | None = Query(
        default=None,
        description="F027 cursor-based pagination token from the previous response's "
        "`next_cursor`. Omit (or pass empty) to fetch the first page.",
    ),
    file_type: int | None = Query(default=None, description="0=DIR only, 1=FILE only, empty=both"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """List space children (F027 cursor-based pagination).

    Response shape (PageInfiniteCursorData): ``{data, page_size, has_more, next_cursor}``.
    The legacy ``total`` / ``page`` fields have been removed (AC-03).
    """
    route = await provider.resolve_space_route(space_id)
    if route:
        return resp_200(
            await provider_listing(
                await svc._permission_actor(),
                route,
                parent_id=parent_id,
                order_field=order_field,
                order_sort=order_sort,
                page_size=page_size,
                cursor=cursor,
                file_ids=file_ids,
                file_type=file_type,
                file_status=file_status,
            )
        )
    result = await svc.list_space_children(
        space_id,
        parent_id,
        file_ids,
        order_field,
        order_sort,
        file_status=file_status,
        cursor=cursor,
        page_size=page_size,
        file_type=file_type,
    )
    return resp_200(result)


@router.get("/{space_id}/search")
async def search_space_children(
    space_id: int,
    parent_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    order_field: SpaceFileOrderField = "file_type",
    order_sort: SpaceFileOrderSort = "asc",
    tag_ids: list[int] = Query(default=None, description="标签ID列表"),
    file_status: list[int] = Query(default=None, description="文件状态列表"),
    keyword: str | None = None,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    route = await provider.resolve_space_route(space_id)
    if route:
        return resp_200(
            await provider_listing(
                await svc._permission_actor(),
                route,
                parent_id=parent_id,
                order_field=order_field,
                order_sort=order_sort,
                page_size=page_size,
                page=page,
                tag_ids=tag_ids,
                keyword=keyword,
                file_status=file_status,
                search=True,
            )
        )
    result = await svc.search_space_children(
        space_id,
        parent_id,
        tag_ids=tag_ids,
        keyword=keyword,
        page=page,
        page_size=page_size,
        file_status=file_status,
        order_field=order_field,
        order_sort=order_sort,
    )
    return resp_200(result)


@router.get("/{space_id}/tag", dependencies=[Depends(require_native_space)])
async def get_space_tag(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.get_space_tags(space_id)
    return resp_200(result)


@router.post("/{space_id}/tag", dependencies=[Depends(require_native_space)])
async def add_space_tags(
    space_id: int,
    tag_name: str = Body(..., embed=True, description="标签名称"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.add_space_tag(space_id, tag_name)
    return resp_200(result)


@router.delete("/{space_id}/tag", dependencies=[Depends(require_native_space)])
async def delete_space_tags(
    space_id: int,
    tag_id: int = Body(..., embed=True, description="标签ID"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.delete_space_tag(space_id, tag_id)
    return resp_200(result)


# ──────────────────────────── Folders ─────────────────────────────────────────


@router.post("/{space_id}/folders", dependencies=[Depends(require_native_space)])
async def add_folder(
    space_id: int,
    req: FolderCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    folder = await svc.add_folder(
        knowledge_id=space_id,
        folder_name=req.name,
        parent_id=req.parent_id,
    )
    return resp_200(folder)


@router.post("/{space_id}/folders/upload", dependencies=[Depends(require_native_space)])
async def upload_folder(
    space_id: int,
    req: FolderUploadReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """F034 §5.5: register a whole client-side folder (nested) in one batch."""
    if req.upload_context is not None:
        return resp_200(await register_owned_upload(svc, space_id, req, folder=True))
    files = await svc.upload_folder_items(
        knowledge_id=space_id,
        items=req.items,
        parent_id=req.parent_id,
        **({"processing_overrides": req.overrides} if req.overrides is not None else {}),
    )
    return resp_200(files)


@router.put("/{space_id}/folders/{folder_id}", dependencies=[Depends(require_native_space)])
async def rename_folder(
    space_id: int,
    folder_id: int,
    req: FolderRenameReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    folder = await svc.rename_folder(folder_id, req.name)
    return resp_200(folder)


@router.delete("/{space_id}/folders/{folder_id}", dependencies=[Depends(require_native_space)])
async def delete_folder(
    space_id: int,
    folder_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_folder(space_id, folder_id)
    return resp_200()


@router.get("/{space_id}/folders/{folder_id}/parent", dependencies=[Depends(require_native_space)])
async def get_folder_parent(
    space_id: int,
    folder_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_folder_file_parent(space_id, folder_id)
    return resp_200(result)


# ──────────────────────────── Files ───────────────────────────────────────────


@router.post("/{space_id}/files", dependencies=[Depends(require_native_space)])
async def add_file(
    space_id: int,
    req: FileCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    if req.upload_context is not None:
        return resp_200(await register_owned_upload(svc, space_id, req))
    file_record = await svc.add_file(
        knowledge_id=space_id,
        file_path=req.file_path,
        parent_id=req.parent_id,
        **({"processing_overrides": req.overrides} if req.overrides is not None else {}),
    )
    return resp_200(file_record)


@router.post("/{space_id}/web-links", dependencies=[Depends(require_native_space)])
async def import_web_link(
    space_id: int,
    req: WebLinkCreateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.import_web_link(
        knowledge_id=space_id,
        url=req.url,
        title=req.title,
        parent_id=req.parent_id,
        overwrite=req.overwrite,
    )
    return resp_200(file_record)


@router.put("/{space_id}/files/{file_id}", dependencies=[Depends(require_native_space)])
async def rename_file(
    space_id: int,
    file_id: int,
    req: FileRenameReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.rename_file(file_id, req.name)
    return resp_200(file_record)


@router.put("/{space_id}/files/{file_id}/encoding", dependencies=[Depends(require_native_space)])
async def update_file_encoding(
    space_id: int,
    file_id: int,
    req: FileEncodingUpdateReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    file_record = await svc.update_file_encoding(file_id, req.encoding)
    return resp_200(file_record)


@router.delete("/{space_id}/files/{file_id}", dependencies=[Depends(require_native_space)])
async def delete_file(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.delete_file(file_id, space_id=space_id)
    return resp_200()


@router.post("/{space_id}/files/move", dependencies=[Depends(require_native_space)])
async def move_file_folder(
    space_id: int,
    req: FileMoveReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """Legacy same-space synchronous entry; cross-space uses explicit confirmation."""
    return resp_200(
        await svc.move_items(
            space_id,
            [item.model_dump() for item in req.items],
            target_space_id=req.target_space_id,
            target_folder_id=req.target_folder_id,
            skip_invalid=req.skip_invalid,
        )
    )


@router.get("/{space_id}/files/{file_id}/preview")
async def get_file_preview(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    if await provider.resolve_space_route(space_id):
        reads = await provider.build_provider_reads()
        handle = await reads.issue(await svc._permission_actor(), space_id, file_id, "preview")
        return resp_200({"original_url": "", "preview_url": provider.handle_url(handle), "media_kind": "text_excerpt"})
    urls = await svc.get_file_preview(file_id, space_id=space_id)
    return resp_200(urls)


@router.get("/{space_id}/files/{file_id}/download")
async def get_file_download(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    if await provider.resolve_space_route(space_id):
        reads = await provider.build_provider_reads()
        handle = await reads.issue(await svc._permission_actor(), space_id, file_id, "download")
        return resp_200({"original_url": provider.handle_url(handle), "preview_url": ""})
    urls = await svc.get_file_download(file_id, space_id=space_id)
    return resp_200(urls)


class _ControlledDownload(StreamingResponse):
    def __init__(self, reads, actor, handle, range_header, user_id=None):
        super().__init__(iter(()))
        self.reads, self.actor, self.handle, self.range_header = reads, actor, handle, range_header
        self.user_id = user_id

    async def __call__(self, scope, receive, send):
        # Acquire before headers, close even on cancellation or response-start failure.
        async with self.reads.open(
            self.actor, self.handle, range_header=self.range_header, user_id=self.user_id
        ) as upstream:
            preview = self.handle.operation == "preview"
            headers = {
                "Cache-Control": "private, no-store",
                "Content-Disposition": "inline" if preview else "attachment",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            }
            for field in ("content-range", "content-length", "accept-ranges"):
                if field in upstream.headers:
                    headers[field] = upstream.headers[field]
            response = StreamingResponse(
                upstream.aiter_bytes() if preview else upstream.aiter_raw(),
                status_code=upstream.status_code,
                media_type="text/plain" if preview else "application/octet-stream",
                headers=headers,
            )
            await response(scope, receive, send)


@router.get("/{space_id}/files/{file_id}/content/{operation}")
async def fetch_provider_content(
    space_id: int,
    file_id: int,
    operation: Literal["preview", "download"],
    version_id: int,
    generation: int,
    epoch: int,
    request: Request,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    if await provider.resolve_space_route(space_id) is None:
        raise provider.ProviderFeatureUnavailable()
    return _ControlledDownload(
        await provider.build_provider_reads(),
        await svc._permission_actor(),
        ReadHandle(space_id, file_id, version_id, generation, epoch, operation),
        request.headers.get("Range"),
        svc.login_user.user_id,
    )


@router.post("/{space_id}/files/{file_id}/tag", dependencies=[Depends(require_native_space)])
async def update_file_tags(
    space_id: int,
    file_id: int,
    tag_ids: list[int] = Body(..., embed=True, description="标签ID列表"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.update_file_tags(space_id, file_id, tag_ids)
    return resp_200(result)


# ──────────────────────────── Batch Ops ───────────────────────────────────────


@router.post("/{space_id}/files/batch-download", dependencies=[Depends(require_native_space)])
async def batch_download(
    space_id: int,
    req: BatchDownloadReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    url = await svc.batch_download(space_id, req.file_ids, req.folder_ids)
    return resp_200({"url": url})


@router.post("/{space_id}/files/batch-delete", dependencies=[Depends(require_native_space)])
async def batch_delete(
    space_id: int,
    req: BatchDeleteReq,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    await svc.batch_delete(space_id, req.file_ids, req.folder_ids)
    return resp_200()


@router.post("/{space_id}/files/batch-tag", dependencies=[Depends(require_native_space)])
async def batch_update_tags(
    space_id: int,
    file_ids: list[int] = Body(..., embed=True, description="文件ID列表"),
    tag_ids: list[int] = Body(..., embed=True, description="标签ID列表"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.batch_add_file_tags(space_id, file_ids, tag_ids)
    return resp_200(result)


@router.post("/{space_id}/files/batch-retry", dependencies=[Depends(require_native_space)])
async def batch_retry_failed_files(
    space_id: int,
    file_ids: list[int] = Body(..., embed=True, description="file or folder ids"),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    result = await svc.batch_retry_failed_files(space_id, file_ids)
    return resp_200(result)


@router.post("/{space_id}/files/retry", dependencies=[Depends(require_native_space)])
async def retry_space_files(
    space_id: int,
    req_data: dict = Body(...),
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    """Retry files in a knowledge space with potentially new split rules"""
    result = await svc.retry_space_files(space_id, req_data)
    return resp_200(result)


# ──────────────────────────── Subscribe ───────────────────────────────────────


@router.get("/{space_id}/exit-status")
async def get_space_exit_status(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    return resp_200(await svc.get_space_exit_status(space_id))


@router.post("/{space_id}/subscribe", response_model=None)
async def subscribe_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.subscribe_space(space_id)
    return resp_200(result)


@router.post("/{space_id}/unsubscribe", response_model=None)
async def unsubscribe_space(
    space_id: int,
    svc: KnowledgeSpaceService = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.unsubscribe_space(space_id)
    return resp_200(result)


# ──────────────────────────── Chat ────────────────────────────────────────────


@router.post("/{space_id}/chat/file/{file_id}")
async def chat_single_file(
    space_id: int,
    file_id: int,
    req: ChatReq,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_single_file(space_id, file_id, req.query, req.model_id):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception("chat_file error")
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{space_id}/chat/file/{file_id}/history")
async def chat_single_file_history(
    space_id: int,
    file_id: int,
    page_size: int = 20,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    response = await svc.single_file_history(space_id, file_id, page_size)
    return resp_200(response)


@router.delete("/{space_id}/chat/file/{file_id}/history")
async def clear_single_file_history(
    space_id: int,
    file_id: int,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    response = await svc.clear_file_history(space_id, file_id)
    return resp_200(response)


@router.get("/{space_id}/chat/folder/session")
async def get_chat_folder_session(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_session(space_id, folder_id)
    return resp_200([KnowledgeChatSessionResponse.model_validate(item) for item in result])


@router.post("/{space_id}/chat/folder/session")
async def create_chat_folder_session(
    space_id: int,
    folder_id: int = Body(default=0, embed=True, description="folder id"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.create_chat_folder_session(space_id, folder_id)
    return resp_200(KnowledgeChatSessionResponse.model_validate(result))


@router.delete("/{space_id}/chat/folder/session")
async def delete_chat_folder_session(
    space_id: int,
    folder_id: int = Body(default=0, description="folder id"),
    chat_id: str = Body(..., description="Chat ID"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_session(space_id, folder_id, chat_id)
    return resp_200(result)


@router.get("/{space_id}/chat/folder/history")
async def get_chat_folder_history(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    chat_id: str = Query(..., description="Chat ID"),
    page_size: int = 20,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.get_chat_folder_history(space_id, folder_id, chat_id, page_size)
    return resp_200(result)


@router.delete("/{space_id}/chat/folder/history")
async def delete_chat_folder_history(
    space_id: int,
    folder_id: int = Query(default=0, description="folder id"),
    chat_id: str = Query(..., description="Chat ID"),
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
):
    result = await svc.delete_chat_folder_history(space_id, folder_id, chat_id)
    return resp_200(result)


@router.post("/{space_id}/chat/folder")
async def chat_folder(
    space_id: int,
    req: ChatFolderReq,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for one in svc.chat_folder(space_id, req.folder_id, req.chat_id, req.query, req.model_id, req.tags):
                yield SSEResponse(data=one).to_string()
        except BaseErrorCode as e:
            yield e.to_sse_event_instance_str()
        except Exception as e:
            logger.exception("chat_folder error")
            yield ServerError(exception=e).to_sse_event_instance_str()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
