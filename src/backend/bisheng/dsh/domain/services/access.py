"""DSH-only JWT validation and online seat checks with explicit tenant scope."""

from collections.abc import Iterator
from contextlib import contextmanager

import jwt
from pydantic import Field, ValidationError

from bisheng.common.errcode.dsh import (
    ERROR_BY_CLIENT_CODE,
    DshAuthorizationUnavailableError,
    DshInvalidAccessTokenError,
    DshUserDisabledError,
)
from bisheng.core.context import tenant as tenant_context
from bisheng.dsh.domain.schemas.contracts import DshContract, SubjectId


class DshPrincipal(DshContract):
    tenant_id: SubjectId
    user_id: SubjectId
    seat_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    grant_version: int = Field(strict=True, ge=1)


@contextmanager
def principal_scope(principal: DshPrincipal) -> Iterator[None]:
    """Re-enter inside an SSE generator; returning a response does not retain this scope."""
    tenant_id = int(principal.tenant_id)
    # Clear inherited admin/bypass flags as well as the visible tenant set.
    tokens = [
        tenant_context.set_current_tenant_id(tenant_id),
        tenant_context.set_visible_tenant_ids(frozenset({tenant_id, 1})),
        tenant_context.set_admin_scope_tenant_id(None),
        tenant_context.set_is_management_api(False),
        tenant_context._bypass_tenant_filter.set(False),
        tenant_context._strict_tenant_filter.set(False),
    ]
    try:
        yield
    finally:
        for token in reversed(tokens):
            token.var.reset(token)


class DshAccessService:
    def __init__(self, issuer: str, keys, identities, gateway):
        self.issuer = issuer
        self.keys = keys
        self.identities = identities
        self.gateway = gateway

    async def authenticate(self, authorization: str) -> DshPrincipal:
        if not authorization.startswith("Bearer ") or len(authorization) > 16384:
            raise DshInvalidAccessTokenError()
        token = authorization[7:]
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "HS256"
                or header.get("typ") != "bisheng-dsh-access+jwt"
                or not isinstance(header.get("kid"), str)
                or not header["kid"]
                or len(header["kid"]) > 128
                or any(name in header for name in ("jku", "jwk", "x5u", "crit"))
            ):
                raise DshInvalidAccessTokenError()
            key = await self.keys.resolve(header["kid"])
            claims = jwt.decode(
                token,
                key,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience="bisheng-dsh-model",
                options={
                    "require": [
                        "iss",
                        "aud",
                        "sub",
                        "tenant_id",
                        "seat_id",
                        "session_id",
                        "grant_version",
                        "iat",
                        "exp",
                        "jti",
                    ],
                    "strict_aud": True,
                },
            )
            if (
                len(claims) != 10
                or type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or claims["exp"] <= claims["iat"]
                or claims["exp"] - claims["iat"] > 600
                or not isinstance(claims["jti"], str)
                or not claims["jti"]
            ):
                raise DshInvalidAccessTokenError()
            principal = DshPrincipal(
                tenant_id=claims["tenant_id"],
                user_id=claims["sub"],
                seat_id=claims["seat_id"],
                session_id=claims["session_id"],
                grant_version=claims["grant_version"],
            )
            if int(principal.tenant_id) < 1 or int(principal.user_id) < 1:
                raise DshInvalidAccessTokenError()
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError):
            raise DshInvalidAccessTokenError() from None
        with principal_scope(principal):
            identity = await self.identities.check(principal.tenant_id, principal.user_id)
            if not identity.active:
                raise DshUserDisabledError()
            if (identity.tenant_id, identity.user_id) != (
                principal.tenant_id,
                principal.user_id,
            ):
                raise DshInvalidAccessTokenError()
            seat = await self.gateway.introspect(token)
            if not seat.active:
                error = ERROR_BY_CLIENT_CODE.get(seat.reason, DshAuthorizationUnavailableError)
                raise error()
            if (seat.seat_id, seat.session_id, seat.grant_version) != (
                principal.seat_id,
                principal.session_id,
                principal.grant_version,
            ):
                raise DshInvalidAccessTokenError()
        return principal
