"""HTTP dependency exports for the shared DSH application runtime."""

import asyncio

from fastapi import Depends, Request

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.access_runtime import DshRuntime, get_runtime, get_settings
from bisheng.dsh.domain.services.access import DshPrincipal


async def desktop_principal(request: Request, runtime: DshRuntime = Depends(get_runtime)) -> DshPrincipal:
    if len(request.headers.getlist("authorization")) != 1:
        raise DshInvalidAccessTokenError()
    principal = await runtime.access.authenticate(request.headers["authorization"])
    request.state.dsh_verified_at = asyncio.get_running_loop().time()
    return principal


__all__ = ["DshRuntime", "desktop_principal", "get_runtime", "get_settings"]
