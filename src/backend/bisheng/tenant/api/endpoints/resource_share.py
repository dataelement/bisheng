"""F017 resource share toggle endpoint.

Route exposed (mounted under the tenant module router, router owns full path):

  PATCH /api/v1/resources/{resource_type}/{resource_id}/share

Handler is intentionally thin:

  1. Auth gate: only the global super admin may flip a resource's sharing
     state (spec AC-01 / PRD §7.2). Child admins and ordinary users → 403.
  2. Structural gate: ``resource_type`` must be one of the 5 shareable types
     registered in ``ResourceShareService.SUPPORTED_SHAREABLE_TYPES``; else
     ``ResourceTypeNotShareableError`` (19502).
  3. Tenant gate: the resource must belong to Root Tenant (1); sharing from
     a Child is not supported (``RootOnlyShareError``, 19501).
  4. FGA fan-out: toggle ``shared_with → tenant:{child}`` tuples for every
     active Child.
  5. DB flip: update the resource's ``is_shared`` column so list queries /
     UI badge rendering can skip an FGA read.
  6. audit_log: ``resource.share_enable`` / ``resource.share_disable`` with
     metadata.shared_children = the Child ids that were actually
     written/revoked (spec §5.4.2).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.tenant_sharing import (
    ResourceTypeNotShareableError,
    RootOnlyShareError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.services.resource_share_service import (
    SUPPORTED_SHAREABLE_TYPES,
    ResourceShareService,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ResourceShareReq(BaseModel):
    share_to_children: bool = Field(..., description='True → enable share; False → revoke')


def _errcode_to_response(exc: BaseErrorCode) -> JSONResponse:
    resp = exc.return_resp_instance()
    http_status = 403 if isinstance(exc, (RootOnlyShareError,)) else 400
    return JSONResponse(status_code=http_status, content=resp.model_dump())


async def _resolve_resource_tenant_id(resource_type: str, resource_id: str) -> Optional[int]:
    """Look up ``{resource}.tenant_id`` across the 5 supported types.

    Uses a raw SQL lookup because the base ORM models for these resources
    do NOT declare the ``tenant_id`` field — F001 added it at DB schema
    level and the ORM auto-filter injects it implicitly, but
    ``getattr(orm_row, 'tenant_id')`` returns None for non-declared
    columns. Raw SQL sidesteps that. We wrap in ``bypass_tenant_filter``
    so a global super admin toggling a Root resource from a Child-scope
    session still reaches it.
    """
    from sqlalchemy import text as sa_text

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session

    # Map api-level resource_type → (table_name, id_column, id_cast).
    _type_to_table = {
        'knowledge_space': ('knowledge', 'id', int),
        'workflow': ('flow', 'id', str),
        'assistant': ('assistant', 'id', str),
        'channel': ('channel', 'id', str),
        'tool': ('t_gpts_tools_type', 'id', int),
    }
    entry = _type_to_table.get(resource_type)
    if entry is None:
        return None
    table, id_col, cast = entry

    try:
        typed_id = cast(resource_id)
    except (TypeError, ValueError):
        return None

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            result = await session.exec(sa_text(
                f'SELECT tenant_id FROM {table} WHERE {id_col} = :rid LIMIT 1'
            ).bindparams(rid=typed_id))
            row = result.first()
    if row is None:
        return None
    # SQLAlchemy Row supports index access; plain tuples also do.
    value = row[0]
    return int(value) if value is not None else None


@router.patch('/resources/{resource_type}/{resource_id}/share')
async def toggle_resource_share(
    resource_type: str,
    resource_id: str,
    req: ResourceShareReq,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Toggle F017 sharing for a Root resource. See module docstring."""
    # 1. Auth: global super admin only
    is_super = False
    try:
        is_super = login_user.is_admin()
    except Exception:  # pragma: no cover - defensive
        is_super = False
    if not is_super:
        return _errcode_to_response(UnAuthorizedError())

    # 2. Resource type
    if resource_type not in SUPPORTED_SHAREABLE_TYPES:
        return _errcode_to_response(ResourceTypeNotShareableError())

    # 3. Tenant gate: must be Root-owned
    tenant_id = await _resolve_resource_tenant_id(resource_type, resource_id)
    if tenant_id is None or tenant_id != ROOT_TENANT_ID:
        return _errcode_to_response(RootOnlyShareError())

    # 4. FGA toggle
    if req.share_to_children:
        children = await ResourceShareService.enable_sharing(resource_type, resource_id)
        action = TenantAuditAction.RESOURCE_SHARE_ENABLE.value
    else:
        children = await ResourceShareService.disable_sharing(resource_type, resource_id)
        action = TenantAuditAction.RESOURCE_SHARE_DISABLE.value

    # 5. DB flag mirror (delegated to ResourceShareService.set_is_shared so
    #    the create-time path and this toggle path share one code path)
    try:
        await ResourceShareService.set_is_shared(
            resource_type, resource_id, req.share_to_children,
        )
    except Exception as e:  # pragma: no cover - DB hiccup, do not fail user-facing call
        logger.warning(
            '[F017] failed to update is_shared column for %s:%s: %s',
            resource_type, resource_id, e,
        )

    # 6. Audit log
    try:
        await AuditLogDao.ainsert_v2(
            tenant_id=ROOT_TENANT_ID,
            operator_id=login_user.user_id,
            operator_tenant_id=login_user.tenant_id,
            action=action,
            target_type=resource_type,
            target_id=str(resource_id),
            metadata={'shared_children': children, 'trigger': 'toggle'},
        )
    except Exception as e:  # pragma: no cover
        logger.warning(
            '[F017] audit_log %s failed for %s:%s: %s',
            action, resource_type, resource_id, e,
        )

    return resp_200(data={
        'is_shared': req.share_to_children,
        'shared_children': children,
    })
