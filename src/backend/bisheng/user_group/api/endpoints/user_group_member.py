"""User group member management API endpoints (F003)."""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.user_group.domain.schemas.user_group_schema import (
    UserGroupAdminSet,
    UserGroupMemberAdd,
    UserGroupMemberSync,
)
from bisheng.user_group.domain.services.user_group_service import UserGroupService

router = APIRouter()


@router.get('/{group_id}/members')
async def get_members(
    group_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=2000),
    keyword: str = Query(''),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.aget_members(
            group_id, page, limit, keyword, login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()


@router.post('/{group_id}/members')
async def add_members(
    group_id: int,
    data: UserGroupMemberAdd,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await UserGroupService.aadd_members(group_id, data.user_ids, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp()


@router.post('/{group_id}/members/sync')
@router.put('/{group_id}/members/sync')
async def sync_plain_members(
    group_id: int,
    data: UserGroupMemberSync,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await UserGroupService.async_plain_members(
            group_id, data.user_ids, login_user,
        )
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp()


@router.delete('/{group_id}/members/{user_id}')
async def remove_member(
    group_id: int,
    user_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await UserGroupService.aremove_member(group_id, user_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp()


@router.put('/{group_id}/admins')
async def set_admins(
    group_id: int,
    data: UserGroupAdminSet,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.aset_admins(
            group_id, data.user_ids, login_user,
        )
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()
