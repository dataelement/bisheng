"""Narrow preview capability provider; callers receive immutable references only."""

from bisheng.app_publish.application.preview_runtime import by_reference
from bisheng.app_publish.domain.services.preview_access_service import (
    CapabilityAccessContext,
    qualified_scope,
    qualify,
    validate_binding,
)
from bisheng.core.context.tenant import bypass_tenant_filter


async def resolve_preview_context(
    *, credential_id=None, session_id=None, operation_id=None, viewer_user_id=None, allow_starting=False
):
    with bypass_tenant_filter():
        row = await by_reference(credential_id=credential_id, session_id=session_id, operation_id=operation_id)
    if row is None:
        return None
    return await validate_binding(
        row, credential_id=credential_id, viewer_user_id=viewer_user_id, allow_starting=allow_starting
    )


__all__ = ["CapabilityAccessContext", "qualified_scope", "qualify", "resolve_preview_context"]


class PreviewCapabilityProvider:
    async def resolve(self, **reference):
        return await resolve_preview_context(**reference)


async def preview_material(session_id):
    from types import SimpleNamespace

    with bypass_tenant_filter():
        row = await by_reference(session_id=session_id)
    if row is None:
        return None
    context = await validate_binding(row, allow_starting=True)
    return SimpleNamespace(
        id=context.session_id,
        tenant_id=context.tenant_id,
        app_id=context.app_id,
        version_id=context.version_id,
        operation_id=context.operation_id,
        status=row.status,
        approver_user_id=context.viewer_user_id,
        expires_at=row.expires_at,
        approval_active=True,
    )
