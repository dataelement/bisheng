"""Regression: terminating a task must persist its bot task turn so the
"task terminated" banner survives a page refresh.

Two termination cases share the ``/workbench/terminate-execute`` endpoint:

- **Terminate a running task** — ``_execute_workflow`` already wrote a
  ``category='task'`` placeholder row at execution start, so a refresh
  re-hydrates the turn and shows the terminated banner.
- **Cancel a queued task** — the task never reached ``_execute_workflow``, so
  no task row was ever written. Without an explicit persist on termination, a
  refresh shows only the user question and the banner is lost.

The endpoint therefore upserts the task turn on termination. These tests fake
all I/O (DAO / Redis / state manager) and assert the persist is invoked with the
terminated session, regardless of whether a placeholder row already exists.
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


@pytest.fixture
def patched_endpoint(monkeypatch):
    """Fake every I/O dependency of terminate_execute and capture the persist call."""
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
    fake_worker.LinsightQueue = lambda *a, **k: SimpleNamespace(remove=AsyncMock())
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)

    monkeypatch.setattr(
        endpoint,
        "LinsightStateMessageManager",
        lambda **k: SimpleNamespace(set_session_version_info=AsyncMock(), push_message=AsyncMock()),
    )

    async def _fake_persist(session_model):
        captured["session"] = session_model

    monkeypatch.setattr(endpoint.linsight_execute_utils, "persist_task_turn_message", _fake_persist)
    return captured


def _login_user(user_id=7):
    return SimpleNamespace(user_id=user_id)


async def test_terminate_queued_task_persists_task_turn(patched_endpoint):
    """Cancelling a queued (NOT_STARTED) task persists the bot task turn so a
    refresh can still render the terminated banner."""
    resp = await endpoint.terminate_execute(linsight_session_version_id="SV-1", login_user=_login_user())

    assert resp.data is True
    persisted = patched_endpoint["session"]
    assert persisted is not None
    # Status must be flipped to TERMINATED before the turn is persisted.
    assert persisted.status == SessionVersionStatusEnum.TERMINATED


async def test_terminate_rejects_already_terminated(monkeypatch, patched_endpoint):
    """An already-terminated session is a no-op (no second persist)."""
    monkeypatch.setattr(
        endpoint.LinsightSessionVersionDao,
        "get_by_id",
        AsyncMock(return_value=_session(status=SessionVersionStatusEnum.TERMINATED)),
    )

    await endpoint.terminate_execute(linsight_session_version_id="SV-1", login_user=_login_user())

    assert "session" not in patched_endpoint  # persist never reached
