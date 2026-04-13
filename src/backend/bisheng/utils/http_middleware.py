# Define a custom middleware class
import http.cookies
from time import time

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from bisheng.core.logger import trace_id_generator, trace_id_var
from bisheng.utils import get_request_ip

# Paths exempt from tenant context checks (login, env, health, docs, static)
TENANT_CHECK_EXEMPT_PATHS = (
    '/api/v1/user/login',
    '/api/v1/user/register',
    '/api/v1/user/sso',
    '/api/v1/user/ldap',
    '/api/v1/user/public_key',
    '/api/v1/user/switch-tenant',
    '/api/v1/user/tenants',
    '/api/v1/env',
    '/health',
    '/docs',
    '/openapi.json',
    '/redoc',
)


def _extract_tenant_id_from_token(token: str) -> int:
    """Decode JWT token and extract tenant_id. Returns DEFAULT_TENANT_ID on failure."""
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID
    try:
        from bisheng.user.domain.services.auth import AuthJwt
        auth = AuthJwt()
        subject = auth.decode_jwt_token(token)
        return subject.get('tenant_id', DEFAULT_TENANT_ID)
    except Exception:
        return DEFAULT_TENANT_ID


def _set_tenant_context(token: str = None) -> int:
    """Set tenant context from JWT cookie token. Returns extracted tenant_id.

    Shared by HTTP and WS middleware.
    """
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id
    try:
        if token:
            tid = _extract_tenant_id_from_token(token)
            set_current_tenant_id(tid)
            return tid
        else:
            from bisheng.common.services.config_service import settings
            if not settings.multi_tenant.enabled:
                set_current_tenant_id(DEFAULT_TENANT_ID)
            return DEFAULT_TENANT_ID
    except Exception:
        try:
            from bisheng.common.services.config_service import settings
            if not settings.multi_tenant.enabled:
                set_current_tenant_id(DEFAULT_TENANT_ID)
        except Exception:
            pass
        return DEFAULT_TENANT_ID


class CustomMiddleware(BaseHTTPMiddleware):
    """HTTP request middleware — trace ID + tenant context injection."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Trace ID
        if request.headers.get('x-trace-id'):
            trace_id = request.headers.get('x-trace-id')
        else:
            trace_id = trace_id_generator()
        ip = get_request_ip(request)
        path = request.url
        trace_id_var.set(trace_id)

        # Tenant context injection from JWT cookie (returns extracted tenant_id)
        token = request.cookies.get('access_token_cookie')
        tenant_id = _set_tenant_context(token)

        # Tenant status checks (F010)
        req_path = request.url.path
        is_exempt = req_path.startswith(TENANT_CHECK_EXEMPT_PATHS)
        if not is_exempt and token:
            # tenant_id=0 means pending tenant selection — block non-exempt paths
            if tenant_id == 0:
                return JSONResponse(
                    status_code=403,
                    content={'status_code': 20004, 'status_message': 'Missing tenant context', 'data': None},
                )
            # Check if tenant is disabled via Redis blacklist
            if tenant_id and tenant_id > 0:
                try:
                    from bisheng.core.cache.redis_manager import get_redis_client
                    redis_client = await get_redis_client()
                    from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY
                    if await redis_client.aget(DISABLED_TENANT_KEY.format(tenant_id)):
                        return JSONResponse(
                            status_code=403,
                            content={'status_code': 20001, 'status_message': 'Tenant is disabled', 'data': None},
                        )
                except Exception:
                    pass  # Redis unavailable — fail-open for middleware

        logger.info(f"| {ip} | {request.method} {path}")
        start_time = time()
        response = await call_next(request)
        process_time = round(time() - start_time, 4)
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Trace-ID"] = trace_id
        logger.info(f"| {ip} | {request.method} {path} | process_time={process_time}s")
        return response


class WebSocketLoggingMiddleware:
    """WebSocket middleware — trace ID + tenant context injection."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            trace_id = trace_id_generator()
            trace_id_var.set(trace_id)

            # Tenant context injection from JWT cookie
            token = self._get_cookie_from_scope(scope, 'access_token_cookie')
            _set_tenant_context(token)

        await self.app(scope, receive, send)

    @staticmethod
    def _get_cookie_from_scope(scope: dict, cookie_name: str):
        """Extract a cookie value from ASGI scope headers."""
        headers = dict(scope.get('headers', []))
        cookie_header = headers.get(b'cookie', b'').decode('utf-8', errors='ignore')
        if not cookie_header:
            return None
        cookies = http.cookies.SimpleCookie(cookie_header)
        morsel = cookies.get(cookie_name)
        return morsel.value if morsel else None
