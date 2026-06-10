from collections.abc import AsyncGenerator

from fastapi import Request

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.developer_token.domain.services import DeveloperTokenService
from bisheng.utils import get_request_ip


async def get_developer_token_user(request: Request) -> AsyncGenerator[UserPayload, None]:
    user = await DeveloperTokenService.authenticate(
        request.headers.get("X-Developer-Token"),
        request_ip=get_request_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    try:
        yield user
    finally:
        DeveloperTokenService.reset_auth_context(user)
