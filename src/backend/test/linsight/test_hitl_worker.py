"""F035 Track B — park-and-release HITL worker tests.

Covers the worker-side plumbing for LangGraph ``interrupt()`` park-and-release:

  TB-1  park-and-release closed loop (interrupt -> park -> resume enqueue ->
        worker pick-up -> Command(resume); park-period termination -> stale
        queue item discarded by non-terminal guard).
  TB-3  worker ``async_run`` recognises the JSON resume payload, performs the
        non-terminal DB guard before running, and routes resume vs. new task.
  TB-4  ``/workbench/user-input`` lpushes a head-of-queue resume payload.
  TB-5  queue position semantics: resume items are not counted in other users'
        queue position.

Redis is mocked (no real Redis / no fakeredis dependency). The checkpointer
is exercised conceptually via ``make_checkpointer`` being swappable for
``InMemorySaver`` in resume agent construction (TB-2).
"""

from __future__ import annotations

import asyncio
import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.linsight.worker import (
    LinsightQueue,
    ScheduleCenterProcess,
    encode_queue_item,
    parse_queue_item,
)


# ---------------------------------------------------------------------------
# Fake Redis backing a single list, mimicking RedisClient list semantics:
# rpush/lpush store pickled values, blpop/lpop/lrange unpickle.
# ---------------------------------------------------------------------------
class _FakeRedisList:
    def __init__(self):
        self.lists: dict[str, list] = {}

    async def arpush(self, key, value, expiration=3600):
        value = pickle.dumps(value) if not isinstance(value, bytes) else value
        self.lists.setdefault(key, []).append(value)

    async def alpush(self, key, value, expiration=3600):
        # NOTE: RedisClient.alpush does NOT pickle; callers must pass bytes.
        self.lists.setdefault(key, []).insert(0, value)

    async def ablpop(self, key, timeout=0):
        items = self.lists.get(key, [])
        if not items:
            return None
        raw = items.pop(0)
        return pickle.loads(raw) if raw else None

    async def alpop(self, key, count=None):
        items = self.lists.get(key, [])
        if not items:
            return None
        return items.pop(0)

    async def alrange(self, key, start=0, end=-1):
        items = self.lists.get(key, [])
        return [pickle.loads(v) for v in items if v is not None]

    async def allen(self, key):
        return len(self.lists.get(key, []))

    async def alrem(self, key, value):
        value = pickle.dumps(value) if not isinstance(value, bytes) else value
        items = self.lists.get(key, [])
        before = len(items)
        self.lists[key] = [v for v in items if v != value]
        return before - len(self.lists[key])


@pytest.fixture()
def fake_redis():
    return _FakeRedisList()


@pytest.fixture()
def queue(fake_redis):
    return LinsightQueue("queue", namespace="linsight", redis=fake_redis)


# ===========================================================================
# Payload encode / parse (TB-3 contract)
# ===========================================================================
def test_encode_queue_item_new_task():
    item = encode_queue_item("svid-1")
    assert item == {
        "session_version_id": "svid-1",
        "resume": False,
        "user_input": None,
        "continue_question": None,
    }


def test_encode_queue_item_resume():
    item = encode_queue_item("svid-1", resume=True, user_input="hello")
    assert item == {
        "session_version_id": "svid-1",
        "resume": True,
        "user_input": "hello",
        "continue_question": None,
    }


def test_parse_queue_item_legacy_string_is_new_task():
    # Backward compat: a bare session_version_id string == resume=False.
    parsed = parse_queue_item("svid-legacy")
    assert parsed["session_version_id"] == "svid-legacy"
    assert parsed["resume"] is False
    assert parsed["user_input"] is None


def test_parse_queue_item_dict_passthrough():
    parsed = parse_queue_item({"session_version_id": "svid-2", "resume": True, "user_input": "x"})
    assert parsed["session_version_id"] == "svid-2"
    assert parsed["resume"] is True
    assert parsed["user_input"] == "x"


# ===========================================================================
# LinsightQueue head-of-queue + position semantics (TB-5)
# ===========================================================================
async def test_put_head_jumps_queue(queue, fake_redis):
    await queue.put(encode_queue_item("a"))
    await queue.put(encode_queue_item("b"))
    await queue.put_head(encode_queue_item("resume-x", resume=True, user_input="go"))

    first = await queue.get_wait()
    assert first["session_version_id"] == "resume-x"
    assert first["resume"] is True


async def test_index_matches_by_session_version_id(queue):
    await queue.put(encode_queue_item("a"))
    await queue.put(encode_queue_item("b"))
    # index() addresses items by session_version_id, returning 1-based position.
    assert await queue.index("a") == 1
    assert await queue.index("b") == 2
    assert await queue.index("missing") == 0


