"""Real SQL state machine tests; SQLite does not substitute for production row locking."""

import asyncio
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.user.domain.models.platform_session import PlatformRefreshToken, PlatformSession, PlatformWebTicket
from bisheng.user.domain.repositories.platform_session import PlatformSessionRepository
from bisheng.user.domain.services.platform_session import PlatformSessionService


@pytest.fixture
def runtime(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/auth.db")
    SQLModel.metadata.create_all(
        engine, tables=[t.__table__ for t in (PlatformSession, PlatformRefreshToken, PlatformWebTicket)]
    )
    identity = {"id": 7, "user_name": "test", "tenant_id": 9, "tenant_name": "home", "token_version": 0}
    sqlite_lock = threading.Lock()  # SQLite has no FOR UPDATE; production locks require dual-DB acceptance.

    class Repo(PlatformSessionRepository):
        def identity(self, user_id, tenant_id, **kwargs):
            return dict(identity) if user_id == 7 and tenant_id == 9 else None

    @contextmanager
    def scope():
        with sqlite_lock, Session(engine) as db, db.begin():
            yield Repo(db)

    clock = [datetime(2026, 1, 1)]
    service = PlatformSessionService(scope, secret="test-secret-not-production", now=lambda: clock[0])
    return service, clock, identity


async def test_default_ttls_refresh_does_not_renew(runtime):
    """AC-05/06/07/08: 30-day Access, 90-day idle; only activity renews."""
    service, clock, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    assert issued["expires_in"] == 30 * 86400
    assert issued["refresh_expires_in"] == 90 * 86400
    original = issued["session_expires_at"]
    clock[0] += timedelta(days=29)
    rotated = await service.refresh(issued["refresh_token"])
    assert rotated["session_expires_at"] == original
    await service.activity(rotated["access_token"])
    renewed = await service.inspect(rotated["access_token"])
    assert renewed["session_expires_at"] != original


async def test_deterministic_recovery_then_replay_revokes_family(runtime):
    """AC-11: Lost-response recovery never creates a second refresh branch."""
    service, _, _ = runtime
    first = await service.issue(7, 9, "bisheng-mobile")
    second = await service.refresh(first["refresh_token"])
    retry = await service.refresh(first["refresh_token"])
    assert retry["refresh_token"] == second["refresh_token"]
    await service.refresh(second["refresh_token"])
    with pytest.raises(PlatformAuthError, match="refresh_token_reused"):
        await service.refresh(first["refresh_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.inspect(second["access_token"])


async def test_bootstrap_token_never_becomes_business_credential(runtime):
    """AC-03/23: A gateway entry token stays bootstrap-only after binding."""
    service, _, _ = runtime
    pending = await service.issue(7, 9, "bisheng-web", pending=True)
    with pytest.raises(PlatformAuthError, match="web_bootstrap_required"):
        await service.inspect(pending["access_token"])
    bound = await service.bootstrap(pending["access_token"])
    retry = await service.bootstrap(pending["access_token"])
    assert bound["refresh_token"] == retry["refresh_token"]
    await service.inspect(bound["access_token"])
    with pytest.raises(PlatformAuthError, match="web_bootstrap_required"):
        await service.inspect(pending["access_token"])
    await service.refresh(bound["refresh_token"])
    with pytest.raises(PlatformAuthError, match="web_binding_completed"):
        await service.bootstrap(pending["access_token"])


async def test_revoke_version_and_expiry(runtime):
    """AC-10/15: Version, logout and idle expiry are authoritative."""
    service, clock, identity = runtime
    first = await service.issue(7, 9, "bisheng-mobile")
    identity["token_version"] += 1
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.refresh(first["refresh_token"])
    second = await service.issue(7, 9, "bisheng-mobile")
    await service.logout(second["access_token"])
    await service.logout(second["access_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.inspect(second["access_token"])
    third = await service.issue(7, 9, "bisheng-mobile")
    clock[0] += timedelta(days=91)
    with pytest.raises(PlatformAuthError, match="session_expired"):
        await service.refresh(third["refresh_token"])


async def test_session_policy_is_frozen_and_absolute_cap_applies(runtime):
    """AC-05/06/07: Configuration updates affect new sessions only."""
    service, clock, _ = runtime
    first = await service.issue(7, 9, "bisheng-mobile")
    service.access_seconds, service.idle_seconds, service.grace_seconds = 86400, 10 * 86400, 0
    service.absolute_seconds = 5 * 86400
    second = await service.issue(7, 9, "bisheng-mobile")
    assert second["expires_in"] == 86400
    clock[0] += timedelta(days=1)
    rotated = await service.refresh(first["refresh_token"])
    assert rotated["expires_in"] == 30 * 86400
    await service.activity(rotated["access_token"])
    assert (await service.inspect(rotated["access_token"]))["session_expires_at"] == "2026-04-02T00:00:00+00:00"
    # Refresh the second token at its one-day access boundary, then record activity.
    second_rotated = await service.refresh(second["refresh_token"])
    await service.activity(second_rotated["access_token"])
    assert (await service.inspect(second_rotated["access_token"]))["session_expires_at"] == "2026-01-06T00:00:00+00:00"


async def test_same_second_tokens_and_live_single_login_policy(runtime):
    """AC-13: Same-second logins are unique and current login policy is read live."""
    service, _, _ = runtime
    multi = [True]

    async def policy():
        return multi[0]

    service.login_policy_reader = policy
    first = await service.issue(7, 9, "bisheng-mobile")
    second = await service.issue(7, 9, "bisheng-web")
    assert first["access_token"] != second["access_token"]
    assert first["session_id"] != second["session_id"]
    await service.inspect(first["access_token"])
    multi[0] = False
    final = await service.issue(7, 9, "bisheng-mobile")
    for old in (first, second):
        with pytest.raises(PlatformAuthError, match="session_revoked"):
            await service.inspect(old["access_token"])
    refreshed = await service.refresh(final["refresh_token"])
    assert refreshed["session_id"] == final["session_id"]


async def test_serialized_parallel_retries_and_no_resurrection(runtime):
    """AC-12: Serialized SQL retries converge; a late activity cannot resurrect logout."""
    service, _, _ = runtime
    first = await service.issue(7, 9, "bisheng-mobile")
    results = await asyncio.gather(*(service.refresh(first["refresh_token"]) for _ in range(8)))
    assert len({result["refresh_token"] for result in results}) == 1
    await service.logout(results[0]["access_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.activity(results[0]["access_token"])


async def test_host_activity_renews_parent_and_refresh(runtime):
    """AC-07/26: WebView business activity keeps the native parent and current RT alive."""
    service, clock, _ = runtime
    parent = await service.issue(7, 9, "bisheng-mobile")
    ticket = await service.create_ticket(parent["access_token"], "https://platform.test")
    host = await service.consume_ticket(ticket["ticket"], "https://platform.test")
    clock[0] += timedelta(days=29)
    await service.activity(host["access_token"])
    refreshed = await service.refresh(parent["refresh_token"])
    assert refreshed["session_expires_at"] == "2026-04-30T00:00:00+00:00"
    await service.logout(host["access_token"])
    await service.inspect(refreshed["access_token"])


async def test_refresh_grace_is_24_hours_and_does_not_recover_consumed_successor(runtime):
    """AC-11: The stored grace policy ends after 24h and always revokes stale reuse."""
    service, clock, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    await service.refresh(issued["refresh_token"])
    clock[0] += timedelta(days=1, seconds=1)
    with pytest.raises(PlatformAuthError, match="refresh_token_reused"):
        await service.refresh(issued["refresh_token"])


async def test_closed_worker_reference_cannot_bypass_logout(runtime):
    """AC-26: A queued platform reference retains its exact Session and original AT expiry."""
    from test.platform_auth.test_platform_stream import reference

    service, _, _ = runtime
    issued = await service.issue(7, 9, "bisheng-mobile")
    ref = reference(service, issued)
    assert (await service.validate_reference(ref))["id"] == 7
    await service.logout(issued["access_token"])
    with pytest.raises(PlatformAuthError, match="session_revoked"):
        await service.validate_reference(ref)
