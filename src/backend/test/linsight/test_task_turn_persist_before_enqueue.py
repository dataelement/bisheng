"""Regression: the bot task turn is persisted BEFORE the session is enqueued.

``persist_task_turn_message`` is a find-then-insert upsert with no unique key,
and the worker runs the same upsert at execution start (``_execute_workflow``).
An idle worker dequeues within milliseconds, so persisting AFTER the enqueue
raced the worker: both sides found no ``category="task"`` row for the SV, both
inserted, and the unified conversation rendered the whole task panel twice
(seen on the test environment on every task turn: two rows created in the same
second, one holding the answer and one an empty placeholder).

Writing the row first turns the worker's call into a plain in-place update.
Both API-side writers are covered: the unified ``/c`` task submit and the legacy
``/workbench/start-execute`` endpoint. Pure unit tests: all I/O faked.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.linsight.api.endpoints import linsight as endpoint
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.workstation.domain.services import chat_service


def _order_recorder(calls: list, *, persist_raises: bool = False):
    async def _persist(_session_model):
        calls.append("persist")
        if persist_raises:
            raise RuntimeError("db down")

    async def _enqueue(_session_model):
        calls.append("enqueue")

    return _persist, _enqueue


# ---------------------------------------------------------------------------
# unified /c task submit (workstation chat_service)
# ---------------------------------------------------------------------------
async def _drain(response) -> list:
    return [chunk async for chunk in response.body_iterator]


def _task_data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-09-20T00:00:00Z",
        conversationId="chat-1",
        model="m1",
        text="结合知识库评估 OKR 制度",
        task_mode=True,
    )


@pytest.fixture
def unified_submit(monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "evaluate_workbench_user_text",
        staticmethod(lambda *_a, **_k: None),
    )
    session_version = SimpleNamespace(id="sv-1", session_id="chat-1")
    monkeypatch.setattr(
        "bisheng.linsight.domain.services.workbench_impl.LinsightWorkbenchImpl.submit_user_question",
        AsyncMock(return_value=(MagicMock(), session_version)),
    )
    monkeypatch.setattr(chat_service.LLMService, "get_bisheng_llm", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(chat_service, "gen_title", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "_TITLE_GEN_TIMEOUT_S", 0.1)

    def _run(calls: list, *, persist_raises: bool = False):
        persist, enqueue = _order_recorder(calls, persist_raises=persist_raises)
        monkeypatch.setattr("bisheng.linsight.domain.utils.persist_task_turn_message", persist)
        monkeypatch.setattr("bisheng.linsight.domain.utils.enqueue_session_for_execution", enqueue)
        return chat_service._task_mode_stream_completion(MagicMock(), _task_data(), MagicMock())

    return _run


async def test_unified_submit_persists_task_turn_before_enqueue(unified_submit):
    calls: list = []
    await _drain(await unified_submit(calls))
    assert calls == ["persist", "enqueue"]


async def test_unified_submit_persist_failure_still_enqueues(unified_submit):
    """The row is best-effort (the worker writes it at start regardless); the
    run itself must never be lost because the placeholder could not be written."""
    calls: list = []
    await _drain(await unified_submit(calls, persist_raises=True))
    assert calls == ["persist", "enqueue"]


# ---------------------------------------------------------------------------
# legacy /workbench/start-execute
# ---------------------------------------------------------------------------
@pytest.fixture
def start_execute(monkeypatch):
    monkeypatch.setattr(
        endpoint.LinsightSessionVersionDao,
        "get_by_id",
        AsyncMock(
            return_value=LinsightSessionVersion(
                id="SV-1",
                session_id="chat-1",
                user_id=7,
                question="q",
                status=SessionVersionStatusEnum.NOT_STARTED,
                tenant_id=1,
            )
        ),
    )
    monkeypatch.setattr(endpoint.MessageSessionDao, "touch_session", AsyncMock())
    # keep the heavy worker import chain out of the test (see
    # test_start_execute_persists_task_turn.py for why the stub is shaped so)
    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.LinsightQueue = lambda *a, **k: SimpleNamespace(put=AsyncMock())
    fake_worker.encode_queue_item = lambda session_version_id, **kwargs: {"session_version_id": session_version_id, **kwargs}
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)

    def _run(calls: list, *, persist_raises: bool = False):
        persist, enqueue = _order_recorder(calls, persist_raises=persist_raises)
        monkeypatch.setattr(endpoint.linsight_execute_utils, "persist_task_turn_message", persist)
        monkeypatch.setattr(endpoint.linsight_execute_utils, "enqueue_session_for_execution", enqueue)
        return endpoint.start_execute(linsight_session_version_id="SV-1", login_user=SimpleNamespace(user_id=7))

    return _run


async def test_start_execute_persists_task_turn_before_enqueue(start_execute):
    calls: list = []
    resp = await start_execute(calls)
    assert resp.data is True
    assert calls == ["persist", "enqueue"]


async def test_start_execute_persist_failure_still_enqueues(start_execute):
    calls: list = []
    resp = await start_execute(calls, persist_raises=True)
    assert resp.data is True
    assert calls == ["persist", "enqueue"]