async def test_index_skips_resume_items_in_position(queue):
    # A resume item at the head must NOT inflate other users' queue position.
    await queue.put(encode_queue_item("a"))
    await queue.put(encode_queue_item("b"))
    await queue.put_head(encode_queue_item("resume-x", resume=True, user_input="go"))

    # "a" is still position 1 among real queued (new) tasks despite the
    # resume item physically sitting at the head.
    assert await queue.index("a") == 1
    assert await queue.index("b") == 2
    # The resume item itself is not a queue position.
    assert await queue.index("resume-x") == 0


async def test_index_legacy_string_items(queue, fake_redis):
    # Pre-existing bare-string items still work.
    await fake_redis.arpush("linsight:queue", "legacy-1")
    await queue.put(encode_queue_item("b"))
    assert await queue.index("legacy-1") == 1
    assert await queue.index("b") == 2


async def test_remove_by_session_version_id(queue):
    await queue.put(encode_queue_item("a"))
    await queue.put(encode_queue_item("b"))
    await queue.remove("a")
    assert await queue.index("a") == 0
    assert await queue.index("b") == 1


# ===========================================================================
# Worker async_run: non-terminal guard + resume routing (TB-3 / TB-1)
# ===========================================================================
def _make_worker(queue, fake_redis):
    """Build a ScheduleCenterProcess wired for a single async_run iteration."""
    import asyncio

    worker = ScheduleCenterProcess()
    worker.queue = queue
    worker.max_concurrency = 5
    worker.semaphore = asyncio.Semaphore(5)
    node_manager = MagicMock()
    node_manager.node_id = "node-test"
    node_manager.register_task_ownership = AsyncMock()
    node_manager.release_task_ownership = AsyncMock()
    worker.node_manager = node_manager
    return worker


def _patch_session_status(status):
    """Patch LinsightSessionVersionDao.get_by_id to return a session of given status."""
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum

    session = MagicMock()
    session.status = status
    return patch(
        "bisheng.linsight.worker.LinsightSessionVersionDao.get_by_id",
        new=AsyncMock(return_value=session),
    ), SessionVersionStatusEnum


async def test_async_run_new_task_routes_to_async_run(queue, fake_redis):
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum

    worker = _make_worker(queue, fake_redis)
    await queue.put(encode_queue_item("svid-new"))

    captured = {}

    async def fake_async_run(self, svid):
        captured["new"] = svid

    async def fake_resume(self, svid, user_input=None):
        captured["resume"] = (svid, user_input)

    sess_patch, _ = _patch_session_status(SessionVersionStatusEnum.NOT_STARTED)
    with (
        sess_patch,
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_run", new=fake_async_run),
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_resume", new=fake_resume, create=True),
    ):
        spawned = await worker.process_one_item()
        # Let the spawned task coroutine run to completion.
        await asyncio.sleep(0)

    assert spawned is True
    assert captured.get("new") == "svid-new"
    assert "resume" not in captured


async def test_async_run_resume_task_routes_to_async_resume(queue, fake_redis):
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum

    worker = _make_worker(queue, fake_redis)
    await queue.put_head(encode_queue_item("svid-r", resume=True, user_input="user answer"))

    captured = {}

    async def fake_async_run(self, svid):
        captured["new"] = svid

    async def fake_resume(self, svid, user_input=None):
        captured["resume"] = (svid, user_input)

    sess_patch, _ = _patch_session_status(SessionVersionStatusEnum.IN_PROGRESS)
    with (
        sess_patch,
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_run", new=fake_async_run),
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_resume", new=fake_resume, create=True),
    ):
        spawned = await worker.process_one_item()
        # Let the spawned resume coroutine run to completion.
        await asyncio.sleep(0)

    assert spawned is True
    assert captured.get("resume") == ("svid-r", "user answer")
    assert "new" not in captured


async def test_async_run_terminal_session_discards_item(queue, fake_redis):
    """Park-period termination: stale resume item picked up while TERMINATED -> discarded."""
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum

    worker = _make_worker(queue, fake_redis)
    await queue.put_head(encode_queue_item("svid-dead", resume=True, user_input="late answer"))

    captured = {}

    async def fake_async_run(self, svid):
        captured["new"] = svid

    async def fake_resume(self, svid, user_input=None):
        captured["resume"] = (svid, user_input)

    sess_patch, _ = _patch_session_status(SessionVersionStatusEnum.TERMINATED)
    with (
        sess_patch,
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_run", new=fake_async_run),
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_resume", new=fake_resume, create=True),
    ):
        handled = await worker.process_one_item()

    # Terminal task must not be run by either path.
    assert "new" not in captured
    assert "resume" not in captured
    # Item was consumed (discarded), not left in queue.
    assert await queue.qsize() == 0
    assert handled is False


