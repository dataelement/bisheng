# build router
from os import name
from typing import Annotated, List

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.utils import check_permissions
from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.database.models.group import GroupRead
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.user import User
from bisheng.database.models.user_group import UserGroupCreate, UserGroupRead
from fastapi import APIRouter, Body, Depends
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='group', tags=['User'])


@router.get('/list', response_model=UnifiedResponseModel(List[GroupRead]))
async def get_all_group(Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.post('/set_user_group', response_model=UnifiedResponseModel(UserGroupRead))
async def set_user_group(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    设置用户分组
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().insert_user_group(user_group)


@router.get('/get_user_group', response_model=UnifiedResponseModel(List[GroupRead]))
async def get_user_group(user_id: int, Authorize: AuthJWT = Depends()):
    """
    获取用户所属分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_user_groups_list(user_id)


@router.get('/get_group_user', response_model=UnifiedResponseModel(List[User]))
async def get_group_user(group_id: int,
                         page_size: int = None,
                         page_num: int = None,
                         Authorize: AuthJWT = Depends()):
    """
    获取分组用户
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_user_list(group_id, page_size, page_num)


@router.post('/set_group_admin', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def set_group_admin(user_ids: Annotated[List[int], Body(embed=True)],
                          group_id: Annotated[int, Body(embed=True)],
                          Authorize: AuthJWT = Depends()):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().set_group_admin(user_ids, group_id)


@router.get('/get_group_flows', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def get_group_flows(*,
                          group_id: Annotated[int, Body(embed=True)],
                          resource_type: Annotated[int, Body(embed=True)],
                          page_size: Annotated[int, Body(embed=True)] = None,
                          page_num: Annotated[int, Body(embed=True)] = None,
                          Authorize: AuthJWT = Depends()):
    """
    获取分组下所有的技能
    """
    # await check_permissions(Authorize, ['admin'])

    return RoleGroupService().get_group_resources(group_id,
                                                  resource_type=ResourceTypeEnum(resource_type),
                                                  name=name,
                                                  page_size=page_size,
                                                  page_num=page_num)