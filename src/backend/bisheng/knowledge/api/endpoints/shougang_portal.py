import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query
from loguru import logger
from starlette.responses import StreamingResponse

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.schemas.api import SSEResponse, resp_200
from bisheng.common.stream_errors import (
    StreamRetryEvent,
    StreamStageError,
    stream_error_sse,
    stream_retry_sse,
)
from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService
from bisheng.knowledge.api.dependencies import (
    get_knowledge_space_chat_service,
    get_knowledge_space_service,
    get_portal_pdf_download_service,
)
from bisheng.knowledge.api.portal_pdf_download_response import prepare_portal_pdf_download_response
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ChatReq,
    KnowledgeSpaceFolderStatsReq,
    ShougangPortalDomainBindableSpacesResp,
    ShougangPortalDomainFileCountReq,
    ShougangPortalDomainFileCountResp,
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFavoriteCreateResp,
    ShougangPortalFavoriteFilesResp,
    ShougangPortalFavoriteRemoveReq,
    ShougangPortalFavoriteRemoveResp,
    ShougangPortalFavoriteStatusReq,
    ShougangPortalFavoriteStatusResp,
    ShougangPortalFileBrowseReq,
    ShougangPortalFileDetailResp,
    ShougangPortalFileSearchReq,
    ShougangPortalFileSearchResp,
    ShougangPortalHomeReq,
    ShougangPortalHomeResp,
    ShougangPortalHomeStatsResp,
    ShougangPortalPersonalSpacesResp,
    ShougangPortalQaFileSearchReq,
    ShougangPortalQaFileSearchResp,
    ShougangPortalRelatedFilesResp,
    ShougangPortalShareLinkAccessResp,
    ShougangPortalShareLinkCreateReq,
    ShougangPortalShareLinkCreateResp,
    ShougangPortalShareLinkMetaResp,
    ShougangPortalShareLinkVerifyReq,
    ShougangPortalSpaceBusinessDomainCodesSyncReq,
    ShougangPortalSpaceBusinessDomainCodesSyncResp,
    ShougangPortalSpaceInfoReq,
    ShougangPortalSpaceInfoResp,
    ShougangPortalSpaceLevelsResp,
    ShougangPortalTagSearchReq,
    ShougangPortalTagSearchResp,
    ShougangPortalTelemetryEventReq,
)
from bisheng.knowledge.domain.schemas.portal_hot_search_schema import (
    PortalHotSearchTriggerRebuildReq,
    PortalHotSearchTriggerRebuildResp,
)
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import PortalPdfDownloadRequest
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)
from bisheng.knowledge.domain.services.portal_hot_search_admin_service import (
    PortalHotSearchAdminService,
)

router = APIRouter(prefix="/knowledge/shougang-portal", tags=["shougang_portal"])


@router.get("/files/{space_id}/{file_id}/download")
async def download_shougang_portal_pdf(
    space_id: int,
    file_id: int,
    entry_point: str = Query(default="other"),
    share_access_grant: str = Header(default="", alias="X-Portal-Share-Access-Grant"),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    svc: Any = Depends(get_portal_pdf_download_service),
) -> Any:
    request = PortalPdfDownloadRequest(
        space_id=space_id,
        file_id=file_id,
        entry_point=entry_point,
        share_access_grant=share_access_grant,
    )
    return await prepare_portal_pdf_download_response(
        service=svc,
        request=request,
        login_user=login_user,
    )


