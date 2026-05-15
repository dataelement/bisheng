from typing import Any

from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_space_service
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    ShougangPortalSpaceInfoReq,
    ShougangPortalSpaceInfoResp,
)

router = APIRouter(prefix='/knowledge/shougang-portal', tags=['shougang_portal'])


@router.post('/spaces/info')
async def get_shougang_portal_space_infos(
        req: ShougangPortalSpaceInfoReq,
        svc: Any = Depends(get_knowledge_space_service),
) -> Any:
    spaces = await svc.get_shougang_portal_space_infos(req.space_ids)
    return resp_200(ShougangPortalSpaceInfoResp(spaces=spaces).model_dump(mode='json'))
