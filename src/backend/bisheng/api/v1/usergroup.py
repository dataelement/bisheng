# build router
import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.api.services.role_group_service import RoleGroupService
from bisheng.api.v1.schemas import resp_200
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.user import UserGroupEmptyError
from bisheng.database.models.group import Group, GroupCreate, GroupDao
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.role.domain.services.role_service import RoleService

router = APIRouter(prefix='/group', tags=['User'], dependencies=[Depends(UserPayload.get_login_user)])
logger = logging.getLogger(__name__)


async def _can_use_v25_role_catalog(user: UserPayload) -> bool:
    if user.is_admin():
        return True

    from bisheng.database.models.department import DepartmentDao
    from bisheng.permission.domain.services.permission_service import PermissionService

    try:
        admin_depts = await DepartmentDao.aget_user_admin_departments(user.user_id)
    except Exception:
        logger.exception(
            'get_group_roles: department admin check failed user=%s',
            getattr(user, 'user_id', None),
        )
        admin_depts = []
    if admin_depts:
        return True

    try:
        return await PermissionService.check(
            user_id=user.user_id,
            relation='admin',
            object_type='tenant',
            object_id=str(user.tenant_id),
            login_user=user,
        )
    except Exception:
        logger.exception(
            'get_group_roles: tenant admin check failed user=%s',
            getattr(user, 'user_id', None),
        )
        return False


@router.get('/list')
async def get_all_group(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get all groups（PRD：超管全量；其他用户见公开组 + 自建/加入的私密组）
    """
    if login_user.is_admin():
        groups_res = RoleGroupService().get_group_list([])
    else:
        groups, _ = await GroupDao.aget_visible_groups(login_user.user_id, 1, 5000, '')
        groups_res = RoleGroupService().enrich_group_reads(groups)
    return resp_200({'records': groups_res, 'total': len(groups_res)})


@router.post('/create')
async def create_group(request: Request, group: GroupCreate,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    Add Usergroup
    """
    return resp_200(RoleGroupService().create_group(request, login_user, group))


@router.put('/create')
async def update_group(request: Request,
                       group: Group,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    Can edit existing usergroups
    """
    return resp_200(RoleGroupService().update_group(request, login_user, group))


@router.delete('/create', status_code=200)
async def delete_group(request: Request,
                       group_id: int,
                       login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    Can delete existing usergroups
    """

    return RoleGroupService().delete_group(request, login_user, group_id)


@router.post('/set_user_group')
async def set_user_group(request: Request,
                         user_id: Annotated[int, Body(embed=True)],
                         group_id: Annotated[List[int], Body(embed=True)],
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Set up user groups, Batch Replacement, Replace different user groups according to different operation permissions
    User group management replaces only the user groups for which he has permissions. Super Admin Full Replacement
    """
    if not group_id:
        raise UserGroupEmptyError()
    return resp_200(RoleGroupService().replace_user_groups(request, login_user, user_id, group_id))


@router.get('/get_user_group')
async def get_user_group(user_id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get the group to which the user belongs
    """
    return resp_200(RoleGroupService().get_user_groups_list(user_id))


@router.get('/get_group_user')
async def get_group_user(group_id: int,
                         page_size: int = None,
                         page_num: int = None,
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get grouped users
    """
    return resp_200(RoleGroupService().get_group_user_list(group_id, page_size, page_num))


@router.post('/set_group_admin')
async def set_group_admin(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    Get groupingadmin, batch setting interface, overriding the historicaladmin
    """

    return resp_200(RoleGroupService().set_group_admin(request, login_user, user_ids, group_id))

@router.post('/set_group_members')
async def set_group_members(
        request: Request,
        user_ids: Annotated[List[int], Body(embed=True)],
        group_id: Annotated[int, Body(embed=True)],
        login_user: UserPayload = Depends(UserPayload.get_admin_user)):
    """
    Batch set group members (non-admin), overriding the historical members
    """
    return resp_200(RoleGroupService().set_group_members(request, login_user, user_ids, group_id))


@router.post('/set_update_user', status_code=200)
async def set_update_user(group_id: Annotated[int, Body(embed=True)],
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Update user group last modified by
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
    Get a list of resources under a user group
    """
    # Determine if you are an administrator of a user group
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
                          group_id: List[int] = Query(..., description="User GroupsIDVertical"),
                          keyword: str = Query(None, description="Search keyword ..."),
                          page: int = 0,
                          limit: int = 0,
                          user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    Get a list of roles within a user group
    """
    # v2.5 roles are tenant/department scoped and usually have group_id=NULL.
    # The user-role editor still calls this legacy endpoint, so v2.5 admins
    # must read from the visible role catalog instead of filtering by
    # role.group_id, otherwise global/default roles disappear from the selector.
    if await _can_use_v25_role_catalog(user):
        result = await RoleService.list_roles(
            keyword=keyword,
            page=page or 1,
            limit=limit or 0,
            login_user=user,
            include_global_for_binding=True,
        )
        return resp_200(data=result)

    # Determine if you are an administrator of a user group
    if not user.check_groups_admin(group_id):
        return UnAuthorizedError.return_resp()
    # List of roles under query group
    role_list = RoleDao.get_role_by_groups(group_id, keyword, page, limit)
    total = RoleDao.count_role_by_groups(group_id, keyword)

    return resp_200(data={
        "data": role_list,
        "total": total
    })


@router.get("/manage/resources")
async def get_manage_resources(login_user: UserPayload = Depends(UserPayload.get_login_user),
                               keyword: str = Query(None, description="Search keyword ..."),
                               page: int = 1,
                               page_size: int = 10):
    """ Get a list of apps under a managed user group """
    res, total = await RoleGroupService().get_manage_resources(login_user, keyword, page, page_size)
    return resp_200(data={
        "data": res,
        "total": total
    })
