"""F073: ``LinsightWorkbenchImpl.terminate`` is the termination body shared by
the v1 endpoint and the Open API (spec AC-23)."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.models.session import MessageSessionDao
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion, SessionVersionStatusEnum
from bisheng.linsight.domain.services import state_message_manager, workbench_impl
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl


@pytest.fixture
def io(monkeypatch):
    captured = {"removed": [], "pushed": [], "saved": [], "persisted": []}

    async def _remove(svid):
        captured["removed"].append(svid)

    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.LinsightQueue = lambda *a, **k: SimpleNamespace(remove=_remove)
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)
    monkeypatch.setattr(workbench_impl, "get_redis_client", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(MessageSessionDao, "touch_session", AsyncMock())

    async def _save(model):
        captured["saved"].append(model.status)

    async def _push(message):
        captured["pushed"].append(message.event_type)

    monkeypatch.setattr(
        state_message_manager,
        "LinsightStateMessageManager",
        lambda **k: SimpleNamespace(set_session_version_info=_save, push_message=_push),
    )

    async def _persist(model):
        captured["persisted"].append(model.id)

    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", _persist)
    return captured


@pytest.mark.parametrize("status", [SessionVersionStatusEnum.NOT_STARTED, SessionVersionStatusEnum.IN_PROGRESS])
async def test_terminate_queued_or_running(io, status):
    session = LinsightSessionVersion(
        id="SV-1", session_id="chat-1", user_id=7, question="q", status=status, tenant_id=1
    )

    await LinsightWorkbenchImpl.terminate(session)

    assert session.status == SessionVersionStatusEnum.TERMINATED
    assert io["removed"] == ["SV-1"]
    assert io["saved"] == [SessionVersionStatusEnum.TERMINATED]
    assert io["persisted"] == ["SV-1"]
    assert io["pushed"] == [state_message_manager.MessageEventType.TASK_TERMINATED]


async def test_queue_failure_does_not_block_termination(io, monkeypatch):
    async def _boom(_svid):
        raise RuntimeError("redis down")

    sys.modules["bisheng.linsight.worker"].LinsightQueue = lambda *a, **k: SimpleNamespace(remove=_boom)
    session = LinsightSessionVersion(id="SV-2", session_id="chat-1", user_id=7, question="q", tenant_id=1)

    await LinsightWorkbenchImpl.terminate(session)

    assert session.status == SessionVersionStatusEnum.TERMINATED
