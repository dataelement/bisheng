"""Host-only Desktop credential exchange; the response contains an HttpOnly cookie value."""

from fastapi import APIRouter, Depends, Request

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.api.dependencies import DshRuntime, get_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.services.web_session import create_web_session

router = APIRouter(route_class=DshRoute)


@router.post("/dsh/web-session")
async def web_session(request: Request, runtime: DshRuntime = Depends(get_runtime)):
    if len(request.headers.getlist("authorization")) != 1:
        raise DshInvalidAccessTokenError()
    return await create_web_session(runtime, request.headers["authorization"])
