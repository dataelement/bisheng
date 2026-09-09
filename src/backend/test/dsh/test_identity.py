"""F062 identity binding and current-state checks. 覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-13, AC-30, AC-31."""

import asyncio
from dataclasses import replace

import pytest

from bisheng.common.errcode.dsh import DshInvalidGrantError, DshUserDisabledError
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.services.identity import BrowserIdentity, IdentityRecord, IdentityService


class Records:
    record = IdentityRecord("2", "1001", "alice", None, None, 0, True, True, True)

    async def get(self, tenant_id, user_id):
        return self.record if (tenant_id, user_id) == (self.record.tenant_id, self.record.user_id) else None


class Intent:
    expires_in = 300

    async def resolve(self, auth_id):
        return {
            "challenge": "a" * 43,
            "redirect_uri": "http://127.0.0.1:54321/dsh/callback",
            "client_id": "dsh-desktop",
            "instance": "instance-test",
            "state": "opaque-state",
            "expires_in": self.expires_in,
        }


async def test_snapshot_always_reads_current_identity():
    records = Records()
    service = IdentityService("instance-test", None, records, Intent())
    snapshot = await service.check("2", "1001")
    assert snapshot.active and snapshot.user.display_name == "alice" and snapshot.tenant.name == "Tenant 2"
    records.record = replace(records.record, username="renamed", display_name="Alice", profile_version=1)
    snapshot = await service.check("2", "1001")
    assert snapshot.user.username == "renamed" and snapshot.profile_version == 1
    records.record = replace(records.record, active=False)
    assert not (await service.check("2", "1001")).active
    assert not (await service.check("3", "1001")).active


@pytest.mark.parametrize("changes", [{"username": " "}, {"natural_person": False}, {"tenant_active": False}])
async def test_inactive_identity_never_leaks_display(changes):
    records = Records()
    records.record = replace(records.record, **changes)
    result = await IdentityService("instance-test", None, records, Intent()).check("2", "1001")
    assert not result.active and result.user is None and result.tenant is None


async def test_browser_authorization_refuses_service_identity():
    service = IdentityService("instance-test", None, Records(), Intent())
    with pytest.raises(DshUserDisabledError):
        await service.authorize(BrowserIdentity("2", "1001", "service_account"), "auth-test")


async def test_browser_denial_resolves_safe_callback_without_issuing_ticket():
    service = IdentityService("instance-test", None, Records(), Intent())
    result = await service.authorize(BrowserIdentity("2", "1001"), "auth-test", decision="deny")
    assert result == {
        "error": "access_denied",
        "redirect_uri": "http://127.0.0.1:54321/dsh/callback",
        "state": "opaque-state",
    }
    assert "identity_ticket" not in result


async def test_real_redis_ticket_is_atomic_bound_expiring_and_digest_only(dsh_redis_url):
    from redis.asyncio import Redis

    redis = Redis.from_url(dsh_redis_url, decode_responses=True)
    tickets = TicketRepository(redis, "instance-test")
    service = IdentityService("instance-test", tickets, Records(), Intent())
    result = await service.authorize(BrowserIdentity("2", "1001"), "auth-test")
    ticket = result["identity_ticket"]
    binding = {
        "auth_id": "auth-test",
        "client_id": "dsh-desktop",
        "redirect_uri": result["redirect_uri"],
        "code_challenge": "a" * 43,
    }
    key = tickets.key(ticket)
    assert ticket not in key and ticket not in await redis.get(key)
    assert 0 < await redis.ttl(key) <= 60
    with pytest.raises(DshInvalidGrantError):
        await service.redeem(ticket, {**binding, "auth_id": "other"})
    outcomes = await asyncio.gather(*(service.redeem(ticket, binding) for _ in range(8)), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in outcomes) == 1
    assert sum(isinstance(result, DshInvalidGrantError) for result in outcomes) == 7
    ticket = (await service.authorize(BrowserIdentity("2", "1001"), "auth-test"))["identity_ticket"]
    await redis.pexpire(tickets.key(ticket), 1)
    await asyncio.sleep(0.01)
    with pytest.raises(DshInvalidGrantError):
        await service.redeem(ticket, binding)
    await redis.aclose()


async def test_ticket_does_not_outlive_authorization(dsh_redis_url):
    from redis.asyncio import Redis

    redis = Redis.from_url(dsh_redis_url)
    intent = Intent()
    intent.expires_in = 7
    tickets = TicketRepository(redis, "instance-test")
    service = IdentityService("instance-test", tickets, Records(), intent)
    result = await service.authorize(BrowserIdentity("2", "1001"), "near-expiry")
    assert result["expires_in"] == 7
    assert 0 < await redis.ttl(tickets.key(result["identity_ticket"])) <= 7
    await redis.delete(tickets.key(result["identity_ticket"]))
    await redis.aclose()
