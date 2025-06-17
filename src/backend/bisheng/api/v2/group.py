from typing import List, Dict

from fastapi import APIRouter, Request

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.v1.schemas import resp_200, resp_500
from bisheng.database.models.group import DefaultGroup

router = APIRouter(prefix='/group', tags=['OpenAPI', 'Group'])


@router.post('/sync')
async def sync_group(request: Request,
                     data: List[Dict]):
    """ 从其他第三方同步用户组信息 """
    RoleGroupService().sync_third_groups(data, target_group_id=DefaultGroup)
    return resp_200(data={"sync_target_group_id": DefaultGroup})


@router.post('/sync_v2')
async def sync_group(request: Request,
                     data: List[Dict]):
    """ 从其他第三方同步用户组信息 """
    sync_target_group_id = request.query_params.get('sync_target_group_id', 0)
    target_group_id = int(sync_target_group_id)
    RoleGroupService().sync_third_groups(data, target_group_id=sync_target_group_id)

    return resp_200(data={"sync_target_group_id": target_group_id})


@router.post('/refresh_code')
async def refresh_code(request: Request):
    """
    刷新全量code，目前code每一级是3位，总体只能支持999个用户组，视情况需要将GroupDao.generate_group_code进行调整
    调整后使用此方法刷新（调整视客户规模评估进行）
    """
    service = RoleGroupService()
    count = service.refresh_all_group_code()
    return resp_200(data={"count": count})