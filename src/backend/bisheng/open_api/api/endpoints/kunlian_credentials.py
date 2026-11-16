"""本地平台超管管理昆联集成 Key。业务 Key 不可调用自身控制面。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.open_api.api.kunlian_dependencies import KunlianApiRoute
from bisheng.open_api.domain.services.kunlian_credential import KunlianCredentialService

router = APIRouter(prefix="/identity-integrations/kunlian/api-keys", route_class=KunlianApiRoute)


async def get_kunlian_key_admin(user: UserPayload = Depends(UserPayload.get_login_user), request: Request = None):
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.user.application.external_identity import (
        KunlianExternalIdentityApplication,
        UserExternalIdentityProjectionRepository,
    )

    owner = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository())
    with tenant_execution_scope(1):
        await owner.require_current_global_super(user.user_id)
    if request is not None:
        from bisheng.open_api.application.kunlian_audit import KunlianAuditService

        audit = getattr(request.app.state, "kunlian_audit_service", None) or KunlianAuditService()
        route = request.scope.get("route")
        audit_id = await audit.begin_control(
            user,
            request.method,
            route.path,
            request.path_params.get("key_id"),
            getattr(request.state, "trace_id", None),
        )
        request.state.kunlian_audit_service = audit
        request.state.kunlian_audit_id = audit_id
    return user


class KeyIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=128)
    integration_id: str = Field(min_length=1, max_length=128)
    tenant_ids: list[str] = Field(min_length=1, max_length=1000)
    capabilities: list[str] = Field(min_length=1, max_length=5)
    expires_at: datetime | None = None


class KeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)
    capabilities: list[str] | None = Field(default=None, min_length=1, max_length=5)
    expires_at: datetime | None = None


@router.post("", status_code=201)
async def issue(body: KeyIssue, user=Depends(get_kunlian_key_admin)):
    return resp_200(
        await KunlianCredentialService().issue(is_global_super=True, created_by=user.user_id, **body.model_dump())
    )


@router.get("")
async def list_keys(
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100), user=Depends(get_kunlian_key_admin)
):
    return resp_200(await KunlianCredentialService().list(is_global_super=True, offset=offset, limit=limit))


@router.patch("/{key_id}")
async def update(key_id: int, body: KeyUpdate, user=Depends(get_kunlian_key_admin)):
    return resp_200(
        await KunlianCredentialService().update(key_id, is_global_super=True, **body.model_dump(exclude_unset=True))
    )


@router.post("/{key_id}/revoke")
async def revoke(key_id: int, user=Depends(get_kunlian_key_admin)):
    return resp_200(await KunlianCredentialService().revoke(key_id, is_global_super=True))


@router.post("/{key_id}/rotate", status_code=201)
async def rotate(key_id: int, user=Depends(get_kunlian_key_admin)):
    return resp_200(await KunlianCredentialService().rotate(key_id, is_global_super=True, created_by=user.user_id))


@router.get("/{key_id}")
async def detail(key_id: int, user=Depends(get_kunlian_key_admin)):
    return resp_200(await KunlianCredentialService().detail(key_id, is_global_super=True))
