"""Single-active E+ connection supervision and desired-state reconciliation."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger

from bisheng.core.lock import RedisLockBusyError, RedisLockLostError, TokenSafeRedisLock
from bisheng.eplus.domain.models.eplus import EPlusConnectionStatus
from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
from bisheng.eplus.infrastructure.config_adapters import EPLUS_CONFIG_CHANGED_CHANNEL
from bisheng.eplus.infrastructure.connection_client import EPlusConnectionExitReason


@dataclass(frozen=True, slots=True)
class BotConnectionRef:
    tenant_id: int
    bot_config_id: int


class ConnectionTargetProvider(Protocol):
    async def list_bot_refs(self) -> tuple[BotConnectionRef, ...]: ...

    async def resolve_target(self, ref: BotConnectionRef) -> EPlusConnectionTarget | None: ...

    async def read_ca(self, target: EPlusConnectionTarget) -> bytes | None: ...

    async def set_status(self, ref: BotConnectionRef, status: EPlusConnectionStatus) -> None: ...


class SupervisedConnection(Protocol):
    async def wait_authenticated(self) -> None: ...

    async def run_connection_once(self) -> EPlusConnectionExitReason: ...

    async def close(self) -> None: ...


class Lease(Protocol):
    async def acquire(self) -> None: ...

    def ensure_owned(self) -> None: ...

    async def release(self) -> None: ...


class ConfigNotificationSource(Protocol):
    async def next_ref(self) -> BotConnectionRef | None: ...

    async def close(self) -> None: ...


class RedisConfigNotificationSource:
    """Translate Redis config-change messages into supervisor wakeups."""

    def __init__(self, redis_client: Any) -> None:
        connection = getattr(redis_client, "async_connection", redis_client)
        self._pubsub = connection.pubsub()
        self._subscribed = False

    async def next_ref(self) -> BotConnectionRef | None:
        if not self._subscribed:
            await self._pubsub.subscribe(EPLUS_CONFIG_CHANGED_CHANNEL)
            self._subscribed = True
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message is None:
                await asyncio.sleep(0)
                continue
            raw = message.get("data") if isinstance(message, dict) else None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                event = json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                logger.warning("ignored malformed E+ config notification")
                continue
            tenant_id = event.get("tenant_id")
            bot_config_id = event.get("bot_config_id")
            if tenant_id is None or bot_config_id is None:
                return None
            return BotConnectionRef(tenant_id=int(tenant_id), bot_config_id=int(bot_config_id))

    async def close(self) -> None:
        if self._subscribed:
            await self._pubsub.unsubscribe(EPLUS_CONFIG_CHANGED_CHANNEL)
            self._subscribed = False
        close = getattr(self._pubsub, "aclose", None) or getattr(self._pubsub, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


ClientFactory = Callable[[EPlusConnectionTarget, bytes | None], SupervisedConnection]
LeaseFactory = Callable[[BotConnectionRef], Lease]
BackoffWaiter = Callable[[float, asyncio.Event], Awaitable[None]]


@dataclass(slots=True)
class _BotRuntime:
    ref: BotConnectionRef
    target: EPlusConnectionTarget
    signature: tuple[Any, ...]
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    client: SupervisedConnection | None = None
    frozen: bool = False


class EPlusConnectionSupervisor:
    """Continuously converge SQL targets into one leased connection per bot."""

    def __init__(
        self,
        *,
        target_provider: ConnectionTargetProvider,
        client_factory: ClientFactory,
        lease_factory: LeaseFactory | None = None,
        redis_client: Any | None = None,
        notification_source: ConfigNotificationSource | None = None,
        reconcile_interval_seconds: float = 30.0,
        lease_ttl_seconds: int = 15,
        lease_renewal_seconds: float = 5.0,
        lease_check_interval_seconds: float = 1.0,
        backoff_waiter: BackoffWaiter | None = None,
    ) -> None:
        if reconcile_interval_seconds <= 0 or lease_check_interval_seconds <= 0:
            raise ValueError("E+ supervisor intervals must be positive")
        if lease_factory is None:
            if redis_client is None:
                raise ValueError("redis_client or lease_factory is required")

            def lease_factory(ref: BotConnectionRef) -> TokenSafeRedisLock:
                return TokenSafeRedisLock(
                    redis_client,
                    f"eplus:bot_lease:{ref.tenant_id}:{ref.bot_config_id}",
                    ttl_seconds=lease_ttl_seconds,
                    renewal_interval_seconds=lease_renewal_seconds,
                )

        self._provider = target_provider
        self._client_factory = client_factory
        self._lease_factory = lease_factory
        self._notification_source = notification_source
        self._reconcile_interval = float(reconcile_interval_seconds)
        self._lease_check_interval = float(lease_check_interval_seconds)
        self._backoff_waiter = backoff_waiter or _default_backoff_waiter
        self._runtimes: dict[BotConnectionRef, _BotRuntime] = {}
        self._reconcile_lock = asyncio.Lock()
        self._periodic_task: asyncio.Task[None] | None = None
        self._notification_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._periodic_task is not None:
            return
        self._stopping = False
        await self.reconcile_once()
        self._periodic_task = asyncio.create_task(self._periodic_loop())
        if self._notification_source is not None:
            self._notification_task = asyncio.create_task(self._notification_loop())

    async def stop(self) -> None:
        self._stopping = True
        await _cancel_task(self._notification_task)
        await _cancel_task(self._periodic_task)
        self._notification_task = None
        self._periodic_task = None
        for ref in tuple(self._runtimes):
            await self._stop_runtime(ref)
        if self._notification_source is not None:
            await self._notification_source.close()

    async def notify_config_changed(self, ref: BotConnectionRef | None = None) -> None:
        await self.reconcile_once(only_ref=ref)

    async def reconcile_once(self, *, only_ref: BotConnectionRef | None = None) -> None:
        async with self._reconcile_lock:
            all_refs = set(await self._provider.list_bot_refs())
            refs = {only_ref} if only_ref is not None and only_ref in all_refs else all_refs
            if only_ref is None:
                for removed_ref in set(self._runtimes) - all_refs:
                    await self._stop_runtime(removed_ref)

            for ref in refs:
                target = await self._provider.resolve_target(ref)
                runtime = self._runtimes.get(ref)
                if target is None:
                    if runtime is not None:
                        await self._stop_runtime(ref)
                    await self._provider.set_status(ref, EPlusConnectionStatus.DISABLED)
                    continue

                signature = _connection_signature(target)
                if runtime is None:
                    self._start_runtime(ref, target, signature)
                    continue
                if runtime.signature != signature:
                    await self._stop_runtime(ref)
                    self._start_runtime(ref, target, signature)
                    continue
                runtime.target = target
                if runtime.task is not None and runtime.task.done() and not runtime.frozen:
                    await self._stop_runtime(ref)
                    self._start_runtime(ref, target, signature)

    def _start_runtime(
        self,
        ref: BotConnectionRef,
        target: EPlusConnectionTarget,
        signature: tuple[Any, ...],
    ) -> None:
        runtime = _BotRuntime(ref=ref, target=target, signature=signature)
        runtime.task = asyncio.create_task(self._run_runtime(runtime))
        self._runtimes[ref] = runtime

    async def _stop_runtime(self, ref: BotConnectionRef) -> None:
        runtime = self._runtimes.pop(ref, None)
        if runtime is None:
            return
        runtime.stop_event.set()
        if runtime.client is not None:
            await runtime.client.close()
        task = runtime.task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run_runtime(self, runtime: _BotRuntime) -> None:
        lease: Lease | None = None
        try:
            while not self._stopping and not runtime.stop_event.is_set():
                lease = self._lease_factory(runtime.ref)
                try:
                    await lease.acquire()
                except RedisLockBusyError:
                    await _wait_or_stop(self._reconcile_interval, runtime.stop_event)
                    lease = None
                    continue

                retry_index = 0
                lease_task = asyncio.create_task(self._monitor_lease(lease))
                try:
                    while not self._stopping and not runtime.stop_event.is_set():
                        outcome = await self._run_connection_attempt(runtime, lease_task)
                        if outcome == "stop":
                            return
                        if outcome == "lease_lost":
                            await _wait_or_stop(self._lease_check_interval, runtime.stop_event)
                            break
                        if outcome is EPlusConnectionExitReason.TAKEN_OVER:
                            runtime.frozen = True
                            await self._provider.set_status(runtime.ref, EPlusConnectionStatus.TAKEN_OVER)
                            return

                        await self._provider.set_status(runtime.ref, EPlusConnectionStatus.RETRYING)
                        delay = min(2**retry_index, 30)
                        retry_index += 1
                        backoff_outcome = await self._wait_backoff(runtime, lease_task, delay)
                        if backoff_outcome == "stop":
                            return
                        if backoff_outcome == "lease_lost":
                            await _wait_or_stop(self._lease_check_interval, runtime.stop_event)
                            break
                finally:
                    await _cancel_task(lease_task)
                    await _release_lease(lease)
                    lease = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "E+ connection supervisor crashed for tenant={} config={}",
                runtime.ref.tenant_id,
                runtime.ref.bot_config_id,
            )
            await self._provider.set_status(runtime.ref, EPlusConnectionStatus.ERROR)
        finally:
            if runtime.client is not None:
                await runtime.client.close()
                runtime.client = None
            if lease is not None:
                await _release_lease(lease)

    async def _run_connection_attempt(
        self,
        runtime: _BotRuntime,
        lease_task: asyncio.Task[None],
    ) -> EPlusConnectionExitReason | str:
        ca_pem = await self._provider.read_ca(runtime.target)
        client = self._client_factory(runtime.target, ca_pem)
        runtime.client = client
        await self._provider.set_status(runtime.ref, EPlusConnectionStatus.CONNECTING)
        connection_task = asyncio.create_task(client.run_connection_once())
        auth_task = asyncio.create_task(client.wait_authenticated())
        stop_task = asyncio.create_task(runtime.stop_event.wait())
        authenticated = False
        try:
            while True:
                watched = {connection_task, lease_task, stop_task}
                if not authenticated:
                    watched.add(auth_task)
                done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
                if auth_task in done and not authenticated:
                    await auth_task
                    authenticated = True
                    await self._provider.set_status(runtime.ref, EPlusConnectionStatus.AUTHENTICATED)
                    continue
                if stop_task in done:
                    await client.close()
                    await _cancel_task(connection_task)
                    return "stop"
                if lease_task in done:
                    try:
                        await lease_task
                    except RedisLockLostError:
                        await client.close()
                        await _cancel_task(connection_task)
                        await self._provider.set_status(runtime.ref, EPlusConnectionStatus.ERROR)
                        return "lease_lost"
                if connection_task in done:
                    return await connection_task
        except Exception:
            logger.opt(exception=True).warning(
                "E+ connection attempt failed for tenant={} config={}",
                runtime.ref.tenant_id,
                runtime.ref.bot_config_id,
            )
            return EPlusConnectionExitReason.DISCONNECTED
        finally:
            await _cancel_task(auth_task)
            await _cancel_task(stop_task)
            if not connection_task.done():
                await client.close()
                await _cancel_task(connection_task)

    async def _wait_backoff(
        self,
        runtime: _BotRuntime,
        lease_task: asyncio.Task[None],
        delay: float,
    ) -> str:
        backoff_task = asyncio.create_task(self._backoff_waiter(delay, runtime.stop_event))
        stop_task = asyncio.create_task(runtime.stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {backoff_task, lease_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                return "stop"
            if lease_task in done:
                try:
                    await lease_task
                except RedisLockLostError:
                    if runtime.client is not None:
                        await runtime.client.close()
                    await self._provider.set_status(runtime.ref, EPlusConnectionStatus.ERROR)
                    return "lease_lost"
            await backoff_task
            return "retry"
        finally:
            await _cancel_task(backoff_task)
            await _cancel_task(stop_task)

    async def _monitor_lease(self, lease: Lease) -> None:
        while True:
            await asyncio.sleep(self._lease_check_interval)
            lease.ensure_owned()

    async def _periodic_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reconcile_interval)
            await self.reconcile_once()

    async def _notification_loop(self) -> None:
        assert self._notification_source is not None
        while True:
            ref = await self._notification_source.next_ref()
            await self.reconcile_once(only_ref=ref)


def _connection_signature(target: EPlusConnectionTarget) -> tuple[Any, ...]:
    return (
        target.bot_id,
        target.connection_url,
        target.secret,
        target.ca_object_key,
        int(target.credential_version),
    )


async def _default_backoff_waiter(delay: float, stop_event: asyncio.Event) -> None:
    await _wait_or_stop(delay, stop_event)


async def _wait_or_stop(delay: float, stop_event: asyncio.Event) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=delay)


async def _release_lease(lease: Lease) -> None:
    try:
        await lease.release()
    except Exception:
        logger.exception("E+ lease release failed")


async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
