from typing import List, Dict

from fastapi import APIRouter, Request

from bisheng.api.v1.schemas import resp_200

router = APIRouter(prefix='/group', tags=['OpenAPI', 'Workflow'])

@router.post('/sync')
async def sync_group(request: Request,
                     data: List[Dict]):
    """ 从其他第三方同步用户组信息 """

    return resp_200(data)