async def test_async_run_missing_session_discards_item(queue, fake_redis):
    worker = _make_worker(queue, fake_redis)
    await queue.put(encode_queue_item("svid-gone"))

    captured = {}

    async def fake_async_run(self, svid):
        captured["new"] = svid

    with (
        patch(
            "bisheng.linsight.worker.LinsightSessionVersionDao.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch("bisheng.linsight.worker.LinsightWorkflowTask.async_run", new=fake_async_run),
    ):
        handled = await worker.process_one_item()

    assert "new" not in captured
    assert handled is False


# ===========================================================================
# TB-2: resume agent construction uses make_checkpointer (InMemorySaver in test)
# ===========================================================================
async def test_async_resume_uses_checkpointer_and_command_resume():
    """_drive_resume feeds Command(resume) into astream on the same thread_id
    (design §4.4), reusing the Track-A astream + StreamEventMapper pipeline."""
    from langgraph.types import Command

    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    exec_task = LinsightWorkflowTask()
    exec_task.session_version_id = "svid-resume"

    resume_calls = {}

    # Fake agent whose astream records the input (expected Command(resume)) and
    # the thread_id it was driven on, then yields nothing (empty resume stream).
    fake_agent = MagicMock()

    async def fake_astream(stream_input, config=None, stream_mode=None, subgraphs=None):
        resume_calls["input"] = stream_input
        resume_calls["thread_id"] = config["configurable"]["thread_id"]
        if False:  # pragma: no cover - make this an async generator
            yield None

    fake_agent.astream = fake_astream

    session_model = MagicMock()
    session_model.id = "svid-resume"

    # Isolate the config infrastructure: _drive_resume only needs max_steps for the
    # recursion_limit. Without this, settings.get_linsight_conf() -> get_all_config()
    # reads the test-mocked redis cache and yaml.safe_load(<MagicMock>) treats the
    # mock as an infinite input stream — an unbounded loop that balloons memory.
    # (settings is a pydantic model, so patch the module-level reference, not the attr.)
    with patch("bisheng.linsight.domain.task_exec.settings") as mock_settings:
        mock_settings.get_linsight_conf.return_value = MagicMock(max_steps=200)
        # Drive the resume helper directly to assert the contract (thread_id reuse +
        # Command(resume)).
        await exec_task._drive_resume(fake_agent, session_model, "the answer")

    assert isinstance(resume_calls["input"], Command)
    assert resume_calls["input"].resume == "the answer"
    assert resume_calls["thread_id"] == "svid-resume"


# ===========================================================================
# TB-4: /workbench/user-input lpushes a head-of-queue resume payload (idempotent)
# ===========================================================================
def _build_session(user_id=1):
    session = MagicMock()
    session.user_id = user_id
    session.session_id = "sess-1"
    return session


def _build_task(status):
    task = MagicMock()
    task.status = status
    return task


async def _call_user_input(real_queue, existing_task_status):
    """Drive the user_input endpoint with collaborators mocked, sharing the
    given real LinsightQueue so we can inspect what was enqueued."""
    from bisheng.linsight.api.endpoints import linsight as ep
    from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum

    login_user = MagicMock()
    login_user.user_id = 1

    sm = MagicMock()
    sm.get_execution_task = AsyncMock(return_value=_build_task(existing_task_status))
    sm.set_user_input = AsyncMock()

    with (
        patch.object(
            ep.LinsightSessionVersionDao,
            "get_by_id",
            new=AsyncMock(return_value=_build_session(user_id=1)),
        ),
        patch.object(ep.MessageSessionDao, "touch_session", new=AsyncMock()),
        patch.object(ep, "LinsightStateMessageManager", return_value=sm),
        patch.object(ep.LinsightWorkbenchImpl, "human_participate_add_file", new=AsyncMock(return_value=None)),
        patch.object(ep, "get_redis_client", new=AsyncMock(return_value=None)),
        patch("bisheng.linsight.worker.LinsightQueue", return_value=real_queue),
    ):
        # ExecuteTaskStatusEnum imported in endpoint module must match.
        assert ep.ExecuteTaskStatusEnum is ExecuteTaskStatusEnum
        resp = await ep.user_input(
            session_version_id="svid-ep",
            linsight_execute_task_id="task-1",
            input_content="my answer",
            files=None,
            login_user=login_user,
        )
    return resp, sm


async def test_user_input_enqueues_resume_at_head(queue):
    from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum

    # Pre-existing new task ahead in queue.
    await queue.put(encode_queue_item("other"))

    _resp, sm = await _call_user_input(queue, existing_task_status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT)

    sm.set_user_input.assert_awaited_once()
    # Resume payload jumped to the head.
    head = await queue.get_wait()
    assert head["session_version_id"] == "svid-ep"
    assert head["resume"] is True
    assert head["user_input"] == "my answer"


async def test_user_input_idempotent_no_double_enqueue(queue):
    from bisheng.linsight.domain.models.linsight_execute_task import ExecuteTaskStatusEnum

    # Task already USER_INPUT_COMPLETED -> a resume payload was already enqueued
    # by the first submit; a second submit must NOT enqueue again.
    await _call_user_input(queue, existing_task_status=ExecuteTaskStatusEnum.USER_INPUT_COMPLETED)

    assert await queue.qsize() == 0
