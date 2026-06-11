from collections.abc import AsyncGenerator

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.utils import get_request_ip


def _get_developer_token_endpoint_key(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None) or request.scope.get("path") or request.url.path
    return f"{request.method.upper()} {route_path}"


async def get_developer_token_user(request: Request) -> AsyncGenerator[UserPayload, None]:
    user = await DeveloperTokenService.authenticate(
        request.headers.get("X-Developer-Token"),
        request_ip=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        endpoint_key=_get_developer_token_endpoint_key(request),
    )
    try:
        yield user
    finally:
        DeveloperTokenService.reset_auth_context(user)
