"""Standalone Linsight startup installs the real source graphs before readiness.

The actual process entrypoint runs on its own loop. Redis, permission transport
and the heartbeat are isolated; reference composition and getters are real.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core import context
from bisheng.department.domain.services import department_projection_scope
from bisheng.knowledge.application import model_reference_read
from bisheng.linsight import worker
from bisheng.llm.application import model_default_read
from bisheng.permission.application import process_runtime
from bisheng.resource_reference import composition, read_composition
from bisheng.resource_reference.application import access, source_access


class ReadyBoundary(Exception):
    """Stop before starting the heartbeat or consuming queue items."""


@pytest.fixture(autouse=True)
def cold_reference_process(monkeypatch):
    for module, names in [
        (composition, ("_runtime",)),
        (read_composition, ("_runtime", "_knowledge_model_runtime", "_model_default_runtime")),
        (access, ("_runtime",)),
        (source_access, ("_runtime",)),
        (model_reference_read, ("_runtime",)),
        (model_default_read, ("_runtime",)),
    ]:
        for name in names:
            monkeypatch.setattr(module, name, None)


@pytest.fixture
def standalone(monkeypatch):
    loops = []

    def configure(enabled):
        events = []
        loop = asyncio.new_event_loop()
        loops.append(loop)
        monkeypatch.setattr(worker.asyncio, "new_event_loop", lambda: loop)
        monkeypatch.setattr(worker, "set_logger_config", Mock())
        monkeypatch.setattr(
            worker, "settings", SimpleNamespace(logger_conf={}, openfga=SimpleNamespace(enabled=enabled))
        )
        monkeypatch.setattr(worker, "get_redis_client_sync", Mock(return_value=object()))
        monkeypatch.setattr(worker, "LinsightQueue", Mock())
        monkeypatch.setattr(context, "initialize_app_context", AsyncMock())
        monkeypatch.setattr(process_runtime, "register_f048_permission_runtime_context", Mock())
        monkeypatch.setattr(department_projection_scope, "register_department_projection_runtime_context", Mock())
        warm = AsyncMock(side_effect=lambda: events.append("permissions_ready"))
        monkeypatch.setattr(process_runtime, "get_f048_process_runtime", warm)

        def before_heartbeat(*args, **kwargs):
            # These exact getters fail in a cold standalone process before the
            # repair. Missing business coverage is a separate per-call gate.
            assert access.get_reference_binding_runtime_sync() is composition._runtime
            assert model_default_read.get_model_default_read_runtime() is read_composition._model_default_runtime
            assert (
                model_reference_read.get_knowledge_model_read_runtime_sync()
                is read_composition._knowledge_model_runtime
            )
            events.append("before_heartbeat")
            raise ReadyBoundary()

        heartbeat = Mock(side_effect=before_heartbeat)
        monkeypatch.setattr(worker.NodeManager, "get_instance", heartbeat)
        process = worker.ScheduleCenterProcess.__new__(worker.ScheduleCenterProcess)
        process.max_concurrency = SimpleNamespace(value=1)
        process.node_id = SimpleNamespace(value="standalone-node")
        return SimpleNamespace(process=process, warm=warm, heartbeat=heartbeat, events=events)

    yield configure
    for loop in loops:
        loop.close()
    asyncio.set_event_loop(None)


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_standalone_entrypoint_installs_graphs_before_heartbeat(standalone, enabled):
    setup = standalone(enabled)
    with pytest.raises(ReferenceCoverageNotReadyError):
        model_default_read.get_model_default_read_runtime()
    with pytest.raises(ReadyBoundary):
        setup.process.run()
    assert setup.events == (["permissions_ready", "before_heartbeat"] if enabled else ["before_heartbeat"])
    assert setup.warm.await_count == int(enabled)


def test_permission_readiness_failure_prevents_registration_and_heartbeat(standalone):
    setup = standalone(True)
    error = RuntimeError("published permission catalog is not ready")
    setup.warm.side_effect = error
    with pytest.raises(RuntimeError) as raised:
        setup.process.run()
    assert raised.value is error
    setup.heartbeat.assert_not_called()
    with pytest.raises(ReferenceCoverageNotReadyError):
        model_default_read.get_model_default_read_runtime()


def test_reference_registration_failure_prevents_heartbeat(standalone, monkeypatch):
    setup = standalone(False)
    error = RuntimeError("reference composition failed")
    monkeypatch.setattr(composition, "register", Mock(side_effect=error))
    with pytest.raises(RuntimeError) as raised:
        setup.process.run()
    assert raised.value is error
    setup.heartbeat.assert_not_called()
