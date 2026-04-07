from contextvars import ContextVar, Token
from typing import Optional
from urllib.parse import urlparse

from loguru import logger
from starlette.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.user.domain.services.auth import AuthJwt

_current_access_token: ContextVar[str | None] = ContextVar('mcp_access_token', default=None)
_current_login_user: ContextVar[UserPayload | None] = ContextVar('mcp_login_user', default=None)

_MCP_BEARER_REALM = 'bisheng-mcp'
_LOCAL_ORIGIN_HOSTS = {'127.0.0.1', 'localhost'}


def get_current_access_token() -> str | None:
    return _current_access_token.get()


def get_current_login_user() -> UserPayload | None:
    return _current_login_user.get()


def _get_headers(scope) -> dict[str, str]:
    headers = {}
    for key, value in scope.get('headers', []):
        headers[key.decode('latin1').lower()] = value.decode('latin1')
    return headers


def _parse_bearer_token(auth_header: str) -> Optional[str]:
    if not auth_header:
        return None
    auth_header = auth_header.strip()
    if not auth_header.lower().startswith('bearer '):
        return None
    token = auth_header.split(' ', 1)[1].strip()
    return token or None


def _extract_hostname(value: str) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value if '://' in value else f'//{value}')
    return parsed.hostname.lower() if parsed.hostname else None


def _is_allowed_origin(origin: str, host: str) -> bool:
    if not origin:
        return True
    origin_host = _extract_hostname(origin)
    host_name = _extract_hostname(host)
    if not origin_host or not host_name:
        return False
    if origin_host == host_name:
        return True
    if origin_host in _LOCAL_ORIGIN_HOSTS and host_name in _LOCAL_ORIGIN_HOSTS:
        return True
    return False


def _auth_header(error: str, description: str) -> str:
    description = description.replace('"', "'")
    return (
        f'Bearer realm="{_MCP_BEARER_REALM}", '
        f'error="{error}", '
        f'error_description="{description}"'
    )


def _error_response(status_code: int,
                    message: str,
                    *,
                    error: str,
                    extra_headers: Optional[dict[str, str]] = None) -> JSONResponse:
    headers = {'Cache-Control': 'no-store'}
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            'ok': False,
            'error': error,
            'message': message,
        },
    )


async def _resolve_login_user_from_token(token: str) -> UserPayload:
    subject = AuthJwt().decode_jwt_token(token)
    return await UserPayload.init_login_user(
        user_id=subject['user_id'],
        user_name=subject['user_name'],
    )


class McpAuthorizationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token_ref: Token | None = None
        user_ref: Token | None = None
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        headers = _get_headers(scope)
        method = scope.get('method', '').upper()
        origin = headers.get('origin')
        host = headers.get('host', '')

        if method == 'OPTIONS':
            await self.app(scope, receive, send)
            return

        if origin and not _is_allowed_origin(origin, host):
            await _error_response(
                403,
                'Origin is not allowed for Bisheng MCP',
                error='forbidden_origin',
            )(scope, receive, send)
            return

        bearer_token = _parse_bearer_token(headers.get('authorization', ''))
        if not bearer_token:
            await _error_response(
                401,
                'Missing Bisheng bearer token for MCP request',
                error='invalid_request',
                extra_headers={
                    'WWW-Authenticate': _auth_header(
                        'invalid_request',
                        'Missing Bearer token',
                    )
                },
            )(scope, receive, send)
            return

        try:
            login_user = await _resolve_login_user_from_token(bearer_token)
        except JWTDecodeError as exc:
            await _error_response(
                401,
                exc.message,
                error='invalid_token',
                extra_headers={
                    'WWW-Authenticate': _auth_header('invalid_token', exc.message)
                },
            )(scope, receive, send)
            return

        token_ref = _current_access_token.set(bearer_token)
        user_ref = _current_login_user.set(login_user)
        try:
            await self.app(scope, receive, send)
        except Exception:
            logger.exception('Unhandled exception in MCP authorization middleware')
            raise
        finally:
            if user_ref is not None:
                _current_login_user.reset(user_ref)
            if token_ref is not None:
                _current_access_token.reset(token_ref)


async def get_login_user_from_mcp_token() -> UserPayload:
    login_user = get_current_login_user()
    if login_user is not None:
        return login_user
    token = get_current_access_token()
    if not token:
        raise UnAuthorizedError(msg='Missing Bisheng bearer token for MCP request')
    return await _resolve_login_user_from_token(token)
