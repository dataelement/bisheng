from contextvars import ContextVar, Token

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.user.domain.services.auth import AuthJwt

_current_access_token: ContextVar[str | None] = ContextVar('mcp_access_token', default=None)


def get_current_access_token() -> str | None:
    return _current_access_token.get()


class McpAuthorizationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token_ref: Token | None = None
        if scope.get('type') == 'http':
            headers = {}
            for key, value in scope.get('headers', []):
                headers[key.decode('latin1').lower()] = value.decode('latin1')
            auth_header = headers.get('authorization', '')
            bearer_token = None
            if auth_header.lower().startswith('bearer '):
                bearer_token = auth_header.split(' ', 1)[1].strip()
            token_ref = _current_access_token.set(bearer_token)
        try:
            await self.app(scope, receive, send)
        finally:
            if token_ref is not None:
                _current_access_token.reset(token_ref)


async def get_login_user_from_mcp_token() -> UserPayload:
    token = get_current_access_token()
    if not token:
        raise UnAuthorizedError(msg='Missing Bisheng bearer token for MCP request')
    subject = AuthJwt().decode_jwt_token(token)
    return await UserPayload.init_login_user(
        user_id=subject['user_id'],
        user_name=subject['user_name'],
    )
