# build router
from typing import List, Annotated

from bisheng.api.JWT import get_login_user
from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import check_permissions
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group import GroupRead
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.user_group import UserGroupCreate, UserGroupRead
from fastapi import APIRouter, Body, Depends, Query
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/group', tags=['User'])


@router.get('/list', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_all_group(Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.post('/set_user_group', response_model=UnifiedResponseModel[UserGroupRead])
async def set_user_group(user_group: UserGroupCreate, Authorize: AuthJWT = Depends()):
    """
    设置用户分组
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().insert_user_group(user_group)


@router.get('/get_user_group', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_user_group(user_id: int, Authorize: AuthJWT = Depends()):
    """
    获取用户所属分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_user_groups_list(user_id)


@router.post('/set_group_admin', response_model=UnifiedResponseModel[List[UserGroupRead]])
async def set_group_admin(user_ids: Annotated[List[int], Body(embed=True)],
                          group_id: Annotated[int, Body(embed=True)],
                          Authorize: AuthJWT = Depends()):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """
    await check_permissions(Authorize, ['admin'])
    return RoleGroupService().set_group_admin(user_ids, group_id)


@router.get('/get_group_flows', response_model=UnifiedResponseModel[List[UserGroupRead]])
async def get_group_flows(*,
                          group_id: Annotated[int, Body(embed=True)],
                          resource_type: Annotated[int, Body(embed=True)],
                          Authorize: AuthJWT = Depends()):
    """
    获取所有分组
    """
    # await check_permissions(Authorize, ['admin'])
    return RoleGroupService().get_group_list()


@router.get("/roles", response_model=UnifiedResponseModel[GroupRead])
async def get_group_roles(*,
                          group_id: int = Query(..., description="用户组ID"),
                          keyword: str = Query(None, description="搜索关键字"),
                          page: int = 1,
                          limit: int = 10,
                          user: UserPayload = Depends(get_login_user)):
    """
    获取用户组内的角色列表
    """
    return resp_200(data={
        "data": [
            {
                "id": "role-id",
                "name": "角色名字",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            },
            {
                "id": "role-id",
                "name": "角色名字2",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            }
        ],
        "total": 10
    })


@router.get("/assistant", response_model=UnifiedResponseModel[GroupRead])
async def get_group_assistant(*,
                              group_id: int = Query(..., description="用户组ID"),
                              keyword: str = Query(None, description="搜索关键字"),
                              page: int = 1,
                              limit: int = 10,
                              user: UserPayload = Depends(get_login_user)):
    """
    获取用户组可见的助手列表
    """
    return resp_200(data={
        "data": [
            {
                "id": "assistant-id",
                "name": "助手名字",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            },
            {
                "id": "assistant-id",
                "name": "助手名字2",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            }
        ],
        "total": 10
    })


@router.get("/knowledge", response_model=UnifiedResponseModel[GroupRead])
async def get_group_knowledge(*,
                              group_id: int = Query(..., description="用户组ID"),
                              keyword: str = Query(None, description="搜索关键字"),
                              page: int = 1,
                              limit: int = 10,
                              user: UserPayload = Depends(get_login_user)):
    """
    获取用户组可见的知识库列表
    """
    return resp_200(data={
        "data": [
            {
                "id": "knowledge-id",
                "name": "知识库名字",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            },
            {
                "id": "knowledge-id",
                "name": "知识库名字2",
                "create_user": "xxx",
                "create_time": "2022-01-01 00:00:00"
            }
        ],
        "total": 10
    })
