"""Admin HTTP endpoints for unified secondary-tool pricing."""

from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_sync_db_session
from bisheng.dsh.api.endpoints.admin import get_management
from bisheng.dsh.domain.schemas.tool_pricing import ToolPricingInput
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.tool_pricing import list_tenant_tool_pricing, save_tenant_tool_pricing

router = APIRouter(prefix="/dsh")
admin_user = UserPayload.get_tenant_admin_user
ToolId = Annotated[int, Path(gt=0, le=9_223_372_036_854_775_807)]
TenantId = Annotated[int | None, Query(gt=0, le=9_223_372_036_854_775_807)]


@contextmanager
def _sync_session_scope():
    with get_sync_db_session() as session, session.begin():
        yield session


@router.get("/admin/tool-pricing")
async def list_tool_pricing(
    user=Depends(UserPayload.get_login_user),
    tenant_id: TenantId = None,
):
    target_tenant = tenant_id or get_current_tenant_id() or user.tenant_id
    if tenant_id is not None and tenant_id != user.tenant_id:
        from bisheng.dsh.admin_runtime import authorize_admin

        _, target_tenant = await authorize_admin(user.user_id, tenant_id)
    with profile_scope(int(target_tenant)), _sync_session_scope() as session:
        return resp_200(data=list_tenant_tool_pricing(session))


@router.put("/admin/tool-pricing/{tool_id}")
async def save_tool_pricing(
    tool_id: ToolId,
    body: ToolPricingInput,
    user=Depends(admin_user),
    service=Depends(get_management),
    tenant_id: TenantId = None,
):
    _, tenant = await service.authorize(user.user_id, tenant_id or get_current_tenant_id())
    with profile_scope(tenant), _sync_session_scope() as session:
        return resp_200(data=save_tenant_tool_pricing(session, tool_id=tool_id, actor=user.user_id, value=body))
