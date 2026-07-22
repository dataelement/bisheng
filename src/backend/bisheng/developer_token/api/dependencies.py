from collections.abc import AsyncGenerator

from fastapi import Depends, Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.utils import get_request_ip


def _get_developer_token_endpoint_key(request: Request) -> str:
    method, route_path = _get_developer_token_route(request)
    endpoint_path = route_path or request.scope.get("path") or request.url.path
    return f"{method} {endpoint_path}"


def _get_developer_token_route(request: Request) -> tuple[str, str | None]:
    route = request.scope.get("route")
    return request.method.upper(), getattr(route, "path", None)


async def get_developer_token_principal(
    request: Request,
) -> AsyncGenerator[DeveloperTokenPrincipal, None]:
    principal = await DeveloperTokenService.authenticate_principal(
        request.headers.get("X-Developer-Token"),
        request_ip=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        endpoint_key=_get_developer_token_endpoint_key(request),
        request_method=request.method.upper(),
        route_path=_get_developer_token_route(request)[1],
    )
    try:
        yield principal
    finally:
        DeveloperTokenService.reset_auth_context(principal.user)


async def get_developer_token_user(
    principal: DeveloperTokenPrincipal = Depends(get_developer_token_principal),
) -> UserPayload:
    return principal.user
