"""A task-mode submit must enqueue itself, without waiting for the browser.

Enqueueing used to be the client's job: submit created the session and streamed
a ``linsight_task_handoff`` event, and only then did the browser POST
``/workbench/start-execute``. Everything between those two steps was a window in
which the task could be lost — and it was not a narrow one, because
``submit_user_question`` used to parse every attachment inline. A production task
with 12 attachments spent 19 minutes in that call; the user stopped waiting, so
the second request never came and the session sat at NOT_STARTED forever. The
conversation lost its task row too, which is why even the task-mode badge
vanished on reload. Ingestion now runs in the worker, so the window is short —
but a short window is still a window, and the browser is still optional. (Where
the parsing went, and what deliberately stayed behind in the request, is pinned
in ``test_deferred_ingest.py``.)

So: submit enqueues server-side, and start-execute degrades to a late retry.
That makes double-enqueue the normal case (server + client), which is safe
because the executor rejects re-entry on an already-running session — but it
also means start-execute must stop reporting "already running" as an error, or
the frontend's `.catch` marks a perfectly healthy task as failed.

Pure unit tests: no Redis, no DB, no worker.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum


def _session(status=SessionVersionStatusEnum.NOT_STARTED, user_id=1):
    return SimpleNamespace(
        id="sv-1",
        session_id="chat-1",
        tenant_id=1,
        user_id=user_id,
        status=status,
    )


# ---------------------------------------------------------------------------
# enqueue_session_for_execution: the shared entry point
# ---------------------------------------------------------------------------
async def test_enqueue_puts_the_session_on_the_worker_queue(monkeypatch: pytest.MonkeyPatch):
    put = AsyncMock()

    class _Queue:
        def __init__(self, *args, **kwargs):
            self.put = put

    import bisheng.linsight.worker as worker_mod

    monkeypatch.setattr(worker_mod, "LinsightQueue", _Queue)
    monkeypatch.setattr(worker_mod, "encode_queue_item", lambda svid, tenant_id: f"{svid}:{tenant_id}")
    monkeypatch.setattr(linsight_execute_utils, "get_redis_client", AsyncMock(return_value=object()))

    await linsight_execute_utils.enqueue_session_for_execution(_session())

    put.assert_awaited_once()
    assert put.await_args.kwargs["data"] == "sv-1:1"


# ---------------------------------------------------------------------------
# start-execute: idempotent for a session the server already enqueued
# ---------------------------------------------------------------------------
@pytest.fixture
def endpoint_env(monkeypatch: pytest.MonkeyPatch):
    from bisheng.linsight.api.endpoints import linsight as ep

    state: dict = {"enqueued": 0, "session": _session()}

    async def _get_by_id(linsight_session_version_id):
        return state["session"]

    async def _enqueue(session_model):
        state["enqueued"] += 1

    monkeypatch.setattr(ep.LinsightSessionVersionDao, "get_by_id", AsyncMock(side_effect=_get_by_id))
    monkeypatch.setattr(ep.MessageSessionDao, "touch_session", AsyncMock())
    monkeypatch.setattr(ep.linsight_execute_utils, "enqueue_session_for_execution", _enqueue)
    monkeypatch.setattr(ep.linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    return ep, state


async def test_start_execute_enqueues_a_pending_session(endpoint_env):
    ep, state = endpoint_env
    login_user = SimpleNamespace(user_id=1)

    resp = await ep.start_execute(linsight_session_version_id="sv-1", login_user=login_user)

    assert resp.status_code == 200
    assert state["enqueued"] == 1


async def test_start_execute_on_a_running_session_is_a_successful_no_op(endpoint_env):
    """The regression: server-side enqueue means the worker often picks the
    session up BEFORE the client's start-execute lands. Answering with an error
    made the UI show a running task as failed."""
    ep, state = endpoint_env
    state["session"] = _session(status=SessionVersionStatusEnum.IN_PROGRESS)
    login_user = SimpleNamespace(user_id=1)

    resp = await ep.start_execute(linsight_session_version_id="sv-1", login_user=login_user)

    assert resp.status_code == 200
    # Must NOT enqueue a second time — the run is already under way.
    assert state["enqueued"] == 0


@pytest.mark.parametrize(
    "status",
    [SessionVersionStatusEnum.COMPLETED, SessionVersionStatusEnum.TERMINATED],
)
async def test_start_execute_still_refuses_a_finished_session(endpoint_env, status):
    ep, state = endpoint_env
    state["session"] = _session(status=status)
    login_user = SimpleNamespace(user_id=1)

    resp = await ep.start_execute(linsight_session_version_id="sv-1", login_user=login_user)

    assert resp.status_code != 200
    assert state["enqueued"] == 0


async def test_start_execute_rejects_another_users_session(endpoint_env):
    ep, state = endpoint_env
    state["session"] = _session(user_id=999)
    login_user = SimpleNamespace(user_id=1)

    resp = await ep.start_execute(linsight_session_version_id="sv-1", login_user=login_user)

    assert resp.status_code != 200
    assert state["enqueued"] == 0
