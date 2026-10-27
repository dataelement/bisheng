"""Current natural-person administrator authorization; no log-menu shortcut."""

from bisheng.admin.application.tenant_scope import current_admin_scope
from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.application import is_tenant_admin


async def resolve_scope(user, tenant_id=None):
    if not isinstance(user, UserPayload):
        raise RuntimeAuditAccessDeniedError()
    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository

    account = await RuntimeAuditRepository().current_user(user.user_id)
    if account is None or account.token_version != user.token_version:
        raise RuntimeAuditAccessDeniedError()
    fresh = await UserPayload.init_login_user(
        user_id=user.user_id, user_name=user.user_name, tenant_id=user.tenant_id, token_version=user.token_version
    )
    effective = get_current_tenant_id()
    admin_scope = await current_admin_scope(user.user_id) if fresh.is_global_super else None
    if admin_scope is not None:
        effective = admin_scope
    owner = effective or user.tenant_id
    if fresh.is_global_super and admin_scope is None:
        if tenant_id is not None and tenant_id <= 0:
            raise RuntimeAuditAccessDeniedError()
        return AuthorizedRuntimeAuditScope(user.user_id, owner, tenant_id)
    if effective is None or (tenant_id is not None and tenant_id != effective):
        raise RuntimeAuditAccessDeniedError()
    if not fresh.is_global_super and not await is_tenant_admin(user.user_id, effective):
        raise RuntimeAuditAccessDeniedError()
    return AuthorizedRuntimeAuditScope(user.user_id, owner, effective)
