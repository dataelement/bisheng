"""Browser administration endpoints; actors always come from platform JWT."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.domain.schemas.admin import SubjectPolicyInput
from bisheng.dsh.domain.schemas.audit import AuditAction, AuditStatus
from bisheng.dsh.domain.schemas.contracts import DshContract, DshUserPolicyInput
from bisheng.dsh.domain.services.vision import VisionSetting

router = APIRouter(prefix="/dsh/admin")
admin_user = UserPayload.get_tenant_admin_user
UserId = Annotated[int, Path(gt=0, le=9223372036854775807)]
TenantId = Annotated[int | None, Query(gt=0, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=100)]
SubjectType = Literal["DEPARTMENT", "ROLE"]


class SeatCommand(DshContract):
    operation_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    expected_grant_version: int = Field(strict=True, ge=1, le=9223372036854775807)


async def get_management(runtime=Depends(get_runtime)):
    from bisheng.dsh.admin_runtime import get_admin_runtime

    return (await get_admin_runtime(runtime)).admin


@router.get("/models/{model_id}/vision")
async def model_vision(model_id: UserId, user=Depends(admin_user), service=Depends(get_management)):
    return resp_200(data=await service.model_vision(user.user_id, model_id))


@router.put("/models/{model_id}/vision")
async def update_model_vision(
    model_id: UserId, setting: VisionSetting, user=Depends(admin_user), service=Depends(get_management)
):
    return resp_200(data=await service.model_vision(user.user_id, model_id, setting))


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


@router.get("/models/{model_id}/users")
async def model_users(
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    limit: Limit = 20,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    authorized_only: bool = False,
):
    return resp_200(
        data=await service.model_users(
            user.user_id,
            model_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
            keyword=keyword,
            authorized_only=authorized_only,
        )
    )


@router.get("/models/{model_id}/user-permissions")
async def model_user_permissions(
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    limit: Limit = 20,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    department_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    membership: Literal["DIRECT", "EFFECTIVE"] = "EFFECTIVE",
    unassigned_only: bool = False,
    include_seats: bool = False,
):
    return resp_200(
        data=await service.model_user_permissions(
            user.user_id,
            model_id,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
            keyword=keyword,
            department_id=department_id,
            membership=membership,
            unassigned_only=unassigned_only,
            include_seats=include_seats,
        )
    )


@router.get("/models/{model_id}/subjects")
async def model_subjects(
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(data=await service.model_subjects(user.user_id, model_id, tenant_id=tenant_id))


@router.put("/models/{model_id}/subjects/{subject_type}/{subject_id}/policy")
async def update_subject_policy(
    model_id: UserId,
    subject_type: SubjectType,
    subject_id: UserId,
    body: SubjectPolicyInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(
        data=await service.update_subject_policy(
            user.user_id,
            model_id,
            subject_type,
            subject_id,
            body,
            tenant_id=tenant_id,
        )
    )


@router.get("/users/{user_id}/models/{model_id}/policy")
async def model_policy(
    user_id: UserId,
    model_id: UserId,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(data=await service.get_model_policy(user.user_id, user_id, model_id, tenant_id=tenant_id))


@router.put("/users/{user_id}/models/{model_id}/policy")
async def update_policy(
    user_id: UserId,
    model_id: UserId,
    body: DshUserPolicyInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    return resp_200(
        data=await service.update_policy(user.user_id, user_id, body, model_id=model_id, tenant_id=tenant_id)
    )


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


@router.get("/audit-records")
async def audit_records(
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Limit = 20,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
):
    return resp_200(
        data=await service.audit_records(
            user.user_id, tenant_id=tenant_id, cursor=cursor, limit=limit, action=action, status=status
        )
    )


@router.get("/users/{user_id}/policy")
async def policy(
    user_id: UserId, user=Depends(admin_user), service=Depends(get_management), tenant_id: TenantId = None
):
    return resp_200(data=await service.get_policy(user.user_id, user_id, tenant_id=tenant_id))


@router.get("/users/{user_id}/usage-summary")
async def usage_summary(
    user_id: UserId,
    start_at: Annotated[datetime, Query()],
    end_at: Annotated[datetime, Query()],
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    granularity: Literal["hour", "day"] | None = None,
):
    return resp_200(
        data=await service.usage_summary(
            user.user_id,
            user_id,
            start_at=start_at,
            end_at=end_at,
            tenant_id=tenant_id,
            granularity=granularity,
        )
    )


@router.get("/usage-overview")
async def usage_overview(
    start_at: Annotated[datetime, Query()],
    end_at: Annotated[datetime, Query()],
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
    cursor: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    limit: Limit = 20,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
    department_id: Annotated[int | None, Query(gt=0, le=9223372036854775807)] = None,
    include_summary: Annotated[bool, Query()] = False,
    granularity: Literal["hour", "day"] | None = None,
):
    return resp_200(
        data=await service.usage_overview(
            user.user_id,
            start_at=start_at,
            end_at=end_at,
            tenant_id=tenant_id,
            cursor=cursor,
            limit=limit,
            keyword=keyword,
            department_id=department_id,
            include_summary=include_summary,
            granularity=granularity,
        )
    )


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
