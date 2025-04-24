# build router
import json
from typing import Annotated, List, Optional
from uuid import UUID

from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.flow import FlowDao
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.database.models.knowledge import KnowledgeDao
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi_jwt_auth import AuthJWT

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.services.user_service import UserPayload, get_login_user, get_admin_user
from bisheng.api.utils import check_permissions
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.database.models.group_resource import GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.role import RoleDao
from bisheng.database.models.group import Group, GroupCreate, GroupRead
from bisheng.database.models.user import User
from bisheng.database.models.user_group import UserGroupDao, UserGroupRead

router = APIRouter(prefix='/group', tags=['Group'], dependencies=[Depends(get_login_user)])


@router.get('/list', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_all_group(login_user: UserPayload = Depends(get_login_user),
                        page: Optional[int] = Query(default=1, description='页码'),
                        page_size: Optional[int] = Query(default=10, description='每页条数'),
                        keyword: Optional[str] = Query(default=None,description='匹配关键字')):
    """
    获取所有分组
    """
    if login_user.is_admin():
        groups = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        groups = []
        for one in user_groups:
            if one.is_group_admin:
                groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')

    groups_res = RoleGroupService().get_group_list(groups)
    if page and page_size:
        groups_res = groups_res[(page-1) * page_size:page * page_size]
    if keyword:
        groups_res = [one for one in groups_res if keyword in one.group_name]
    return resp_200({'records': groups_res})

@router.get('/list_v2', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_all_group2(login_user: UserPayload = Depends(get_login_user),
                        page: Optional[int] = Query(default=1, description='页码'),
                        page_size: Optional[int] = Query(default=10, description='每页条数'),
                        keyword: Optional[str] = Query(default=None,description='匹配关键字')):
    """
    获取所有分组
    """
    if login_user.is_admin():
        groups = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        groups = []
        for one in user_groups:
            if one.is_group_admin:
                groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')

    groups_res = RoleGroupService().get_group_list(groups)
    if keyword:
        groups_res = [one for one in groups_res if keyword in one.group_name]
    total = len(groups_res)
    if page and page_size:
        groups_res = groups_res[(page-1) * page_size:page * page_size]
    return resp_200({'data': groups_res,'total': total})

@router.get('/list_operation', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_all_group(*,login_user: UserPayload = Depends(get_login_user),
                        keyword: Optional[str] = Query(default=None,description='匹配关键字')):
    """
    获取所有分组
    """
    if login_user.is_admin():
        groups = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_operation_or_admin_group(login_user.user_id)
        groups = []
        for one in user_groups:
            groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')

    groups_res = RoleGroupService().get_group_list(groups)
    if keyword:
        groups_res = [one for one in groups_res if keyword in one.group_name]
    return resp_200({'data': groups_res,'total': len(groups_res)})

@router.get('/list_audit', response_model=UnifiedResponseModel[List[GroupRead]])
async def get_all_group(*,login_user: UserPayload = Depends(get_login_user),
                        keyword: Optional[str] = Query(default=None,description='匹配关键字')):
    """
    获取所有分组
    """
    if login_user.is_admin():
        groups = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_audit_or_admin_group(login_user.user_id)
        groups = []
        for one in user_groups:
            groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')
    groups_res = RoleGroupService().get_group_list(groups)
    if keyword:
        groups_res = [one for one in groups_res if keyword in one.group_name]
    return resp_200({'data': groups_res,'total': len(groups_res)})


@router.get('/tree')
async def get_all_group_tree(login_user: UserPayload = Depends(get_login_user),
                             group_id: Optional[int] = None):
    """
    获取所有分组树
    """
    if login_user.is_admin():
        groups = [group_id] if group_id else []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        groups = []
        for one in user_groups:
            if one.is_group_admin:
                groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise UnAuthorizedError.http_exception()
        if group_id:
            if group_id not in groups:
                raise UnAuthorizedError.http_exception()
            groups = [group_id]

    groups_res = RoleGroupService().get_group_tree(groups)
    return resp_200(groups_res)


@router.post('/create', response_model=UnifiedResponseModel[GroupRead], status_code=200)
async def create_group(request: Request, login_user: UserPayload = Depends(get_admin_user),
                       group: GroupCreate = Body(...)):
    """
    新建用户组
    """
    return resp_200(RoleGroupService().create_group(request, login_user, group))


@router.put('/create', response_model=UnifiedResponseModel[GroupRead], status_code=200)
async def update_group(request: Request,
                       group: Group,
                       login_user: UserPayload = Depends(get_login_user)):
    """
    编辑用户组
    """
    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return resp_200(RoleGroupService().update_group(request, login_user, group))


@router.delete('/create', status_code=200)
async def delete_group(request: Request,
                       group_id: int,
                       login_user: UserPayload = Depends(get_login_user)):
    """
    删除用户组
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return RoleGroupService().delete_group(request, login_user, group_id)


@router.post('/set_user_group',
             response_model=UnifiedResponseModel[UserGroupRead],
             status_code=200)
async def set_user_group(request: Request,
                         user_id: Annotated[int, Body(embed=True)],
                         group_id: Annotated[List[int], Body(embed=True)],
                         login_user: UserPayload = Depends(get_login_user)):
    """
    设置用户分组, 批量替换, 根据操作人权限不同，替换不同的用户组
    用户组管理就只替换他拥有权限的用户组。超级管理员全量替换
    """
    if not group_id:
        raise HTTPException(status_code=500, detail='用户组不能为空')
    return resp_200(RoleGroupService().replace_user_groups(request, login_user, user_id, group_id))


@router.get('/get_user_group',
            response_model=UnifiedResponseModel[List[GroupRead]],
            status_code=200)
async def get_user_group(user_id: int, Authorize: AuthJWT = Depends()):
    """
    获取用户所属分组
    """
    # await check_permissions(Authorize, ['admin'])
    return resp_200(RoleGroupService().get_user_groups_list(user_id))


@router.get('/get_app_list')
async def get_app_list(
                         page_size: int = None,
                         page_num: int = None,
        login_user: UserPayload = Depends(get_login_user)):
    """
    获取用户管理的用户组下所有的应用
    """

    groups = UserGroupDao.get_user_admin_group(login_user.user_id)
    all_resources = []
    for gruop_id in groups:
        resource = GroupResourceDao.get_group_all_resource(gruop_id)
        all_resources.extend(resource)

    for r in all_resources:
        if r.type.value == ResourceTypeEnum.FLOW.value:
            r.name = FlowDao.get_flow_by_id(r.third_id).name
        elif r.type.value == ResourceTypeEnum.KNOWLEDGE.value:
            r.name =KnowledgeDao.query_by_id(r.third_id).name
        elif r.type.value == ResourceTypeEnum.ASSISTANT.value:
            r.name =AssistantDao.get_one_assistant(UUID(r.third_id)).name
        elif r.type.value == ResourceTypeEnum.GPTS_TOOL.value:
            r.name =GptsToolsDao.get_one_tool(r.third_id).name


    all_user = []

    for g in groups:
        user_list, _ = RoleGroupService().get_group_user_list(g.id, page_num, page_size)
        all_user.extend(user_list)

    data = {"app_list": all_resources, "user_list": all_user,"un_mark":100}

    return resp_200(data=data)

@router.get('/get_group_user', response_model=UnifiedResponseModel[List[User]], status_code=200)
async def get_group_user(group_id: int,
                         page: int = None,
                         limit: int = None,
                         login_user: UserPayload = Depends(get_login_user)):
    """
    获取分组下的用户，包含子用户组
    """
    if not login_user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()
    res, total = RoleGroupService().get_group_user_list(group_id, page, limit)
    return resp_200({
        'data': res,
        'total': total
    })


@router.post('/set_group_admin',
             response_model=UnifiedResponseModel[List[UserGroupRead]],
             status_code=200)
async def set_group_admin(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(get_login_user)):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return resp_200(RoleGroupService().set_group_admin(request, login_user, user_ids, group_id))

@router.post('/set_group_operation',
             response_model=UnifiedResponseModel[List[UserGroupRead]],
             status_code=200)
async def set_group_operation(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(get_login_user)):
    """
    获取分组的admin，批量设置接口，覆盖历史的operation
    """

    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return resp_200(RoleGroupService().set_group_operation(request, login_user, user_ids, group_id))

@router.post('/set_group_audit',
             response_model=UnifiedResponseModel[List[UserGroupRead]],
             status_code=200)
async def set_group_audit(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(get_login_user)):
    """
    获取分组的admin，批量设置接口，覆盖历史的audit
    """
    if not login_user.is_admin():
        return UnAuthorizedError.return_resp()
    return resp_200(RoleGroupService().set_group_audit(request, login_user, user_ids, group_id))


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


@router.get('/get_group_resources',
            response_model=UnifiedResponseModel[List[UserGroupRead]],
            status_code=200)
async def get_group_resources(*,
                              group_id: int,
                              resource_type: int,
                              name: Optional[str] = None,
                              page_size: Optional[int] = 10,
                              page_num: Optional[int] = 1,
                              user: UserPayload = Depends(get_login_user)):
    """
    获取用户组下的资源列表
    """
    # 判断是否是用户组的管理员
    if not user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()
    res, total = RoleGroupService().get_group_resources(
        group_id,
        resource_type=ResourceTypeEnum(resource_type),
        name=name,
        page_size=page_size,
        page_num=page_num)
    return resp_200(data={
        "data": res,
        "total": total
    })

@router.get("/manage/resources", response_model=UnifiedResponseModel)
async def get_manage_resources(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                               keyword: str = Query(None, description="搜索关键字"),
                               page: int = 1,
                               page_size: int = 10):
    """ 获取管理的用户组下的应用列表 """
    res, total = RoleGroupService().get_manage_resources(request, login_user, keyword, page, page_size)
    return resp_200(data={
        "data": res,
        "total": total
    })

@router.get("/operation/resources", response_model=UnifiedResponseModel)
async def get_operation_resources(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                               keyword: str = Query(None, description="搜索关键字"),
                               page: int = 1,
                               page_size: int = 10):
    """ 获取管理的用户组下的应用列表 """
    res, total = RoleGroupService().get_operation_resources(request, login_user, keyword, page, page_size)
    return resp_200(data={
        "data": res,
        "total": total
    })
@router.get("/audit/resources", response_model=UnifiedResponseModel)
async def get_audit_resources(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                               keyword: str = Query(None, description="搜索关键字"),
                               page: int = 1,
                               page_size: int = 10):
    """ 获取管理的用户组下的应用列表 """
    res, total = RoleGroupService().get_audit_resources(request, login_user, keyword, page, page_size)
    return resp_200(data={
        "data": res,
        "total": total
    })

@router.get("/roles", response_model=UnifiedResponseModel)
async def get_group_roles(*,
                          group_id: list[int] = Query(None, description="用户组ID列表，不传则查询所有有权限的角色列表"),
                          keyword: str = Query(None, description="搜索关键字"),
                          include_parent: bool = Query(False, description="是否包含父用户组绑定的角色"),
                          page: int = 0,
                          limit: int = 0,
                          user: UserPayload = Depends(get_login_user)):
    """
    获取用户组内的角色列表
    """
    res, total = RoleGroupService().get_group_roles(user, group_id, keyword, page, limit, include_parent)

    return resp_200(data={
        "data": res,
        "total": total
    })


@router.get("/user/roles", response_model=UnifiedResponseModel)
async def get_user_group_roles(login_user: UserPayload = Depends(get_login_user),
                               user_id: int = Query(None, description="用户ID"),
                               group_id: int = Query(None, description="用户组ID")):
    """
    获取用户 在指定用户组内的角色列表
    """
    res = RoleGroupService().get_user_group_roles(login_user, user_id, group_id)
    return resp_200(data={
        'data':res
    })
