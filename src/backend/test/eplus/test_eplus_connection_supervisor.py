from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace

from bisheng.core.lock import RedisLockBusyError, RedisLockLostError
from bisheng.eplus.domain.models.eplus import EPlusConnectionStatus
from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
from bisheng.eplus.infrastructure.connection_client import EPlusConnectionExitReason
from bisheng.eplus.infrastructure.connection_supervisor import (
    BotConnectionRef,
    EPlusConnectionSupervisor,
    RedisConfigNotificationSource,
)


async def _eventually(predicate, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


def _target(*, credential_version: int = 1) -> EPlusConnectionTarget:
    return EPlusConnectionTarget(
        tenant_id=9,
        bot_config_id=73,
        assistant_id="assistant-1",
        bot_id="bot-1",
        connection_url="wss://eplus.example/im_openws?bizid=1",
        secret=f"secret-v{credential_version}",
        ca_object_key=None,
        media_hosts=("eplus.example",),
        credential_version=credential_version,
        scope_version=1,
    )


class FakeTargetProvider:
    def __init__(self, target: EPlusConnectionTarget | None) -> None:
        self.ref = BotConnectionRef(tenant_id=9, bot_config_id=73)
        self.refs = {self.ref}
        self.target = target
        self.statuses: list[EPlusConnectionStatus] = []

    async def list_bot_refs(self) -> tuple[BotConnectionRef, ...]:
        return tuple(self.refs)

    async def resolve_target(self, ref: BotConnectionRef) -> EPlusConnectionTarget | None:
        assert ref == self.ref
        return self.target

    async def read_ca(self, target: EPlusConnectionTarget) -> bytes | None:
        return None

    async def set_status(self, ref: BotConnectionRef, status: EPlusConnectionStatus) -> None:
        assert ref == self.ref
        self.statuses.append(status)


class FakeLeaseRegistry:
    def __init__(self) -> None:
        self.owners: dict[str, FakeLease] = {}

    def factory(self, ref: BotConnectionRef):
        return FakeLease(self, f"eplus:bot_lease:{ref.tenant_id}:{ref.bot_config_id}")

    def expire(self, key: str) -> None:
        self.owners.pop(key, None)


class FakeLease:
    def __init__(self, registry: FakeLeaseRegistry, key: str) -> None:
        self.registry = registry
        self.key = key
        self.released = False

    async def acquire(self) -> None:
        if self.key in self.registry.owners:
            raise RedisLockBusyError(self.key)
        self.registry.owners[self.key] = self

    def ensure_owned(self) -> None:
        if self.registry.owners.get(self.key) is not self:
            raise RedisLockLostError(self.key)

    async def release(self) -> None:
        if self.registry.owners.get(self.key) is self:
            self.registry.owners.pop(self.key)
        self.released = True


class FakeClient:
    def __init__(self, reason: EPlusConnectionExitReason | None = None) -> None:
        self.reason = reason
        self.authenticated = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_calls = 0

    async def wait_authenticated(self) -> None:
        await self.authenticated.wait()

    async def run_connection_once(self) -> EPlusConnectionExitReason:
        self.authenticated.set()
        if self.reason is not None:
            return self.reason
        await self.closed.wait()
        return EPlusConnectionExitReason.DISCONNECTED

    async def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class FakeClientFactory:
    def __init__(self, reasons=()) -> None:
        self.reasons = deque(reasons)
        self.clients: list[FakeClient] = []
        self.targets: list[EPlusConnectionTarget] = []

    def __call__(self, target: EPlusConnectionTarget, ca_pem: bytes | None) -> FakeClient:
        assert ca_pem is None
        reason = self.reasons.popleft() if self.reasons else None
        client = FakeClient(reason)
        self.clients.append(client)
        self.targets.append(target)
        return client


def _supervisor(provider, factory, leases, **kwargs) -> EPlusConnectionSupervisor:
    return EPlusConnectionSupervisor(
        target_provider=provider,
        client_factory=factory,
        lease_factory=leases.factory,
        reconcile_interval_seconds=kwargs.pop("reconcile_interval_seconds", 0.01),
        lease_check_interval_seconds=kwargs.pop("lease_check_interval_seconds", 0.005),
        **kwargs,
    )


async def test_two_instances_create_only_one_connection_and_stop_releases_lease() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    first_factory = FakeClientFactory()
    second_factory = FakeClientFactory()
    first = _supervisor(provider, first_factory, leases)
    second = _supervisor(provider, second_factory, leases)

    await asyncio.gather(first.start(), second.start())
    await _eventually(lambda: len(first_factory.clients) + len(second_factory.clients) == 1)

    assert len(leases.owners) == 1
    await asyncio.gather(first.stop(), second.stop())
    assert leases.owners == {}


async def test_lease_loss_closes_old_connection_and_other_instance_takes_over() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    first_factory = FakeClientFactory()
    second_factory = FakeClientFactory()
    first = _supervisor(provider, first_factory, leases, reconcile_interval_seconds=0.005)
    second = _supervisor(provider, second_factory, leases, reconcile_interval_seconds=0.005)

    await first.start()
    await _eventually(lambda: len(first_factory.clients) == 1)
    await second.start()
    leases.expire("eplus:bot_lease:9:73")

    await _eventually(lambda: first_factory.clients[0].close_calls >= 1)
    await _eventually(lambda: len(second_factory.clients) == 1)
    await asyncio.gather(first.stop(), second.stop())


async def test_ordinary_disconnect_uses_bounded_exponential_backoff() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory([EPlusConnectionExitReason.DISCONNECTED] * 6)
    delays: list[float] = []
    block_after_six = asyncio.Event()

    async def backoff_waiter(delay: float, wake: asyncio.Event) -> None:
        delays.append(delay)
        if len(delays) >= 6:
            await block_after_six.wait()

    supervisor = _supervisor(provider, factory, leases, backoff_waiter=backoff_waiter)
    await supervisor.start()
    await _eventually(lambda: len(delays) >= 6)

    assert delays[:6] == [1, 2, 4, 8, 16, 30]
    block_after_six.set()
    await supervisor.stop()


async def test_lease_loss_during_reconnect_backoff_closes_previous_client() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory([EPlusConnectionExitReason.DISCONNECTED])
    backoff_started = asyncio.Event()
    release_backoff = asyncio.Event()

    async def backoff_waiter(delay: float, wake: asyncio.Event) -> None:
        backoff_started.set()
        await release_backoff.wait()

    supervisor = _supervisor(
        provider,
        factory,
        leases,
        lease_check_interval_seconds=0.001,
        backoff_waiter=backoff_waiter,
    )
    await supervisor.start()
    await backoff_started.wait()
    leases.expire("eplus:bot_lease:9:73")
    await asyncio.sleep(0.02)
    close_calls_before_backoff_ended = factory.clients[0].close_calls
    release_backoff.set()
    await supervisor.stop()

    assert close_calls_before_backoff_ended >= 1


async def test_offline_disabled_or_deleted_target_disconnects_and_online_target_connects() -> None:
    provider = FakeTargetProvider(None)
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory()
    supervisor = _supervisor(provider, factory, leases, reconcile_interval_seconds=60)

    await supervisor.start()
    assert factory.clients == []
    assert provider.statuses[-1] is EPlusConnectionStatus.DISABLED

    provider.target = _target()
    await supervisor.notify_config_changed(provider.ref)
    await _eventually(lambda: len(factory.clients) == 1)
    assert EPlusConnectionStatus.AUTHENTICATED in provider.statuses

    provider.target = None
    await supervisor.notify_config_changed(provider.ref)
    await _eventually(lambda: factory.clients[0].close_calls >= 1)
    assert provider.statuses[-1] is EPlusConnectionStatus.DISABLED
    await supervisor.stop()


async def test_credential_change_restarts_connection_but_scope_change_does_not() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory()
    supervisor = _supervisor(provider, factory, leases, reconcile_interval_seconds=60)
    await supervisor.start()
    await _eventually(lambda: len(factory.clients) == 1)

    provider.target = replace(provider.target, scope_version=2)
    await supervisor.notify_config_changed(provider.ref)
    await asyncio.sleep(0.01)
    assert len(factory.clients) == 1

    provider.target = _target(credential_version=2)
    await supervisor.notify_config_changed(provider.ref)
    await _eventually(lambda: len(factory.clients) == 2)
    assert factory.clients[0].close_calls >= 1
    assert factory.targets[-1].credential_version == 2
    await supervisor.stop()


async def test_periodic_reconciliation_repairs_lost_notification() -> None:
    provider = FakeTargetProvider(None)
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory()
    supervisor = _supervisor(provider, factory, leases, reconcile_interval_seconds=0.005)
    await supervisor.start()

    provider.target = _target()
    await _eventually(lambda: len(factory.clients) == 1)
    await supervisor.stop()


async def test_taken_over_connection_is_frozen_and_not_reacquired() -> None:
    provider = FakeTargetProvider(_target())
    leases = FakeLeaseRegistry()
    factory = FakeClientFactory([EPlusConnectionExitReason.TAKEN_OVER])
    supervisor = _supervisor(provider, factory, leases, reconcile_interval_seconds=0.005)
    await supervisor.start()
    await _eventually(lambda: EPlusConnectionStatus.TAKEN_OVER in provider.statuses)
    await asyncio.sleep(0.03)

    assert len(factory.clients) == 1
    assert leases.owners == {}
    await supervisor.stop()


async def test_redis_notification_source_parses_bot_events_and_closes_pubsub() -> None:
    class FakePubSub:
        def __init__(self) -> None:
            self.messages = deque(
                [
                    None,
                    {"type": "message", "data": b'{"tenant_id":9,"bot_config_id":73}'},
                ]
            )
            self.subscribed: list[str] = []
            self.closed = False

        async def subscribe(self, channel: str) -> None:
            self.subscribed.append(channel)

        async def get_message(self, **kwargs):
            return self.messages.popleft() if self.messages else None

        async def unsubscribe(self, channel: str) -> None:
            self.subscribed.remove(channel)

        async def aclose(self) -> None:
            self.closed = True

    pubsub = FakePubSub()

    class FakeRedis:
        def pubsub(self):
            return pubsub

    source = RedisConfigNotificationSource(FakeRedis())

    assert await source.next_ref() == BotConnectionRef(tenant_id=9, bot_config_id=73)
    await source.close()
    assert pubsub.subscribed == []
    assert pubsub.closed is True
