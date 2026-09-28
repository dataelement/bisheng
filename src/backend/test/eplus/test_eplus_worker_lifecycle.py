from __future__ import annotations

import asyncio
from pathlib import Path

import yaml


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
