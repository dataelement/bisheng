"""Use the platform's verified identity and tenant-admin application protocol.

Market records are tenant distribution settings. They have no personal owners,
resource grants, inherited sharing, or root-to-child catalogue visibility.
"""

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request


@dataclass(frozen=True)
class MarketActor:
    tenant_id: int
    user_id: int
    global_super: bool = False
    desktop: bool = False


async def market_actor(request: Request) -> MarketActor:
    from bisheng.core.context.tenant import set_current_tenant_id, set_is_management_api, set_visible_tenant_ids
    from bisheng.user.domain.services.auth import AuthJwt, LoginUser
    from bisheng.utils.http_middleware import _validate_token_version

    authorization = request.headers.get("authorization", "")
    if len(request.headers.getlist("authorization")) > 1:
        raise HTTPException(401, "Use one enterprise credential")
    if authorization.startswith("Bearer "):
        try:
            desktop = jwt.get_unverified_header(authorization[7:]).get("typ") == "bisheng-dsh-access+jwt"
        except jwt.PyJWTError:
            desktop = False
        if desktop:
            from bisheng.common.errcode.base import BaseErrorCode
            from bisheng.core.context import tenant as tenant_context
            from bisheng.dsh.access_runtime import get_runtime, get_settings

            try:
                runtime = await get_runtime(request, get_settings())
                principal = await runtime.access.authenticate(authorization)
            except BaseErrorCode as exc:
                raise HTTPException(getattr(exc, "HttpStatus", 503), exc.Msg) from exc
            tenant_id = int(principal.tenant_id)
            set_is_management_api(False)
            set_current_tenant_id(tenant_id)
            set_visible_tenant_ids(frozenset({tenant_id}))
            tenant_context.set_admin_scope_tenant_id(None)
            tenant_context._bypass_tenant_filter.set(False)
            return MarketActor(tenant_id, int(principal.user_id), desktop=True)
    token = request.cookies.get("access_token_cookie")
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "Enterprise login required")
    try:
        subject = AuthJwt(request).decode_jwt_token(token)
        user_id = int(subject["user_id"])
        token_version = int(subject.get("token_version", 0))
    except Exception as exc:
        raise HTTPException(401, "Invalid enterprise credential") from exc
    if not await _validate_token_version(user_id, token_version):
        raise HTTPException(401, "Enterprise credential expired")
    user = await LoginUser.init_login_user(
        user_id=user_id,
        user_name=subject.get("user_name", ""),
        tenant_id=int(subject.get("tenant_id", 1)),
        token_version=token_version,
    )
    set_is_management_api(False)
    set_current_tenant_id(user.tenant_id)
    set_visible_tenant_ids(frozenset({user.tenant_id}))
    return MarketActor(user.tenant_id, user.user_id, user.is_global_super)


async def market_admin(request: Request, actor: MarketActor = Depends(market_actor)) -> MarketActor:
    from bisheng.common.errcode.dsh_market import MarketPermissionError
    from bisheng.common.permission_identity import check_tenant_admin
    from bisheng.core.context.tenant import set_current_tenant_id, set_is_management_api, set_visible_tenant_ids
    from bisheng.dsh_market.infrastructure import tenant_is_active

    if actor.desktop:
        raise MarketPermissionError()

    # A pinned header checks the request's login tenant; identity determines the scope.
    header = request.headers.get("x-dsh-market-tenant")
    if header is not None and header != str(actor.tenant_id):
        raise MarketPermissionError()
    tenant = actor.tenant_id
    set_is_management_api(False)
    set_current_tenant_id(tenant)
    set_visible_tenant_ids(frozenset({tenant}))
    if actor.global_super or await check_tenant_admin(actor.user_id, tenant):
        if not await tenant_is_active(tenant):
            raise MarketPermissionError()
        return actor
    raise MarketPermissionError()
