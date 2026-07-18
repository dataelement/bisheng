"""Regression: enqueuing a task (start-execute) must persist its bot task turn so
the 排队中 QueueCard survives a page refresh while the task is still QUEUED.

A queued task sits at session status NOT_STARTED until the Linsight worker
dequeues it (``_execute_workflow`` flips it to IN_PROGRESS and only THEN writes
the ``category='task'`` placeholder row). In the unified ``/c`` conversation the
task turn is discovered from the chat messages, so without a row persisted at
enqueue time a refresh-while-queued finds only the user question — the whole task
panel, queue badge included, disappears.

``start_execute`` therefore upserts the task turn right after a successful
enqueue. These tests fake all I/O (DAO / Redis / state manager) and assert the
persist is invoked with the queued session.
"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.api.endpoints import linsight as endpoint
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)


def _session(*, status=SessionVersionStatusEnum.NOT_STARTED):
    return LinsightSessionVersion(
        id="SV-1",
        session_id="chat-1",
        user_id=7,
        question="帮我研究 2026 年 SLM 进展",
        status=status,
        tenant_id=1,
    )


def _login_user(user_id=7):
    return SimpleNamespace(user_id=user_id)


@pytest.fixture
def patched_endpoint(monkeypatch):
    """Fake every I/O dependency of start_execute and capture the persist call."""
    captured = {}

    monkeypatch.setattr(
        endpoint.LinsightSessionVersionDao,
        "get_by_id",
        AsyncMock(return_value=_session()),
    )
    monkeypatch.setattr(endpoint.MessageSessionDao, "touch_session", AsyncMock())
    monkeypatch.setattr(endpoint, "get_redis_client", AsyncMock(return_value=SimpleNamespace()))

    # LinsightQueue is imported function-locally from bisheng.linsight.worker;
    # inject a stub module so the heavy worker import chain is never loaded.
    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.LinsightQueue = lambda *a, **k: SimpleNamespace(put=AsyncMock())
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)

    async def _fake_persist(session_model):
        captured["session"] = session_model

    monkeypatch.setattr(endpoint.linsight_execute_utils, "persist_task_turn_message", _fake_persist)
    return captured


async def test_start_execute_persists_queued_task_turn(patched_endpoint):
    """Enqueuing a NOT_STARTED task persists the bot task turn so a refresh while
    queued can re-hydrate the turn and keep showing the queue badge."""
    resp = await endpoint.start_execute(linsight_session_version_id="SV-1", login_user=_login_user())

    assert resp.data is True
    persisted = patched_endpoint.get("session")
    assert persisted is not None
    assert persisted.id == "SV-1"


async def test_start_execute_persist_failure_does_not_break_enqueue(monkeypatch, patched_endpoint):
    """The persist is best-effort: a failure must not fail the start-execute call
    (the worker writes the row at execution start regardless)."""

    async def _boom(_session_model):
        raise RuntimeError("db down")

    monkeypatch.setattr(endpoint.linsight_execute_utils, "persist_task_turn_message", _boom)

    resp = await endpoint.start_execute(linsight_session_version_id="SV-1", login_user=_login_user())

    assert resp.data is True


async def test_start_execute_rejects_in_progress(monkeypatch, patched_endpoint):
    """An already-running session is rejected and never re-persisted/enqueued."""
    monkeypatch.setattr(
        endpoint.LinsightSessionVersionDao,
        "get_by_id",
        AsyncMock(return_value=_session(status=SessionVersionStatusEnum.IN_PROGRESS)),
    )

    await endpoint.start_execute(linsight_session_version_id="SV-1", login_user=_login_user())

    assert "session" not in patched_endpoint  # persist never reached
