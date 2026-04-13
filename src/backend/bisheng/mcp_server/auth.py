import hashlib
import json
import os
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import jwt
from loguru import logger
from starlette.responses import JSONResponse

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.user.domain.services.auth import LoginUser
from bisheng.user.domain.services.auth import AuthJwt
from bisheng.utils import generate_uuid
from bisheng.utils.constants import USER_CURRENT_SESSION

_current_access_token: ContextVar[str | None] = ContextVar('mcp_access_token', default=None)
_current_login_user: ContextVar[UserPayload | None] = ContextVar('mcp_login_user', default=None)
_current_token_scopes: ContextVar[tuple[str, ...]] = ContextVar('mcp_token_scopes', default=tuple())

_MCP_BEARER_REALM = 'bisheng-mcp'
_LOCAL_ORIGIN_HOSTS = {'127.0.0.1', 'localhost'}
_MCP_AUDIENCE = 'bisheng-workflow-mcp'
_MCP_ISSUER = 'bisheng-mcp'
_MCP_TOKEN_TYPE = 'mcp_access_token'
_MCP_DEFAULT_SCOPES = ('workflow.read', 'workflow.write', 'workflow.publish')
_MCP_MAX_EXPIRES_IN = 60 * 60
_MCP_DEFAULT_EXPIRES_IN = 30 * 60
_MCP_ALLOWED_ORIGINS = tuple(
    one.strip() for one in os.getenv('BISHENG_MCP_ALLOWED_ORIGINS', '').split(',') if one.strip()
)


def get_current_access_token() -> str | None:
    return _current_access_token.get()


def get_current_login_user() -> UserPayload | None:
    return _current_login_user.get()


def get_current_token_scopes() -> tuple[str, ...]:
    return _current_token_scopes.get()


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
    if _MCP_ALLOWED_ORIGINS:
        return origin in _MCP_ALLOWED_ORIGINS
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


def get_request_bisheng_access_token(request) -> Optional[str]:
    token = _parse_bearer_token(request.headers.get('authorization', ''))
    if token:
        return token
    return request.cookies.get('access_token_cookie')


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def hash_bisheng_session_token(token: str) -> str:
    return _hash_session_token(token)


def _normalize_scopes(scopes: Optional[list[str] | tuple[str, ...]]) -> tuple[str, ...]:
    if not scopes:
        return _MCP_DEFAULT_SCOPES
    normalized = []
    for scope in scopes:
        if scope in _MCP_DEFAULT_SCOPES and scope not in normalized:
            normalized.append(scope)
    return tuple(normalized or _MCP_DEFAULT_SCOPES)


def normalize_mcp_scopes(scopes: Optional[list[str] | tuple[str, ...] | str]) -> tuple[str, ...]:
    if isinstance(scopes, str):
        scopes = [scope.strip() for scope in scopes.replace(',', ' ').split() if scope.strip()]
    return _normalize_scopes(scopes)


async def _assert_parent_session_valid(user_id: int, parent_session_hash: str):
    redis_client = await get_redis_client()
    current_session = await redis_client.aget(USER_CURRENT_SESSION.format(user_id))
    if not current_session:
        raise JWTDecodeError(status_code=401, message='Bisheng session expired')
    if _hash_session_token(current_session) != parent_session_hash:
        raise JWTDecodeError(status_code=401, message='Bisheng session has been replaced')


async def resolve_login_user_from_bisheng_access_token(token: str) -> UserPayload:
    subject = AuthJwt().decode_jwt_token(token)
    await _assert_parent_session_valid(subject['user_id'], _hash_session_token(token))
    return await UserPayload.init_login_user(
        user_id=subject['user_id'],
        user_name=subject['user_name'],
    )


def _create_mcp_access_token_from_session_hash(login_user: LoginUser,
                                               parent_session_hash: str,
                                               *,
                                               scopes: Optional[list[str] | tuple[str, ...]] = None,
                                               expires_in: int = _MCP_DEFAULT_EXPIRES_IN) -> tuple[str, dict]:
    now = int(datetime.now(timezone.utc).timestamp())
    expires_in = max(60, min(int(expires_in), _MCP_MAX_EXPIRES_IN))
    normalized_scopes = list(_normalize_scopes(scopes))
    claims = {
        'sub': str(login_user.user_id),
        'user_id': login_user.user_id,
        'user_name': login_user.user_name,
        'iss': _MCP_ISSUER,
        'aud': _MCP_AUDIENCE,
        'iat': now,
        'exp': now + expires_in,
        'jti': generate_uuid(),
        'token_type': _MCP_TOKEN_TYPE,
        'scope': normalized_scopes,
        'parent_session_hash': parent_session_hash,
    }
    token = jwt.encode(claims, AuthJwt().jwt_secret, algorithm='HS256')
    return token, {
        'access_token': token,
        'token_type': 'Bearer',
        'expires_in': expires_in,
        'scopes': normalized_scopes,
        'audience': _MCP_AUDIENCE,
    }


