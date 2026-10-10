"""A task failed by someone other than its own run must still reach the live panel.

The worker-startup crash sweep and the worker's force-fail backstop used to write
FAILED to the DB only. The task panel learns about the end of a run solely from
the task-message-stream queue, so after a pod restart the page kept spinning on a
task the DB already called FAILED (customer site, two hours).

``asyncio_mode = auto`` — async tests need no decorator.
"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain import utils
from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum
from bisheng.linsight.domain.services import state_message_manager as smm
from bisheng.linsight.domain.services.state_message_manager import MessageEventType


class FakeStateManager:
    instances: list["FakeStateManager"] = []

    def __init__(self, session_version_id):
        self.session_version_id = session_version_id
        self.session_info = None
        self.tasks = None
        self.pushed = []
        FakeStateManager.instances.append(self)

    async def set_session_version_info(self, session_model):
        self.session_info = session_model

    async def set_execution_tasks(self, tasks):
        self.tasks = tasks

    async def push_message(self, message):
        self.pushed.append(message)


def failed_session(output_result):
    return SimpleNamespace(id="sv-1", session_id="chat-1", user_id=7, output_result=output_result)


def task_row(task_id, status):
    return SimpleNamespace(id=task_id, status=status, model_dump=lambda: {"id": task_id, "status": status.value})


@pytest.fixture
def fakes(monkeypatch):
    FakeStateManager.instances = []
    monkeypatch.setattr(smm, "LinsightStateMessageManager", FakeStateManager)
    persist = AsyncMock()
    monkeypatch.setattr(utils, "persist_task_turn_message", persist)

    def _apply(session, tasks):
        monkeypatch.setattr(utils.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session))
        monkeypatch.setattr(utils.LinsightExecuteTaskDao, "get_by_session_version_id", AsyncMock(return_value=tasks))
        return persist

    return _apply


async def test_pushes_task_end_per_failed_row_then_error_message(fakes):
    session = failed_session({"error_message": "Worker node crash detected"})
    tasks = [
        task_row("t-done", ExecuteTaskStatusEnum.SUCCESS),
        task_row("t-killed", ExecuteTaskStatusEnum.FAILED),
    ]
    persist = fakes(session, tasks)

    await utils.announce_stranded_session_failure("sv-1")

    manager = FakeStateManager.instances[0]
    events = [(m.event_type, m.data.get("id")) for m in manager.pushed]
    assert events == [(MessageEventType.TASK_END, "t-killed"), (MessageEventType.ERROR_MESSAGE, None)]

    error = manager.pushed[-1].data
    assert error["error"] == "Worker node crash detected"
    # The sweep records no classification; the card must still render.
    assert error["error_type"] == "unknown"

    # Redis copies that still said in-progress are overwritten from the DB.
    assert manager.session_info is session
    assert manager.tasks == tasks
    persist.assert_awaited_once_with(session)


async def test_keeps_the_classification_the_writer_recorded(fakes):
    fakes(
        failed_session(
            {"error_message": "Task aborted unexpectedly: x", "error_type": "network_timeout", "error_code": 1}
        ),
        [],
    )

    await utils.announce_stranded_session_failure("sv-1")

    manager = FakeStateManager.instances[0]
    assert [m.event_type for m in manager.pushed] == [MessageEventType.ERROR_MESSAGE]
    assert manager.pushed[0].data["error_type"] == "network_timeout"
    assert manager.pushed[0].data["error_code"] == 1


async def test_missing_session_is_a_no_op(fakes):
    fakes(None, [])
    await utils.announce_stranded_session_failure("gone")
    assert FakeStateManager.instances == []


async def test_failure_never_escapes(fakes, monkeypatch):
    """One session failing here must not stop the sweep over the others."""
    fakes(failed_session({"error_message": "x"}), [])
    monkeypatch.setattr(utils, "persist_task_turn_message", AsyncMock(side_effect=RuntimeError("db down")))

    await utils.announce_stranded_session_failure("sv-1")  # must not raise


async def test_crash_sweep_announces_every_terminated_session(monkeypatch):
    class StubNodeManager:
        def __init__(self, redis_client, node_id):
            pass

    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.NodeManager = StubNodeManager
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)
    monkeypatch.setattr(utils, "get_redis_client", AsyncMock(return_value=SimpleNamespace(aget=AsyncMock(return_value=None))))
    monkeypatch.setattr(type(utils.settings), "aget_all_config", AsyncMock(return_value={}))

    orphans = [SimpleNamespace(id="sv-1", user_id=1), SimpleNamespace(id="sv-2", user_id=2)]
    monkeypatch.setattr(
        utils.LinsightSessionVersionDao, "get_session_versions_by_status", AsyncMock(return_value=orphans)
    )
    monkeypatch.setattr(utils.LinsightSessionVersionDao, "batch_update_session_versions_status", AsyncMock())
    monkeypatch.setattr(utils.LinsightExecuteTaskDao, "batch_update_status_by_session_version_id", AsyncMock())
    announce = AsyncMock()
    monkeypatch.setattr(utils, "announce_stranded_session_failure", announce)

    await utils.check_and_terminate_incomplete_tasks("node-A")

    assert [c.args[0] for c in announce.await_args_list] == ["sv-1", "sv-2"]
