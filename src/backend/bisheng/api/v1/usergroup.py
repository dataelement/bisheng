# build router
from typing import List, Annotated
from uuid import UUID
import json
from typing import Annotated, List, Optional

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
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group import Group, GroupCreate, GroupRead
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.user import User
from bisheng.database.models.user_group import UserGroupDao, UserGroupRead
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT

router = APIRouter(prefix='/group', tags=['User'])


@router.get('/list', response_model=UnifiedResponseModel[List[GroupRead]])
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

    groups_res = RoleGroupService().get_group_list(groups)
    return resp_200({'records': groups_res})


@router.post('/create', response_model=UnifiedResponseModel[GroupRead], status_code=200)
async def create_group(group: GroupCreate, Authorize: AuthJWT = Depends()):
    """
    新建用户组
    """
    await check_permissions(Authorize, ['admin'])
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    return resp_200(RoleGroupService().create_group(login_user, group))


@router.put('/create', response_model=UnifiedResponseModel[GroupRead], status_code=200)
async def update_group(group: Group, Authorize: AuthJWT = Depends()):
    """
    编辑用户组
    """
    await check_permissions(Authorize, ['admin'])
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    return resp_200(RoleGroupService().update_group(login_user, group))


@router.delete('/create', status_code=200)
async def delete_group(group_id: int, Authorize: AuthJWT = Depends()):
    """
    删除用户组
    """
    await check_permissions(Authorize, ['admin'])
    return resp_200(RoleGroupService().delete_group(group_id))


@router.post('/set_user_group',
             response_model=UnifiedResponseModel[UserGroupRead],
             status_code=200)
async def set_user_group(user_id: Annotated[int, Body(embed=True)],
                         group_id: Annotated[List[int], Body(embed=True)],
                         Authorize: AuthJWT = Depends()):
    """
    设置用户分组, 批量替换
    """
    await check_permissions(Authorize, ['admin'])
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    return resp_200(RoleGroupService().replace_user_groups(login_user, user_id, group_id))


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
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    return resp_200(RoleGroupService().set_group_admin(login_user, user_ids, group_id))


@router.post('/set_update_user', status_code=200)
async def set_update_user(group_id: Annotated[int, Body(embed=True)],
                          Authorize: AuthJWT = Depends()):
    """
    更新用户组的最近修改人
    """
    # await check_permissions(Authorize, ['admin'])
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    return resp_200(RoleGroupService().set_group_update_user(login_user, group_id))


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
