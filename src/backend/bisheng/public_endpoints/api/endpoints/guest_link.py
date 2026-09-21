"""Management API for the per-app guest-link switch. Path must not contain 'config'."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.public_endpoints.domain.services.guest_link import (
    GuestLinkPatchRequest,
    get_guest_link_settings,
    patch_guest_link_settings,
    write_guest_link_audit,
)
from bisheng.utils import get_request_ip

router = APIRouter(prefix="/guest-link", tags=["GuestLink"])

GuestResourcePath = Literal["workflow", "assistant"]


@router.get("/{resource_type}/{resource_id}")
async def get_guest_link(
    resource_type: GuestResourcePath,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await get_guest_link_settings(login_user, resource_type, resource_id)
    return resp_200(data=data)


@router.patch("/{resource_type}/{resource_id}")
async def patch_guest_link(
    request: Request,
    resource_type: GuestResourcePath,
    resource_id: str,
    req: GuestLinkPatchRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    data = await patch_guest_link_settings(login_user, resource_type, resource_id, req)
    audit = data.pop("_audit", None)
    if audit:
        await write_guest_link_audit(
            login_user,
            ip_address=get_request_ip(request),
            resource_type=resource_type,
            audit=audit,
        )
    return resp_200(data=data)
