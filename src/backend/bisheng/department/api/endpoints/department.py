"""Department CRUD + tree + move API endpoints.

Part of F002-department-tree.
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.department.domain.schemas.department_schema import (
    DepartmentAdminSet,
    DepartmentCreate,
    DepartmentLocalMemberCreate,
    DepartmentLocalMemberCreateWithDeptId,
    DepartmentMoveRequest,
    DepartmentUpdate,
)
from bisheng.department.domain.services.department_service import DepartmentService

router = APIRouter()


@router.post('/')
async def create_department(
    data: DepartmentCreate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        dept = await DepartmentService.acreate_department(data, login_user)
        return resp_200(dept.model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/tree')
async def get_tree(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        tree = await DepartmentService.aget_tree(login_user)
        return resp_200([node.model_dump() for node in tree])
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/local-members')
async def create_local_member_body(
    data: DepartmentLocalMemberCreateWithDeptId,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """创建本地人员（dept_id 在 body）。必须放在 ``GET /{dept_id}`` 之前，否则 ``local-members`` 会被当成 dept_id 导致 POST→405。"""
    try:
        inner = DepartmentLocalMemberCreate(
            user_name=data.user_name,
            person_id=data.person_id,
            password=data.password,
            role_ids=data.role_ids,
        )
        out = await DepartmentService.acreate_local_member(data.dept_id, inner, login_user)
        return resp_200(out)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/get_user_primary_department')
async def get_user_primary_department(
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the user's primary department. Called by Gateway for traffic control."""
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    ud = await UserDepartmentDao.aget_user_primary_department(user_id)
    if not ud:
        return resp_200([])
    dept = await DepartmentDao.aget_by_id(ud.department_id)
    if not dept:
        return resp_200([])
    return resp_200([{'id': dept.id, 'dept_id': dept.dept_id, 'name': dept.name}])


@router.get('/{dept_id}')
async def get_department(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await DepartmentService.aget_department(dept_id, login_user)
        return resp_200(data)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/{dept_id}')
async def update_department(
    dept_id: str,
    data: DepartmentUpdate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        dept = await DepartmentService.aupdate_department(dept_id, data, login_user)
        return resp_200(dept.model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{dept_id}')
async def delete_department(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.adelete_department(dept_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{dept_id}/purge')
async def purge_department(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.apurge_department(dept_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{dept_id}/restore')
async def restore_department(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.arestore_department(dept_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{dept_id}/move')
async def move_department(
    dept_id: str,
    data: DepartmentMoveRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        dept = await DepartmentService.amove_department(dept_id, data, login_user)
        return resp_200(dept.model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{dept_id}/admins')
async def get_department_admins(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        admins = await DepartmentService.aget_admins(dept_id, login_user)
        return resp_200(admins)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put('/{dept_id}/admins')
async def set_department_admins(
    dept_id: str,
    data: DepartmentAdminSet,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await DepartmentService.aset_admins(
            dept_id, data.user_ids, login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()
