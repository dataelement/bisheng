# build router
from typing import List, Annotated
from uuid import UUID

from bisheng.api.JWT import get_login_user
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.assistant import AssistantService
from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import check_permissions
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200, AssistantSimpleInfo
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.group import GroupRead
from bisheng.database.models.group_resource import ResourceTypeEnum, GroupResourceDao
from bisheng.database.models.knowledge import KnowledgeDao
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user import UserDao
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


@router.get("/roles", response_model=UnifiedResponseModel)
async def get_group_roles(*,
                          group_id: int = Query(..., description="用户组ID"),
                          keyword: str = Query(None, description="搜索关键字"),
                          page: int = 1,
                          limit: int = 10,
                          user: UserPayload = Depends(get_login_user)):
    """
    获取用户组内的角色列表
    """
    # 判断是否是用户组的管理员
    if not user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()
    # 查询组下角色列表
    role_list = RoleDao.get_role_by_groups([group_id], keyword, page, limit)
    total = RoleDao.count_role_by_groups([group_id], keyword)

    return resp_200(data={
        "data": role_list,
        "total": total
    })


@router.get("/assistant", response_model=UnifiedResponseModel[List[AssistantSimpleInfo]])
async def get_group_assistant(*,
                              group_id: int = Query(..., description="用户组ID"),
                              keyword: str = Query(None, description="搜索关键字"),
                              page: int = 1,
                              limit: int = 10,
                              user: UserPayload = Depends(get_login_user)):
    """
    获取用户组可见的助手列表
    """
    # 判断是否是用户组的管理员
    if not user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()

    # 查询用户组下的助手ID列表
    resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.ASSISTANT)
    res = []
    total = 0
    if resource_list:
        assistant_ids = [UUID(resource.third_id) for resource in resource_list]        # 查询助手
        data, total = AssistantDao.filter_assistant_by_id(assistant_ids, keyword, page, limit)
        for one in data:
            simple_one = AssistantService.return_simple_assistant_info(one)
            res.append(simple_one)
    return resp_200(data={
        "data": res,
        "total": total
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

    # 判断是否是用户组的管理员
    if not user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()

    # 查询用户组下的知识库ID列表
    resource_list = GroupResourceDao.get_group_resource(group_id, ResourceTypeEnum.KNOWLEDGE)
    res = []
    total = 0
    if resource_list:
        knowledge_ids = [int(resource.third_id) for resource in resource_list]
        # 查询知识库
        data, total = KnowledgeDao.filter_knowledge_by_ids(knowledge_ids, keyword, page, limit)
        db_user_ids = {one.user_id for one in data}
        user_list = UserDao.get_user_by_ids(list(db_user_ids))
        user_map = {user.user_id: user.user_name for user in user_list}
        for one in data:
            one_dict = one.model_dump()
            one_dict["user_name"] = user_map.get(one.user_id, one.user_id)
            res.append(one_dict)
    return resp_200(data={
        "data": res,
        "total": total
    })
