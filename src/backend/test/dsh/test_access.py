"""F062 dedicated access trust. 覆盖 AC: AC-04, AC-13, AC-14, AC-15, AC-16, AC-17, AC-30, AC-31, AC-32."""

import asyncio
import time

import jwt
import pytest

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError, DshSeatRevokedError
from bisheng.core.context import tenant as context
from bisheng.dsh.domain.schemas.contracts import DshIdentitySnapshot, DshTenantDisplay, DshUserDisplay
from bisheng.dsh.domain.services.access import DshAccessService, principal_scope
from bisheng.dsh.infrastructure.gateway_client import SeatIntrospection


class Keys:
    key = b"test-only-hmac-access-key-32bytes!"

    async def resolve(self, kid):
        if kid != "test-key":
            raise DshInvalidAccessTokenError()
        return self.key


class Identities:
    async def check(self, tenant_id, user_id):
        assert context.get_current_tenant_id() == int(tenant_id)
        return DshIdentitySnapshot(
            installation_id="instance-test",
            tenant_id=tenant_id,
            user_id=user_id,
            active=True,
            user=DshUserDisplay(id=user_id, username="alice", display_name="Alice"),
            tenant=DshTenantDisplay(id=tenant_id, name="Tenant"),
            profile_version=0,
        )


class Seats:
    active = True

    async def introspect(self, _):
        return SeatIntrospection(
            active=self.active,
            seat_id="42",
            session_id="session-test",
            grant_version=1,
            reason=None if self.active else "seat_revoked",
        )


def token(**overrides):
    now = int(time.time())
    claims = {
        "iss": "test-issuer",
        "aud": "bisheng-dsh-model",
        "sub": "1001",
        "installation_id": "instance-test",
        "tenant_id": "2",
        "seat_id": "42",
        "session_id": "session-test",
        "grant_version": 1,
        "iat": now,
        "exp": now + 300,
        "jti": "test-jti",
    }
    claims.update(overrides)
    return jwt.encode(claims, Keys.key, algorithm="HS256", headers={"kid": "test-key", "typ": "bisheng-dsh-access+jwt"})


def service(seats=None):
    return DshAccessService("instance-test", "test-issuer", Keys(), Identities(), seats or Seats())


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "ordinary-jwt"},
        {"aud": "bisheng-web"},
        {"exp": 1},
        {"installation_id": "other"},
        {"grant_version": True},
        {"tenant_id": 2},
        {"sub": "sak:1"},
        {"grant_version": 0},
    ],
)
async def test_rejects_wrong_credential_scope_and_claim_types(changes):
    with pytest.raises(DshInvalidAccessTokenError):
        await service().authenticate("Bearer " + token(**changes))


async def test_pat_sak_and_ordinary_jwt_are_not_fallback_credentials():
    for credential in ("pat_example", "sak_example", jwt.encode({"sub": "1001"}, "test-only" * 4, algorithm="HS256")):
        with pytest.raises(DshInvalidAccessTokenError):
            await service().authenticate("Bearer " + credential)


async def test_online_seat_check_and_parallel_scopes_are_restored():
    seats = Seats()
    access = service(seats)
    scope_token = context.set_admin_scope_tenant_id(99)
    try:
        principal = await access.authenticate("Bearer " + token())
        assert context.get_current_tenant_id() == 99

        async def read(tenant_id):
            principal = await access.authenticate("Bearer " + token(tenant_id=str(tenant_id)))
            with principal_scope(principal):
                await asyncio.sleep(0)
                return context.get_current_tenant_id(), context.get_visible_tenant_ids()

        assert await asyncio.gather(read(2), read(3)) == [(2, frozenset({1, 2})), (3, frozenset({1, 3}))]
        seats.active = False
        with pytest.raises(DshSeatRevokedError):
            await access.authenticate("Bearer " + token())
        with pytest.raises(asyncio.CancelledError), principal_scope(principal):
            assert context.get_current_tenant_id() == 2
            raise asyncio.CancelledError()
        assert context.get_current_tenant_id() == 99
    finally:
        scope_token.var.reset(scope_token)
