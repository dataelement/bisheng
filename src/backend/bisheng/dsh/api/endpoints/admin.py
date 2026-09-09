"""Eight browser administration endpoints; actors always come from platform JWT."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.domain.schemas.contracts import DshContract, DshUserPolicyInput

router = APIRouter(prefix="/dsh/admin")
admin_user = UserPayload.get_tenant_admin_user
UserId = Annotated[int, Path(gt=0, le=9223372036854775807)]
TenantId = Annotated[int | None, Query(gt=0, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=100)]


class SeatCommand(DshContract):
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    expected_grant_version: int = Field(strict=True, ge=1, le=9223372036854775807)


async def get_management(runtime=Depends(get_runtime)):
    from bisheng.dsh.admin_runtime import get_admin_runtime

    return (await get_admin_runtime(runtime)).admin


@router.get("/users")
async def users(
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Limit = 50,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    seat_state: Literal["ASSIGNED", "REVOKED"] = "ASSIGNED",
    login_state: Literal["HAS_SESSIONS", "NO_SESSIONS"] | None = None,
):
    return resp_200(
        data=await service.users(
            user.user_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
            keyword=keyword,
            seat_state=seat_state,
            login_state=login_state,
        )
    )


@router.get("/license")
async def license(user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None):
    return resp_200(data=await service.license(user.user_id, tenant_id=tenant_id))


@router.put("/users/{user_id}/policy")
async def update_policy(
    user_id: UserId,
    body: DshUserPolicyInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(data=await service.update_policy(user.user_id, user_id, body, tenant_id=tenant_id))


@router.post("/users/{user_id}/revoke")
async def revoke(
    user_id: UserId,
    body: SeatCommand,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(
        data=await service.command(
            user.user_id, user_id, "REVOKE", body.operation_id, body.expected_grant_version, tenant_id=tenant_id
        )
    )


@router.post("/users/{user_id}/reassign")
async def reassign(
    user_id: UserId,
    body: SeatCommand,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(
        data=await service.command(
            user.user_id, user_id, "REASSIGN", body.operation_id, body.expected_grant_version, tenant_id=tenant_id
        )
    )


@router.get("/operations/{operation_id}")
async def operation(
    operation_id: str, user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None
):
    return resp_200(data=await service.operation(user.user_id, operation_id, tenant_id=tenant_id))


@router.get("/users/{user_id}/policy")
async def policy(
    user_id: UserId, user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None
):
    return resp_200(data=await service.get_policy(user.user_id, user_id, tenant_id=tenant_id))


@router.get("/users/{user_id}/sessions")
async def sessions(
    user_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Limit = 50,
):
    return resp_200(data=await service.sessions(user.user_id, user_id, tenant_id=tenant_id, cursor=cursor, limit=limit))
