from typing import List, Dict

from fastapi import APIRouter, Request

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.v1.schemas import resp_200

router = APIRouter(prefix='/group', tags=['OpenAPI', 'Group'])


@router.post('/sync')
async def sync_group(request: Request,
                     data: List[Dict]):
    """ 从其他第三方同步用户组信息 """
    RoleGroupService().sync_third_groups(data)
    return resp_200()
