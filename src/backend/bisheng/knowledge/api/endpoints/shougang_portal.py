from typing import Any

from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalFileSearchReq,
    ShougangPortalFileSearchResp,
    ShougangPortalSpaceInfoReq,
    ShougangPortalSpaceInfoResp,
    ShougangPortalSpaceLevelsResp,
)

router = APIRouter(prefix='/knowledge/shougang-portal', tags=['shougang_portal'])


@router.get('/space-levels')
async def get_shougang_portal_space_levels(
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    levels = await svc.get_shougang_portal_space_levels()
    return resp_200(ShougangPortalSpaceLevelsResp(levels=levels).model_dump(mode='json'))


@router.post('/spaces/info')
async def get_shougang_portal_space_infos(
        req: ShougangPortalSpaceInfoReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_shougang_portal_space_infos(req.space_ids)
    return resp_200(ShougangPortalSpaceInfoResp(spaces=spaces).model_dump(mode='json'))


@router.post('/files/search')
async def search_shougang_portal_files(
        req: ShougangPortalFileSearchReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    result = await svc.search_shougang_portal_files(req)
    return resp_200(ShougangPortalFileSearchResp(**result).model_dump(mode='json'))
