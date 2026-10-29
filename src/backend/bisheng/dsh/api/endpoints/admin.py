"""Browser administration endpoints; actors always come from platform JWT."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.dsh.api.dependencies import get_runtime
from bisheng.dsh.domain.schemas.audit import AuditAction, AuditStatus
from bisheng.dsh.domain.services.vision import VisionSetting

router = APIRouter(prefix="/dsh/admin")
admin_user = UserPayload.get_tenant_admin_user
UserId = Annotated[int, Path(gt=0, le=9223372036854775807)]
TenantId = Annotated[int | None, Query(gt=0, le=9223372036854775807)]
Limit = Annotated[int, Query(ge=1, le=100)]


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
