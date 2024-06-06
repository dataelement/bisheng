# build router
from typing import List

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.database.models.group import GroupRead
from bisheng.database.models.user_group import UserGroupCreate, UserGroupRead
from fastapi import APIRouter, Depends
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='group', tags=['User'])


@router.get('/list', response_model=UnifiedResponseModel(List[GroupRead]))
async def get_all_group(Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.post('/set_user_group', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def set_user_group(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    设置用户分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.post('/get_user_group', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def get_user_group(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    获取用户所属分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.post('/set_group_admin', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def set_group_admin(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.get('/get_group_flows', response_model=UnifiedResponseModel(List[UserGroupRead]))
async def get_group_flows(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()
