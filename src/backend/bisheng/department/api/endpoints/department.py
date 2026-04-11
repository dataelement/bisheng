"""Department CRUD + tree + move API endpoints.

Part of F002-department-tree.
"""

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.department.domain.schemas.department_schema import (
    DepartmentCreate,
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
