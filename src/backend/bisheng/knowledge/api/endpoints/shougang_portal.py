import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.common.telemetry.portal_event_service import PortalTelemetryEventService
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalDomainFileCountReq,
    ShougangPortalDomainFileCountResp,
    ShougangPortalFavoriteCreateReq,
    ShougangPortalFavoriteCreateResp,
    ShougangPortalFavoriteFilesResp,
    ShougangPortalFavoriteRemoveReq,
    ShougangPortalFavoriteRemoveResp,
    ShougangPortalFavoriteStatusReq,
    ShougangPortalFavoriteStatusResp,
    ShougangPortalFileSearchReq,
    ShougangPortalFileSearchResp,
    ShougangPortalHomeReq,
    ShougangPortalHomeResp,
    ShougangPortalHomeStatsResp,
    ShougangPortalQaFileSearchReq,
    ShougangPortalQaFileSearchResp,
    ShougangPortalPersonalSpacesResp,
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

router = APIRouter(prefix='/knowledge/shougang-portal', tags=['shougang_portal'])


@router.get('/space-levels')
async def get_shougang_portal_space_levels(
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    levels = await svc.get_shougang_portal_space_levels()
    return resp_200(ShougangPortalSpaceLevelsResp(levels=levels).model_dump(mode='json'))


@router.get('/personal-spaces')
async def get_shougang_portal_personal_spaces(
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_personal_spaces()
    return resp_200(ShougangPortalPersonalSpacesResp(**result).model_dump(mode='json'))


@router.post('/favorites')
async def create_shougang_portal_favorite(
        req: ShougangPortalFavoriteCreateReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.create_shougang_portal_favorite(req)
        raw = result.model_dump() if hasattr(result, 'model_dump') else result
        return resp_200(ShougangPortalFavoriteCreateResp(**raw).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post('/favorites/remove')
async def remove_shougang_portal_favorite(
        req: ShougangPortalFavoriteRemoveReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.remove_shougang_portal_favorite(req)
        raw = result.model_dump() if hasattr(result, 'model_dump') else result
        return resp_200(ShougangPortalFavoriteRemoveResp(**raw).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post('/favorites/status')
async def get_shougang_portal_favorite_status(
        req: ShougangPortalFavoriteStatusReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_favorite_status(req)
    raw = result.model_dump() if hasattr(result, 'model_dump') else result
    return resp_200(ShougangPortalFavoriteStatusResp(**raw).model_dump(mode='json'))


@router.get('/favorites/files')
async def list_shougang_portal_favorites(
        page: int = 1,
        page_size: int = 20,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.list_shougang_portal_favorites(page=page, page_size=page_size)
    raw = result.model_dump() if hasattr(result, 'model_dump') else result
    return resp_200(ShougangPortalFavoriteFilesResp(**raw).model_dump(mode='json'))


@router.post('/share-links')
async def create_shougang_portal_share_link(
        req: ShougangPortalShareLinkCreateReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.create_shougang_portal_share_link(req)
        raw = result.model_dump() if hasattr(result, 'model_dump') else result
        return resp_200(ShougangPortalShareLinkCreateResp(**raw).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.get('/share-links/{share_token}')
async def get_shougang_portal_share_link_meta(
        share_token: str,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.get_shougang_portal_share_link_meta(share_token)
        raw = result.model_dump() if hasattr(result, 'model_dump') else result
        return resp_200(ShougangPortalShareLinkMetaResp(**raw).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post('/share-links/{share_token}/verify')
async def verify_shougang_portal_share_link(
        share_token: str,
        req: ShougangPortalShareLinkVerifyReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.verify_shougang_portal_share_link(share_token, req)
        raw = result.model_dump() if hasattr(result, 'model_dump') else result
        return resp_200(ShougangPortalShareLinkAccessResp(**raw).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post('/spaces/info')
async def get_shougang_portal_space_infos(
        req: ShougangPortalSpaceInfoReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_shougang_portal_space_infos(req.space_ids)
    return resp_200(ShougangPortalSpaceInfoResp(spaces=spaces).model_dump(mode='json'))


@router.put('/spaces/business-domain-codes')
async def sync_shougang_portal_space_business_domain_codes(
        req: ShougangPortalSpaceBusinessDomainCodesSyncReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    try:
        result = await svc.sync_shougang_portal_space_business_domain_codes(req)
        return resp_200(ShougangPortalSpaceBusinessDomainCodesSyncResp(**result).model_dump(mode='json'))
    except BaseErrorCode as exc:
        return exc.return_resp_instance()


@router.post('/tags/search')
async def search_shougang_portal_tags(
        req: ShougangPortalTagSearchReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    tags = await svc.search_shougang_portal_tags(req.space_ids, req.space_level, req.business_domain_code)
    return resp_200(ShougangPortalTagSearchResp(tags=tags).model_dump(mode='json'))


@router.post('/domain-file-counts')
async def count_shougang_portal_domain_files(
        req: ShougangPortalDomainFileCountReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    counts = await svc.count_shougang_portal_domain_files(req.codes)
    return resp_200(ShougangPortalDomainFileCountResp(counts=counts).model_dump(mode='json'))


@router.post('/home')
async def get_shougang_portal_home(
        req: ShougangPortalHomeReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.get_shougang_portal_home(req)
    return resp_200(ShougangPortalHomeResp(**result).model_dump(mode='json'))


@router.post('/telemetry/events')
async def record_shougang_portal_telemetry_event(
        req: ShougangPortalTelemetryEventReq,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    event_type = BaseTelemetryTypeEnum(req.event_type)
    event_data = PortalTelemetryEventService.build_event_data(
        event_type,
        req.model_dump(exclude={'event_type'}, exclude_none=True),
    )
    PortalTelemetryEventService.log_event_sync(
        user_id=login_user.user_id,
        event_type=event_type,
        event_data=event_data,
    )
    return resp_200({'accepted': True})


@router.get('/home/stats')
async def get_shougang_portal_home_stats(
        login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> Any:
    _ = login_user
    result, total_files = await asyncio.gather(
        PortalTelemetryEventService.count_home_events(),
        KnowledgeFileDao.async_count_all_success_files(),
    )
    return resp_200(ShougangPortalHomeStatsResp(**result, total_files=total_files).model_dump(mode='json'))


@router.post('/files/search')
async def search_shougang_portal_files(
        req: ShougangPortalFileSearchReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_shougang_portal_files(req)
    return resp_200(ShougangPortalFileSearchResp(**result).model_dump(mode='json'))


@router.post('/qa/files/search')
async def search_shougang_portal_qa_files(
        req: ShougangPortalQaFileSearchReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_shougang_portal_qa_files_by_name(req)
    return resp_200(ShougangPortalQaFileSearchResp(**result).model_dump(mode='json'))
