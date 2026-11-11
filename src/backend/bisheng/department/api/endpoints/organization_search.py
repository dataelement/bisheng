"""Dedicated organization-page search; picker contracts remain unchanged."""

from typing import Literal

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.department.domain.services.organization_search_service import OrganizationSearchService

router = APIRouter()


@router.get("/search/directory")
async def search_directory(
    keyword: str = "",
    kind: Literal["members", "departments"] = "members",
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    include_archived: bool = False,
    preferred_department_id: int | None = None,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        result = await OrganizationSearchService.search(
            login_user,
            keyword,
            kind,
            page,
            limit,
            include_archived,
            preferred_department_id,
        )
        return resp_200(PageData[dict](**result))
    except BaseErrorCode as error:
        return error.return_resp_instance()


@router.get("/{dept_id}/members/locate")
async def locate_member(
    dept_id: str,
    user_id: int = Query(..., ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_primary: int | None = Query(None, ge=0, le=1),
    include_archived: bool = False,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        return resp_200(
            await OrganizationSearchService.locate_member(
                login_user,
                dept_id,
                user_id,
                limit,
                is_primary,
                include_archived,
            )
        )
    except BaseErrorCode as error:
        return error.return_resp_instance()
