"""User group CRUD API endpoints (F003)."""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.user_group.domain.schemas.user_group_schema import (
    UserGroupCreate,
    UserGroupUpdate,
)
from bisheng.user_group.domain.services.user_group_service import UserGroupService

router = APIRouter()


@router.post('/')
async def create_group(
    data: UserGroupCreate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.acreate_group(data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()


@router.get('/')
async def list_groups(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=2000),
    keyword: str = Query(''),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.alist_groups(page, limit, keyword, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()


@router.get('/{group_id}')
async def get_group(
    group_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.aget_group(group_id, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()


@router.put('/{group_id}')
async def update_group(
    group_id: int,
    data: UserGroupUpdate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await UserGroupService.aupdate_group(group_id, data, login_user)
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp()


@router.delete('/{group_id}')
async def delete_group(
    group_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        await UserGroupService.adelete_group(group_id, login_user)
        return resp_200()
    except BaseErrorCode as e:
        return e.return_resp()
