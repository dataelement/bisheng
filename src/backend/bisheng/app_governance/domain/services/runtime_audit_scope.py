"""Current audit-entry qualification plus application edit and one tenant."""

from bisheng.admin.application.tenant_scope import resolve_management_scope
from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
from bisheng.app_runtime.application.authorization import authorize_app, editable_app_ids
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.application import is_tenant_admin


async def resolve_scope(user, tenant_id=None, *, app_id=None):
    if not isinstance(user, UserPayload):
        raise RuntimeAuditAccessDeniedError()
    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository

    account = await RuntimeAuditRepository().current_user(user.user_id)
    if account is None or account.token_version != user.token_version:
        raise RuntimeAuditAccessDeniedError()
    own = await resolve_management_scope(user.user_id, is_super=False)
    fresh = await UserPayload.init_login_user(
        user_id=user.user_id, user_name=user.user_name, tenant_id=own.tenant_id, token_version=user.token_version
    )
    effective = get_current_tenant_id() or own.tenant_id
    if type(effective) is not int or effective <= 0 or (tenant_id is not None and tenant_id != effective):
        raise RuntimeAuditAccessDeniedError()
    if not fresh.is_global_super and effective != own.tenant_id:
        raise RuntimeAuditAccessDeniedError()
    if app_id:
        await authorize_app(fresh, app_id, "audit_read")
        apps = (app_id,)
    else:
        if not fresh.is_global_super and not await is_tenant_admin(fresh.user_id, effective):
            await UserPayload.assert_effective_web_menu_contains(fresh.user_id, "log")
        apps = await editable_app_ids(fresh, effective)
    return AuthorizedRuntimeAuditScope(user.user_id, effective, effective, tuple(apps))
