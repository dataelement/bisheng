"""Department member management API endpoints.

Part of F002-department-tree.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.department.domain.schemas.department_schema import (
    DepartmentLocalMemberCreate,
    DepartmentMemberAdd,
    DepartmentMemberEditApply,
)
from bisheng.department.domain.services.department_service import DepartmentService

router = APIRouter()


@router.get('/{dept_id}/members/{user_id}/edit-form')
async def get_member_edit_form(
    dept_id: str,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await DepartmentService.aget_member_edit_form(
            dept_id, user_id, login_user,
        )
        return resp_200(data)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{dept_id}/members/{user_id}/apply-edit')
async def apply_member_edit(
    dept_id: str,
    user_id: int,
    data: DepartmentMemberEditApply,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.aapply_member_edit(dept_id, user_id, data, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{dept_id}/members')
async def get_members(
    dept_id: str,
    page: int = 1,
    limit: int = 20,
    keyword: str = '',
    is_primary: Optional[int] = Query(None, description='Filter: 1=primary, 0=secondary'),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await DepartmentService.aget_members(
            dept_id, page, limit, keyword, login_user,
            is_primary=is_primary,
        )
        return resp_200(data)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{dept_id}/members')
async def add_members(
    dept_id: str,
    data: DepartmentMemberAdd,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.aadd_members(dept_id, data, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{dept_id}/assignable-roles')
async def list_assignable_roles(
    dept_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await DepartmentService.aget_assignable_roles(dept_id, login_user)
        return resp_200(data)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/{dept_id}/local-members')
async def create_local_member(
    dept_id: str,
    data: DepartmentLocalMemberCreate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        out = await DepartmentService.acreate_local_member(dept_id, data, login_user)
        return resp_200(out)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/{dept_id}/members/{user_id}/delete-check')
async def check_local_member_delete(
    dept_id: str,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await DepartmentService.acheck_local_member_delete(
            dept_id, user_id, login_user,
        )
        return resp_200(data)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{dept_id}/members/{user_id}/local-account')
async def delete_local_organization_member(
    dept_id: str,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.adelete_local_organization_member(
            dept_id, user_id, login_user,
        )
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete('/{dept_id}/members/{user_id}')
async def remove_member(
    dept_id: str,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await DepartmentService.aremove_member(dept_id, user_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp_instance()