def create_mcp_access_token(login_user: LoginUser,
                            parent_access_token: str,
                            *,
                            scopes: Optional[list[str] | tuple[str, ...]] = None,
                            expires_in: int = _MCP_DEFAULT_EXPIRES_IN) -> tuple[str, dict]:
    return _create_mcp_access_token_from_session_hash(
        login_user,
        _hash_session_token(parent_access_token),
        scopes=scopes,
        expires_in=expires_in,
    )


def create_mcp_access_token_from_session_hash(login_user: LoginUser,
                                              parent_session_hash: str,
                                              *,
                                              scopes: Optional[list[str] | tuple[str, ...]] = None,
                                              expires_in: int = _MCP_DEFAULT_EXPIRES_IN) -> tuple[str, dict]:
    return _create_mcp_access_token_from_session_hash(
        login_user,
        parent_session_hash,
        scopes=scopes,
        expires_in=expires_in,
    )


async def _validate_mcp_access_token(token: str) -> tuple[UserPayload, tuple[str, ...]]:
    try:
        payload = jwt.decode(
            token,
            AuthJwt().jwt_secret,
            audience=_MCP_AUDIENCE,
            issuer=_MCP_ISSUER,
            algorithms=['HS256'],
        )
    except Exception as exc:
        raise JWTDecodeError(status_code=401, message=str(exc))

    if payload.get('token_type') != _MCP_TOKEN_TYPE:
        raise JWTDecodeError(status_code=401, message='Unsupported MCP token type')

    user_id = payload.get('user_id')
    user_name = payload.get('user_name')
    if not user_id or not user_name:
        try:
            subject = json.loads(payload.get('sub') or '{}')
        except Exception as exc:
            raise JWTDecodeError(status_code=401, message=f'Invalid MCP token subject: {exc}')
        if not isinstance(subject, dict):
            raise JWTDecodeError(status_code=401, message='Invalid MCP token subject')
        user_id = user_id or subject.get('user_id')
        user_name = user_name or subject.get('user_name')
    parent_session_hash = payload.get('parent_session_hash')
    if not user_id or not user_name or not parent_session_hash:
        raise JWTDecodeError(status_code=401, message='MCP token payload is incomplete')

    await _assert_parent_session_valid(user_id, parent_session_hash)
    login_user = await UserPayload.init_login_user(user_id=user_id, user_name=user_name)
    return login_user, tuple(_normalize_scopes(payload.get('scope')))


def require_mcp_scopes(*required_scopes: str):
    current_scopes = set(get_current_token_scopes())
    missing_scopes = [scope for scope in required_scopes if scope not in current_scopes]
    if missing_scopes:
        raise UnAuthorizedError(msg=f'MCP token missing required scopes: {", ".join(missing_scopes)}')


class McpAuthorizationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token_ref: Token | None = None
        user_ref: Token | None = None
        scope_ref: Token | None = None
        scope_type = scope.get('type')
        if scope_type not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return

        headers = _get_headers(scope)
        method = scope.get('method', '').upper()
        origin = headers.get('origin')
        host = headers.get('host', '')

        if scope_type == 'http' and method == 'OPTIONS':
            await self.app(scope, receive, send)
            return

        if origin and not _is_allowed_origin(origin, host):
            if scope_type == 'http':
                await _error_response(
                    403,
                    'Origin is not allowed for Bisheng MCP',
                    error='forbidden_origin',
                )(scope, receive, send)
            else:
                await send({
                    'type': 'websocket.close',
                    'code': 4403,
                    'reason': 'Origin is not allowed for Bisheng MCP',
                })
            return

        bearer_token = _parse_bearer_token(headers.get('authorization', ''))
        if not bearer_token:
            if scope_type == 'http':
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
            else:
                await send({
                    'type': 'websocket.close',
                    'code': 4401,
                    'reason': 'Missing Bearer token',
                })
            return

        try:
            login_user, token_scopes = await _validate_mcp_access_token(bearer_token)
        except JWTDecodeError as exc:
            if scope_type == 'http':
                await _error_response(
                    401,
                    exc.message,
                    error='invalid_token',
                    extra_headers={
                        'WWW-Authenticate': _auth_header('invalid_token', exc.message)
                    },
                )(scope, receive, send)
            else:
                await send({
                    'type': 'websocket.close',
                    'code': 4401,
                    'reason': exc.message[:120],
                })
            return

        token_ref = _current_access_token.set(bearer_token)
        user_ref = _current_login_user.set(login_user)
        scope_ref = _current_token_scopes.set(token_scopes)
        try:
            await self.app(scope, receive, send)
        except Exception:
            logger.exception('Unhandled exception in MCP authorization middleware')
            raise
        finally:
            if scope_ref is not None:
                _current_token_scopes.reset(scope_ref)
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
    login_user, _ = await _validate_mcp_access_token(token)
    return login_user
