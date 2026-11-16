"""Bind declared routes before dependencies and retain scope through ASGI completion."""

from contextlib import contextmanager
from dataclasses import dataclass

from loguru import logger
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket

from bisheng.admin.application.tenant_scope import EffectiveManagementScope, require_expected_management_tenant
from bisheng.admin.domain.services.tenant_scope import TenantScopeService
from bisheng.common.errcode.admin_scope import AdminScopeChangedError, AdminScopeForbiddenError
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.exceptions.auth import AuthJWTException
from bisheng.common.request_scope import RequestScope, admitted_request_scope, endpoint_scope, route_inventory
from bisheng.core.context import tenant as contexts


@dataclass(frozen=True)
class AdmittedRequest:
    user_id: int
    home_tenant_id: int
    tenant_id: int
    kind: RequestScope
    is_super: bool
    source: str = "own"


async def authenticate_browser(connection):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.user.domain.services.auth import AuthJwt

    connection.state.require_current_super = True
    if connection.scope["type"] == "websocket":
        return await UserPayload.get_login_user_from_ws(connection, AuthJwt())
    auth = AuthJwt(req=connection)
    subject = auth.get_subject()
    if "dsh_web_session" in subject:
        from bisheng.dsh.domain.services.web_session import validate_web_session

        await validate_web_session(connection, subject)
        connection.state.require_current_super = True
        user = await UserPayload.get_login_user(auth)
        user._dsh_web_session_tenant_id = int(subject["tenant_id"])
        return user
    return await UserPayload.get_login_user(auth)


async def request_target(user):
    value = await TenantScopeService.get_scope(user.user_id, is_super=True, for_write=True, require_selection=True)
    # Preserve the existing sliding preference expiry without changing the frozen target.
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import get_redis_client

    try:
        redis = await get_redis_client()
        await redis.aexpire_key(f"admin_scope:{user.user_id}", settings.multi_tenant.admin_scope_ttl_seconds)
    except RedisError:
        logger.opt(exception=True).warning("Management scope TTL refresh failed")
    return EffectiveManagementScope(value["scope_tenant_id"], value["source"], value["expires_at"])


@contextmanager
def bind_admitted_scope(admitted):
    with contexts.tenant_execution_scope(admitted.tenant_id):
        if admitted.kind in {RequestScope.TENANT, RequestScope.PERSONAL}:
            if admitted.source == "credential":
                yield
            elif admitted.is_super:
                with contexts.management_tenant_scope(admitted.tenant_id):
                    yield
            else:
                # Existing Root sharing remains available to its domain gates.
                token = contexts.set_visible_tenant_ids(frozenset({admitted.tenant_id, contexts.DEFAULT_TENANT_ID}))
                try:
                    yield
                finally:
                    contexts.visible_tenant_ids.reset(token)
        else:
            yield


async def admit(connection, kind):
    user = await authenticate_browser(connection)
    connection.state.admitted_login_user = user
    target = user.tenant_id
    source = "own"
    tenant_business = kind in {RequestScope.TENANT, RequestScope.PERSONAL}
    credential_tenant = getattr(user, "_dsh_web_session_tenant_id", None)
    if tenant_business and credential_tenant is not None:
        target = credential_tenant
        source = "credential"
        expected = connection.headers.get("X-Management-Tenant")
        if expected is not None:
            require_expected_management_tenant(expected, EffectiveManagementScope(target, "own", None))
    elif tenant_business:
        selected = await request_target(user) if user.is_global_super else EffectiveManagementScope(target, "own", None)
        target = selected.tenant_id
        source = selected.source
        expected = connection.headers.get("X-Management-Tenant")
        # Native browser WebSockets cannot set custom headers. Their endpoint
        # resource gate still proves the ID belongs to this fixed selection.
        if expected is not None or (user.is_global_super and connection.scope["type"] == "http"):
            require_expected_management_tenant(expected, selected)
    elif kind == RequestScope.PLATFORM and not user.is_global_super:
        raise AdminScopeForbiddenError()
    if tenant_business:
        for supplied in [*connection.query_params.getlist("tenant_id"), connection.path_params.get("tenant_id")]:
            if supplied is not None and str(supplied) != str(target):
                raise AdminScopeChangedError(scope_tenant_id=target)
    admitted = AdmittedRequest(user.user_id, user.tenant_id, target, kind, user.is_global_super, source)
    connection.state.admitted_request = admitted
    connection.state.management_tenant_id = target if tenant_business else None
    return admitted


class ScopedEndpoint:
    def __init__(self, app, kind, variant=None):
        self.app = app
        self.kind = kind
        self.variant = variant

    async def __call__(self, scope, receive, send):
        if self.kind in {RequestScope.CREDENTIAL, RequestScope.PUBLIC}:
            # Their established credential handlers own authentication and scope.
            return await self.app(scope, receive, send)
        connection = Request(scope, receive) if scope["type"] == "http" else WebSocket(scope, receive, send)
        kind = self.kind
        if self.variant and connection.query_params.get(self.variant[0]) == self.variant[1]:
            kind = self.variant[2]
        try:
            admitted = await admit(connection, kind)
        except (AuthJWTException, HTTPException):
            if scope["type"] == "websocket":
                await connection.close(code=1008, reason="Authentication required")
                return
            raise
        except BaseErrorCode as exc:
            if scope["type"] == "websocket":
                await connection.close(code=1008, reason=str(exc.code))
                return
            status = {19701: 403, 19703: 400, 19704: 409, 19705: 503}.get(exc.code, 403)
            return await JSONResponse(exc.return_resp_instance().model_dump(), status_code=status)(scope, receive, send)

        async def scoped_send(message):
            if message["type"] == "http.response.start" and admitted.kind in {
                RequestScope.TENANT,
                RequestScope.PERSONAL,
            }:
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in {b"x-management-tenant", b"x-management-tenant-source"}
                ]
                headers.append((b"x-management-tenant", str(admitted.tenant_id).encode()))
                headers.append((b"x-management-tenant-source", admitted.source.encode()))
                headers = [(name, value) for name, value in headers if name.lower() != b"cache-control"]
                headers.append((b"cache-control", b"private, no-store"))
                headers.append((b"vary", b"X-Management-Tenant, Cookie, Authorization"))
                message = {**message, "headers": headers}
            await send(message)

        token = admitted_request_scope.set(admitted)
        try:
            with bind_admitted_scope(admitted):
                await self.app(scope, receive, scoped_send)
        finally:
            admitted_request_scope.reset(token)


def install_request_admission(app):
    inventory = route_inventory(app.routes)
    for route in app.routes:
        if not isinstance(route.app, ScopedEndpoint):
            route.app = ScopedEndpoint(
                route.app, endpoint_scope(route.endpoint), getattr(route.endpoint, "__bisheng_scope_variant__", None)
            )
    app.state.request_scope_inventory = inventory
    return inventory
