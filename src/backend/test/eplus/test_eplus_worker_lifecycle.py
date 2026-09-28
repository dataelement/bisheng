from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml


async def _eventually(predicate, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


class FakeSupervisor:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.started = asyncio.Event()

    async def start(self) -> None:
        self.events.append("supervisor.start")
        self.started.set()

    async def stop(self) -> None:
        self.events.append("supervisor.stop")


class FakeRobotService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("robot.close")


class FailingSupervisor(FakeSupervisor):
    async def stop(self) -> None:
        self.events.append("supervisor.stop")
        raise RuntimeError("stop failed")


async def test_worker_initializes_full_context_and_closes_runtime_in_order() -> None:
    from bisheng.eplus.worker import EPlusWorker, EPlusWorkerRuntime

    events: list[str] = []
    supervisor = FakeSupervisor(events)
    robot = FakeRobotService(events)

    async def initialize(settings, *, instance_role: str) -> None:
        assert settings == "settings"
        assert instance_role == "eplus_worker"
        events.append("context.initialize")

    async def build_runtime() -> EPlusWorkerRuntime:
        events.append("runtime.build")
        return EPlusWorkerRuntime(supervisor=supervisor, robot_service=robot)

    async def close_context() -> None:
        events.append("context.close")

    worker = EPlusWorker(
        settings="settings",
        initialize_context=initialize,
        build_runtime=build_runtime,
        close_context=close_context,
        shutdown_timeout_seconds=1,
    )
    task = asyncio.create_task(worker.run())
    await supervisor.started.wait()
    worker.request_stop()
    await task

    assert events == [
        "context.initialize",
        "runtime.build",
        "supervisor.start",
        "supervisor.stop",
        "robot.close",
        "context.close",
    ]


async def test_worker_cancellation_still_closes_connections_and_context() -> None:
    from bisheng.eplus.worker import EPlusWorker, EPlusWorkerRuntime

    events: list[str] = []
    supervisor = FakeSupervisor(events)
    robot = FakeRobotService(events)

    async def initialize(settings, *, instance_role: str) -> None:
        events.append("context.initialize")

    async def build_runtime() -> EPlusWorkerRuntime:
        return EPlusWorkerRuntime(supervisor=supervisor, robot_service=robot)

    async def close_context() -> None:
        events.append("context.close")

    worker = EPlusWorker(
        settings=object(),
        initialize_context=initialize,
        build_runtime=build_runtime,
        close_context=close_context,
        shutdown_timeout_seconds=1,
    )
    task = asyncio.create_task(worker.run())
    await supervisor.started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert events[-3:] == ["supervisor.stop", "robot.close", "context.close"]


async def test_supervisor_close_failure_does_not_skip_robot_or_context_cleanup() -> None:
    from bisheng.eplus.worker import EPlusWorker, EPlusWorkerRuntime

    events: list[str] = []
    supervisor = FailingSupervisor(events)
    robot = FakeRobotService(events)

    async def initialize(settings, *, instance_role: str) -> None:
        events.append("context.initialize")

    async def build_runtime() -> EPlusWorkerRuntime:
        return EPlusWorkerRuntime(supervisor=supervisor, robot_service=robot)

    async def close_context() -> None:
        events.append("context.close")

    worker = EPlusWorker(
        settings=object(),
        initialize_context=initialize,
        build_runtime=build_runtime,
        close_context=close_context,
        shutdown_timeout_seconds=1,
    )
    task = asyncio.create_task(worker.run())
    await supervisor.started.wait()
    worker.request_stop()
    await task

    assert events[-3:] == ["supervisor.stop", "robot.close", "context.close"]


async def test_switchable_sender_routes_queued_reply_to_reconnected_client() -> None:
    from bisheng.eplus.worker import SwitchableEPlusSender

    class Connection:
        def __init__(self, name: str) -> None:
            self.name = name

        async def send_direct(self, frame):
            return {"errcode": 0, "connection": self.name, "frame": frame}

    sender = SwitchableEPlusSender(wait_timeout_seconds=0.2)
    first = Connection("first")
    second = Connection("second")
    sender.activate(first)
    assert (await sender.send_with_ack({"value": 1}))["connection"] == "first"

    sender.deactivate(first)
    pending = asyncio.create_task(sender.send_with_ack({"value": 2}))
    await asyncio.sleep(0)
    assert not pending.done()
    sender.activate(second)

    assert (await pending)["connection"] == "second"


async def test_worker_connection_waits_for_recovery_before_accepting_callbacks(monkeypatch) -> None:
    import bisheng.eplus.worker as worker_module
    from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
    from bisheng.eplus.infrastructure.connection_supervisor import BotConnectionRef
    from bisheng.eplus.worker import (
        BotExecutionGuard,
        BotIngressCoordinator,
        CallbackTaskRegistry,
        SwitchableEPlusSender,
        WorkerConnection,
    )

    class Client:
        def __init__(self, config, *, on_message) -> None:
            self.on_message = on_message

        async def wait_authenticated(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class Provider:
        async def runtime_context(self, ref, sender):
            return SimpleNamespace(admission=SimpleNamespace(), sender=sender)

    handled = asyncio.Event()

    class Robot:
        async def handle_message(self, context, callback) -> None:
            handled.set()

        async def reserve_message(self, context, callback):
            return callback

        async def handle_reserved_message(self, context, callback, reservation) -> None:
            handled.set()

        async def cancel_bot(self, **kwargs) -> None:
            return None

    recovery_started = asyncio.Event()
    release_recovery = asyncio.Event()

    async def recover_once(ref, context) -> None:
        recovery_started.set()
        await release_recovery.wait()

    async def clear_recovery(ref) -> None:
        return None

    monkeypatch.setattr(worker_module, "EPlusConnectionClient", Client)
    monkeypatch.setattr(worker_module, "parse_message_callback", lambda frame: frame)
    registry = CallbackTaskRegistry()
    connection = WorkerConnection(
        ref=BotConnectionRef(tenant_id=9, bot_config_id=73),
        target=EPlusConnectionTarget(
            tenant_id=9,
            bot_config_id=73,
            assistant_id="assistant-1",
            bot_id="bot-1",
            connection_url="wss://eplus.example/im_openws?bizid=1",
            secret="test-secret",
            ca_object_key=None,
            media_hosts=("eplus.example",),
            credential_version=1,
            scope_version=1,
        ),
        ca_pem=None,
        provider=Provider(),
        robot_service=Robot(),
        callback_registry=registry,
        sender=SwitchableEPlusSender(),
        execution_guard=BotExecutionGuard(),
        ingress=BotIngressCoordinator(),
        recover_once=recover_once,
        clear_recovery=clear_recovery,
    )

    auth_task = asyncio.create_task(connection.wait_authenticated())
    await recovery_started.wait()
    await connection._on_message({"id": "new"})
    await asyncio.sleep(0.01)
    handled_before_recovery = handled.is_set()
    release_recovery.set()
    await auth_task
    await _eventually(handled.is_set)
    await connection.close()

    assert handled_before_recovery is False


async def test_worker_connection_preserves_callback_arrival_order_before_admission(monkeypatch) -> None:
    import bisheng.eplus.worker as worker_module
    from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
    from bisheng.eplus.infrastructure.connection_supervisor import BotConnectionRef
    from bisheng.eplus.worker import (
        BotExecutionGuard,
        BotIngressCoordinator,
        CallbackTaskRegistry,
        SwitchableEPlusSender,
        WorkerConnection,
    )

    class Client:
        def __init__(self, config, *, on_message) -> None:
            self.on_message = on_message

        async def wait_authenticated(self) -> None:
            return None

        async def close(self) -> None:
            return None

    first_context_started = asyncio.Event()
    release_first_context = asyncio.Event()

    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        async def runtime_context(self, ref, sender):
            self.calls += 1
            if self.calls == 2:
                first_context_started.set()
                await release_first_context.wait()
            return SimpleNamespace(admission=SimpleNamespace(), sender=sender)

    reserved: list[str] = []
    handled: list[str] = []
    first_preparation_started = asyncio.Event()
    release_first_preparation = asyncio.Event()
    second_reserved = asyncio.Event()

    class Robot:
        async def handle_message(self, context, callback) -> None:
            if callback["id"] == "first":
                first_preparation_started.set()
                await release_first_preparation.wait()
            else:
                second_reserved.set()
            handled.append(callback["id"])

        async def reserve_message(self, context, callback):
            reserved.append(callback["id"])
            if callback["id"] == "second":
                second_reserved.set()
            return callback

        async def handle_reserved_message(self, context, callback, reservation) -> None:
            if callback["id"] == "first":
                first_preparation_started.set()
                await release_first_preparation.wait()
            handled.append(callback["id"])

        async def cancel_bot(self, **kwargs) -> None:
            return None

    async def recover_once(ref, context) -> None:
        return None

    async def clear_recovery(ref) -> None:
        return None

    monkeypatch.setattr(worker_module, "EPlusConnectionClient", Client)
    monkeypatch.setattr(worker_module, "parse_message_callback", lambda frame: frame)
    registry = CallbackTaskRegistry()
    connection = WorkerConnection(
        ref=BotConnectionRef(tenant_id=9, bot_config_id=73),
        target=EPlusConnectionTarget(
            tenant_id=9,
            bot_config_id=73,
            assistant_id="assistant-1",
            bot_id="bot-1",
            connection_url="wss://eplus.example/im_openws?bizid=1",
            secret="test-secret",
            ca_object_key=None,
            media_hosts=("eplus.example",),
            credential_version=1,
            scope_version=1,
        ),
        ca_pem=None,
        provider=Provider(),
        robot_service=Robot(),
        callback_registry=registry,
        sender=SwitchableEPlusSender(),
        execution_guard=BotExecutionGuard(),
        ingress=BotIngressCoordinator(),
        recover_once=recover_once,
        clear_recovery=clear_recovery,
    )
    await connection.wait_authenticated()

    await connection._on_message({"id": "first"})
    await first_context_started.wait()
    await connection._on_message({"id": "second"})
    await asyncio.sleep(0.01)
    release_first_context.set()
    await first_preparation_started.wait()
    await asyncio.sleep(0.01)
    second_reserved_before_first_prepared = second_reserved.is_set()
    release_first_preparation.set()
    await _eventually(lambda: len(handled) == 2)
    await connection.close()

    assert reserved == ["first", "second"]
    assert set(handled) == {"first", "second"}
    assert second_reserved_before_first_prepared is True


async def test_reconnect_releases_callbacks_waiting_on_shared_recovery(monkeypatch) -> None:
    import bisheng.eplus.worker as worker_module
    from bisheng.eplus.domain.schemas.config import EPlusConnectionTarget
    from bisheng.eplus.infrastructure.connection_supervisor import BotConnectionRef
    from bisheng.eplus.worker import (
        BotExecutionGuard,
        BotIngressCoordinator,
        CallbackTaskRegistry,
        SwitchableEPlusSender,
        WorkerConnection,
    )

    class Client:
        def __init__(self, config, *, on_message) -> None:
            self.on_message = on_message

        async def wait_authenticated(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class Provider:
        async def runtime_context(self, ref, sender):
            return SimpleNamespace(admission=SimpleNamespace(), sender=sender)

    handled: list[str] = []

    class Robot:
        async def reserve_message(self, context, callback):
            return callback

        async def handle_reserved_message(self, context, callback, reservation) -> None:
            handled.append(callback["id"])

        async def cancel_bot(self, **kwargs) -> None:
            return None

    first_recovery_started = asyncio.Event()
    recovery_calls = 0

    async def recover_once(ref, context) -> None:
        nonlocal recovery_calls
        recovery_calls += 1
        if recovery_calls == 1:
            first_recovery_started.set()
            await asyncio.Event().wait()

    async def clear_recovery(ref) -> None:
        return None

    monkeypatch.setattr(worker_module, "EPlusConnectionClient", Client)
    monkeypatch.setattr(worker_module, "parse_message_callback", lambda frame: frame)
    target = EPlusConnectionTarget(
        tenant_id=9,
        bot_config_id=73,
        assistant_id="assistant-1",
        bot_id="bot-1",
        connection_url="wss://eplus.example/im_openws?bizid=1",
        secret="test-secret",
        ca_object_key=None,
        media_hosts=("eplus.example",),
        credential_version=1,
        scope_version=1,
    )
    ref = BotConnectionRef(tenant_id=9, bot_config_id=73)
    provider = Provider()
    robot = Robot()
    registry = CallbackTaskRegistry()
    sender = SwitchableEPlusSender()
    guard = BotExecutionGuard()
    ingress = BotIngressCoordinator()

    def connection() -> WorkerConnection:
        return WorkerConnection(
            ref=ref,
            target=target,
            ca_pem=None,
            provider=provider,
            robot_service=robot,
            callback_registry=registry,
            sender=sender,
            execution_guard=guard,
            ingress=ingress,
            recover_once=recover_once,
            clear_recovery=clear_recovery,
        )

    first = connection()
    first_auth = asyncio.create_task(first.wait_authenticated())
    await first_recovery_started.wait()
    await first._on_message({"id": "received-before-disconnect"})
    first_auth.cancel()
    await asyncio.gather(first_auth, return_exceptions=True)

    second = connection()
    await second.wait_authenticated()
    await _eventually(lambda: handled == ["received-before-disconnect"])
    await second.close()

    assert recovery_calls == 2


def test_entrypoints_expose_dedicated_eplus_mode() -> None:
    root = Path(__file__).resolve().parents[4]
    for path in (root / "src/backend/entrypoint.sh", root / "docker/bisheng/entrypoint.sh"):
        source = path.read_text(encoding="utf-8")
        assert 'elif [ "$start_mode" = "eplus" ]' in source
        assert "python -m bisheng.eplus.worker" in source


def test_compose_runs_eplus_as_independent_stateless_service() -> None:
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["backend_eplus_worker"]

    assert service["command"] == "sh entrypoint.sh eplus"
    assert service["image"] == compose["services"]["backend"]["image"]
    assert service["environment"] == compose["services"]["backend"]["environment"]
    assert all("/app/data" not in volume for volume in service.get("volumes", []))
    assert "celery" not in service["command"]
    assert "linsight" not in service["command"]
