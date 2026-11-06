"""Recheck a persisted desktop session reference before queued runtime effects."""

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.dsh.access_runtime import build_runtime, get_settings
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope
from bisheng.dsh.domain.services.settings import DshSettingsService


async def resolve_desktop_runtime_identity(reference):
    try:
        if reference["kind"] != "dsh_session":
            raise ValueError("unsupported reference")
        principal = DshPrincipal.model_validate(reference["principal"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PermissionDeniedError(reason="runtime_desktop_identity_invalid") from exc
    config = get_settings()
    if not config.enabled:
        raise PermissionDeniedError(reason="runtime_desktop_disabled")
    await DshSettingsService().require_enabled()
    runtime = await build_runtime(config)
    try:
        with principal_scope(principal):
            await runtime.sessions.validate(principal)
            identity = await runtime.identity.check(principal.tenant_id, principal.user_id)
            if not identity.active:
                raise DshUserDisabledError()
            return await UserPayload.init_login_user(
                user_id=int(principal.user_id),
                user_name=identity.user.username,
                tenant_id=int(principal.tenant_id),
            )
    finally:
        await runtime.close()
