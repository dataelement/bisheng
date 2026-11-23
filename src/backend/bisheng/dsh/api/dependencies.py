"""HTTP dependency exports for the shared DSH application runtime."""

from fastapi import Depends, Request

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.core.session_activity import record_authenticated_activity
from bisheng.dsh.access_runtime import DshRuntime, get_runtime, get_settings
from bisheng.dsh.application.session_activity import DshSessionActivity
from bisheng.dsh.domain.services.access import DshPrincipal


async def desktop_principal(request: Request, runtime: DshRuntime = Depends(get_runtime)) -> DshPrincipal:
    if len(request.headers.getlist("authorization")) != 1:
        raise DshInvalidAccessTokenError()
    principal = await runtime.access.authenticate(request.headers["authorization"])
    request.state.authenticated_activity = DshSessionActivity(runtime.sessions, principal)
    await record_authenticated_activity(request)
    return principal


__all__ = ["DshRuntime", "desktop_principal", "get_runtime", "get_settings"]