@router.get("/space-levels")
async def get_shougang_portal_space_levels(
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    levels = await svc.get_shougang_portal_space_levels()
    return resp_200(ShougangPortalSpaceLevelsResp(levels=levels).model_dump(mode="json"))


@router.get("/spaces")
async def list_shougang_portal_discoverable_spaces(
    discovery_scope: Literal[
        "public",
        "public_and_department",
    ] = "public_and_department",
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.list_shougang_portal_discoverable_spaces(discovery_scope=discovery_scope)
    return resp_200({"spaces": spaces})


@router.get("/personal-spaces")
async def get_shougang_portal_personal_spaces(
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_personal_spaces()
    return resp_200(ShougangPortalPersonalSpacesResp(**result).model_dump(mode="json"))


@router.post("/favorites")
async def create_shougang_portal_favorite(
    req: ShougangPortalFavoriteCreateReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.create_shougang_portal_favorite(req)
        raw = result.model_dump() if hasattr(result, "model_dump") else result
        return resp_200(ShougangPortalFavoriteCreateResp(**raw).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/favorites/remove")
async def remove_shougang_portal_favorite(
    req: ShougangPortalFavoriteRemoveReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.remove_shougang_portal_favorite(req)
        raw = result.model_dump() if hasattr(result, "model_dump") else result
        return resp_200(ShougangPortalFavoriteRemoveResp(**raw).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/favorites/status")
async def get_shougang_portal_favorite_status(
    req: ShougangPortalFavoriteStatusReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_favorite_status(req)
    raw = result.model_dump() if hasattr(result, "model_dump") else result
    return resp_200(ShougangPortalFavoriteStatusResp(**raw).model_dump(mode="json"))


@router.get("/favorites/files")
async def list_shougang_portal_favorites(
    page: int = 1,
    page_size: int = 20,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_shougang_portal_favorites(page=page, page_size=page_size)
    raw = result.model_dump() if hasattr(result, "model_dump") else result
    return resp_200(ShougangPortalFavoriteFilesResp(**raw).model_dump(mode="json"))


@router.post("/share-links")
async def create_shougang_portal_share_link(
    req: ShougangPortalShareLinkCreateReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.create_shougang_portal_share_link(req)
        raw = result.model_dump() if hasattr(result, "model_dump") else result
        return resp_200(ShougangPortalShareLinkCreateResp(**raw).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/share-links/{share_token}")
async def get_shougang_portal_share_link_meta(
    share_token: str,
    portal_anonymous: bool = Header(
        default=False,
        alias="X-Portal-Anonymous",
    ),
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.get_shougang_portal_share_link_meta(
            share_token,
            for_anonymous_portal=portal_anonymous,
        )
        raw = result.model_dump() if hasattr(result, "model_dump") else result
        return resp_200(ShougangPortalShareLinkMetaResp(**raw).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/share-links/{share_token}/verify")
async def verify_shougang_portal_share_link(
    share_token: str,
    req: ShougangPortalShareLinkVerifyReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.verify_shougang_portal_share_link(share_token, req)
        raw = result.model_dump() if hasattr(result, "model_dump") else result
        access = ShougangPortalShareLinkAccessResp(**raw)
        payload = access.model_dump(mode="json")
        if not access.download_grant:
            payload.pop("download_grant", None)
            payload.pop("download_grant_expires_at", None)
        return resp_200(payload)
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/spaces/info")
async def get_shougang_portal_space_infos(
    req: ShougangPortalSpaceInfoReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_shougang_portal_space_infos(req.space_ids)
    return resp_200(ShougangPortalSpaceInfoResp(spaces=spaces).model_dump(mode="json"))


@router.put("/spaces/business-domain-codes")
async def sync_shougang_portal_space_business_domain_codes(
    req: ShougangPortalSpaceBusinessDomainCodesSyncReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.sync_shougang_portal_space_business_domain_codes(req)
        return resp_200(ShougangPortalSpaceBusinessDomainCodesSyncResp(**result).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get("/spaces/domain-bindable")
async def get_shougang_portal_domain_bindable_spaces(
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        spaces = await svc.list_shougang_portal_domain_bindable_spaces()
        response = ShougangPortalDomainBindableSpacesResp(spaces=spaces)
        return resp_200(response.model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/tags/search")
async def search_shougang_portal_tags(
    req: ShougangPortalTagSearchReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    tags = await svc.search_shougang_portal_tags(req.space_ids, req.space_level, req.business_domain_code)
    return resp_200(ShougangPortalTagSearchResp(tags=tags).model_dump(mode="json"))


@router.post("/domain-file-counts")
async def count_shougang_portal_domain_files(
    req: ShougangPortalDomainFileCountReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    counts = await svc.count_shougang_portal_domain_files(req.domains)
    return resp_200(ShougangPortalDomainFileCountResp(counts=counts).model_dump(mode="json"))


@router.post("/home")
async def get_shougang_portal_home(
    req: ShougangPortalHomeReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_home(req)
    return resp_200(ShougangPortalHomeResp(**result).model_dump(mode="json"))


@router.post("/hot-searches/rebuild")
async def trigger_shougang_portal_hot_search_rebuild(
    req: PortalHotSearchTriggerRebuildReq,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> Any:
    """Manually dispatch hot-search rebuild (AC-34). Tenant admin or global super admin."""
    try:
        result = await PortalHotSearchAdminService.trigger_rebuild(req, login_user=login_user)
        return resp_200(PortalHotSearchTriggerRebuildResp(**result.model_dump()).model_dump(mode="json"))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post("/telemetry/events")
async def record_shougang_portal_telemetry_event(
    req: ShougangPortalTelemetryEventReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    event_type = BaseTelemetryTypeEnum(req.event_type)
    event_data = PortalTelemetryEventService.build_event_data(
        event_type,
        req.model_dump(exclude={"event_type"}, exclude_none=True),
    )
    PortalTelemetryEventService.log_event_sync(
        user_id=login_user.user_id,
        event_type=event_type,
        event_data=event_data,
    )
    await svc.record_shougang_portal_recommendation_behavior(req)
    return resp_200({"accepted": True})


@router.get("/home/stats")
async def get_shougang_portal_home_stats(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    _ = login_user
    result, total_files = await asyncio.gather(
        PortalTelemetryEventService.count_home_events(),
        KnowledgeFileDao.async_count_all_success_files(),
    )
    return resp_200(ShougangPortalHomeStatsResp(**result, total_files=total_files).model_dump(mode="json"))


@router.get("/files/{space_id}/{file_id}/preview")
async def get_shougang_portal_file_preview(
    space_id: int,
    file_id: int,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_file_preview(
        space_id=space_id,
        file_id=file_id,
    )
    return resp_200(result)


@router.get("/files/{space_id}/{file_id}/chunks")
async def get_shougang_portal_file_chunks(
    space_id: int,
    file_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=100),
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_file_chunks(
        space_id=space_id,
        file_id=file_id,
        page=page,
        limit=limit,
    )
    return resp_200(result)


@router.post("/files/{space_id}/{file_id}/chat")
async def chat_shougang_portal_single_file(
    space_id: int,
    file_id: int,
    req: ChatReq,
    svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service),
) -> Any:
    async def event_stream():
        try:
            async for item in svc.chat_single_file_for_portal(
                space_id,
                file_id,
                req.query,
                req.model_id,
            ):
                if isinstance(item, StreamRetryEvent):
                    yield stream_retry_sse(item)
                else:
                    yield SSEResponse(data=item).to_string()
        except StreamStageError as exc:
            logger.exception("portal chat_file staged stream error")
            yield stream_error_sse(
                exc.error,
                stage=exc.stage,
                had_output=exc.had_output,
            )
        except BaseErrorCode as exc:
            logger.exception("portal chat_file business error")
            yield stream_error_sse(exc, stage="document")
        except Exception as exc:
            logger.exception("portal chat_file error")
            yield stream_error_sse(exc)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/files/{space_id}/{file_id}/related")
async def list_shougang_portal_related_files(
    space_id: int,
    file_id: int,
    limit: int = 3,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_shougang_portal_related_files(space_id=space_id, file_id=file_id, limit=limit)
    return resp_200(ShougangPortalRelatedFilesResp(**result).model_dump(mode="json"))


@router.get("/files/{space_id}/{file_id}")
async def get_shougang_portal_file(
    space_id: int,
    file_id: int,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    item = await svc.get_shougang_portal_file(space_id=space_id, file_id=file_id)
    raw = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
    return resp_200(ShougangPortalFileDetailResp(data=raw).model_dump(mode="json"))


@router.post("/files/search")
async def search_shougang_portal_files(
    req: ShougangPortalFileSearchReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_shougang_portal_files(req)
    return resp_200(ShougangPortalFileSearchResp(**result).model_dump(mode="json"))


@router.post("/files/browse")
async def browse_shougang_portal_files(
    req: ShougangPortalFileBrowseReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.browse_shougang_portal_files(req)
    return resp_200(ShougangPortalFileSearchResp(**result).model_dump(mode="json"))


@router.post("/qa/files/search")
async def search_shougang_portal_qa_files(
    req: ShougangPortalQaFileSearchReq,
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_shougang_portal_qa_files_by_name(req)
    return resp_200(ShougangPortalQaFileSearchResp(**result).model_dump(mode="json"))


@router.get("/qa/spaces/{space_id}/children")
async def list_shougang_portal_qa_children(
    space_id: int,
    discovery_scope: Literal[
        "public",
        "public_and_department",
    ] = "public_and_department",
    parent_id: int | None = None,
    cursor: str | None = None,
    page_size: int = Query(default=10, ge=1, le=100),
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_shougang_portal_qa_children(
        space_id=space_id,
        parent_id=parent_id,
        cursor=cursor,
        page_size=page_size,
        discovery_scope=discovery_scope,
    )
    return resp_200(result)


@router.post("/qa/spaces/{space_id}/folder-stats")
async def get_shougang_portal_qa_folder_stats(
    space_id: int,
    req: KnowledgeSpaceFolderStatsReq,
    discovery_scope: Literal[
        "public",
        "public_and_department",
    ] = "public_and_department",
    svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_qa_folder_stats(
        space_id=space_id,
        folder_ids=req.folder_ids,
        discovery_scope=discovery_scope,
    )
    return resp_200(result)
