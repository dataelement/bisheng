"""Narrow proofs for gateway-owned controls, never resource reassignment."""

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.department.application.business_scope import resolve_verified_department_scope
from bisheng.permission.application.business_authorization import require_business_action


async def authorize_gateway_targets(user, *, department_id=None, resources=()):
    target = get_current_tenant_id()
    if department_id is not None:
        facts = await resolve_verified_department_scope(department_id, user)
        if facts.business_tenant_id != target:
            raise PermissionInvalidResourceError()
    for resource in resources:
        await require_business_action(user, resource_type=resource.kind, resource_id=resource.id, action="edit")
    return {"tenant_id": target, "user_id": user.user_id}
