# build router
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.user import UserGroupEmptyError
from bisheng.database.models.group import Group, GroupCreate
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user_group import UserGroupDao

router = APIRouter(prefix='/group', tags=['User'], dependencies=[Depends(UserPayload.get_login_user)])


@router.get('/list')
async def get_all_group(login_user: UserPayload = Depends(UserPayload.get_login_user)):
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
            raise UnAuthorizedError()

    groups_res = RoleGroupService().get_group_list(groups)
    return resp_200({'records': groups_res})


@router.post('/create')
async def create_group(request: Request, group: GroupCreate,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    新建用户组
    """
    return resp_200(RoleGroupService().create_group(request, login_user, group))


@router.put('/create')
async def update_group(request: Request,
                       group: Group,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    编辑用户组
    """
    return resp_200(RoleGroupService().update_group(request, login_user, group))


@router.delete('/create', status_code=200)
async def delete_group(request: Request,
                       group_id: int,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    删除用户组
    """

    return RoleGroupService().delete_group(request, login_user, group_id)


@router.post('/set_user_group')
async def set_user_group(request: Request,
                         user_id: Annotated[int, Body(embed=True)],
                         group_id: Annotated[List[int], Body(embed=True)],
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    设置用户分组, 批量替换, 根据操作人权限不同，替换不同的用户组
    用户组管理就只替换他拥有权限的用户组。超级管理员全量替换
    """
    if not group_id:
        raise UserGroupEmptyError()
    return resp_200(RoleGroupService().replace_user_groups(request, login_user, user_id, group_id))


@router.get('/get_user_group')
async def get_user_group(user_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    获取用户所属分组
    """
    return resp_200(RoleGroupService().get_user_groups_list(user_id))


@router.get('/get_group_user')
async def get_group_user(group_id: int,
                         page_size: int = None,
                         page_num: int = None,
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    获取分组用户
    """
    return RoleGroupService().get_group_user_list(group_id, page_size, page_num)


@router.post('/set_group_admin')
async def set_group_admin(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    获取分组的admin，批量设置接口，覆盖历史的admin
    """

    return resp_200(RoleGroupService().set_group_admin(request, login_user, user_ids, group_id))


@router.post('/set_update_user', status_code=200)
async def set_update_user(group_id: Annotated[int, Body(embed=True)],
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    更新用户组的最近修改人
    """
    return resp_200(RoleGroupService().set_group_update_user(login_user, group_id))


@router.get('/get_group_resources')
async def get_group_resources(*,
                              group_id: int,
                              resource_type: int,
                              name: Optional[str] = None,
                              page_size: Optional[int] = 10,
                              page_num: Optional[int] = 1,
                              user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    获取用户组下的资源列表
    """
    # 判断是否是用户组的管理员
    if not user.check_group_admin(group_id):
        return UnAuthorizedError.return_resp()
    res, total = await RoleGroupService().get_group_resources(
        group_id,
        resource_type=ResourceTypeEnum(resource_type),
        name=name,
        page_size=page_size,
        page_num=page_num)
    return resp_200(data={
        "data": res,
        "total": total
    })


@router.get("/roles")
async def get_group_roles(*,
                          group_id: List[int] = Query(..., description="用户组ID列表"),
                          keyword: str = Query(None, description="搜索关键字"),
                          page: int = 0,
                          limit: int = 0,
                          user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    获取用户组内的角色列表
    """
    # 判断是否是用户组的管理员
    if not user.check_groups_admin(group_id):
        return UnAuthorizedError.return_resp()
    # 查询组下角色列表
    role_list = RoleDao.get_role_by_groups(group_id, keyword, page, limit)
    total = RoleDao.count_role_by_groups(group_id, keyword)

    return resp_200(data={
        "data": role_list,
        "total": total
    })


@router.get("/manage/resources")
async def get_manage_resources(login_user: UserPayload = Depends(UserPayload.get_login_user),
                               keyword: str = Query(None, description="搜索关键字"),
                               page: int = 1,
                               page_size: int = 10):
    """ 获取管理的用户组下的应用列表 """
    res, total = RoleGroupService().get_manage_resources(login_user, keyword, page, page_size)
    return resp_200(data={
        "data": res,
        "total": total
    })
