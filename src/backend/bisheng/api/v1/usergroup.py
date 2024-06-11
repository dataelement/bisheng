# build router
import json
from typing import Annotated, List, Optional

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import check_permissions
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group import GroupRead
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.user import User
from bisheng.database.models.user_group import UserGroupCreate, UserGroupRead, UserGroupDao
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/group', tags=['User'])


@router.get('/list', response_model=UnifiedResponseModel[List[GroupRead]], status_code=200)
async def get_all_group(Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    if login_user.is_admin():
        groups = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_group(login_user.user_id)
        groups = []
        for one in user_groups:
            if one.is_group_admin:
                groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')

    groups = RoleGroupService().get_group_list(groups)
    return resp_200({'records': groups})


@router.post('/set_user_group',
             response_model=UnifiedResponseModel[UserGroupRead],
             status_code=200)
async def set_user_group(user_id: int, group_id: List[int], Authorize: AuthJWT = Depends()):
    """
    设置用户分组, 批量替换
    """
    await check_permissions(Authorize, ['admin'])
    return resp_200(RoleGroupService().replace_user_groups(user_id, group_id))


@router.get('/get_user_group',
            response_model=UnifiedResponseModel[List[GroupRead]],
            status_code=200)
async def get_user_group(user_id: int, Authorize: AuthJWT = Depends()):
    """
    获取用户所属分组
    """
    # await check_permissions(Authorize, ['admin'])
    return resp_200(RoleGroupService().get_user_groups_list(user_id))


@router.get('/get_group_user', response_model=UnifiedResponseModel[List[User]], status_code=200)
async def get_group_user(group_id: int,
                         page_size: int = None,
                         page_num: int = None,
                         Authorize: AuthJWT = Depends()):
    """
    获取分组用户
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_user_list(group_id, page_size, page_num)


@router.post('/set_group_admin',
             response_model=UnifiedResponseModel[List[UserGroupRead]],
             status_code=200)
async def set_group_admin(user_ids: Annotated[List[int], Body(embed=True)],
                          group_id: Annotated[int, Body(embed=True)],
                          Authorize: AuthJWT = Depends()):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """
    await check_permissions(Authorize, ['admin'])
    return resp_200(RoleGroupService().set_group_admin(user_ids, group_id))


@router.get('/get_group_flows',
            response_model=UnifiedResponseModel[List[UserGroupRead]],
            status_code=200)
async def get_group_flows(*,
                          group_id: int,
                          resource_type: int,
                          name: Optional[str] = None,
                          page_size: Optional[int] = 10,
                          page_num: Optional[int] = 1,
                          Authorize: AuthJWT = Depends()):
    """
    获取分组下所有的技能
    """
    # await check_permissions(Authorize, ['admin'])

    return resp_200(RoleGroupService().get_group_resources(
        group_id,
        resource_type=ResourceTypeEnum(resource_type),
        name=name,
        page_size=page_size,
        page_num=page_num))
