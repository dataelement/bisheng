"""Unit tests for the worker's stranded-session safety net.

When a Linsight task dies without task_exec recording a terminal status, the
session row stays ``IN_PROGRESS`` and the frontend spins on it forever. That is
exactly what happened when a loguru ``exc_info=`` kwarg raised ``KeyError``
inside ``async_run``'s ``except`` clause, skipping ``_handle_execution_error``.

The net must be strictly subordinate to task_exec's own failure path: it only
writes when the session is still non-terminal, and it may never raise (it runs
from an asyncio done-callback).

``asyncio_mode = auto`` — async tests need no decorator.
"""

import asyncio
from types import SimpleNamespace

import pytest

from bisheng.linsight import worker as worker_mod
from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
from bisheng.linsight.worker import ScheduleCenterProcess


def make_proc():
    """A ScheduleCenterProcess without running Process.__init__ (unused here)."""
    proc = ScheduleCenterProcess.__new__(ScheduleCenterProcess)
    proc.semaphore = None
    proc.max_concurrency = 1
    return proc


class FakeDao:
    def __init__(self, session=None, fail_on_write=False):
        self.session = session
        self.written = []
        self.fail_on_write = fail_on_write

    async def get_by_id(self, session_version_id):
        return self.session

    async def insert_one(self, session):
        if self.fail_on_write:
            raise RuntimeError("db down")
        self.written.append(session)
        return session


def session_with(status):
    return SimpleNamespace(id="sv1", status=status, output_result=None)


async def drain_spawned_tasks():
    """Await the repair task handle_task_result spawned via create_task."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def patch_dao(monkeypatch):
    def _apply(dao):
        monkeypatch.setattr(worker_mod, "LinsightSessionVersionDao", dao)
        return dao

    return _apply


# --------------------------------------------------------------------------
# _force_fail_stranded_session
# --------------------------------------------------------------------------


async def test_stranded_in_progress_session_is_failed(patch_dao):
    dao = patch_dao(FakeDao(session_with(SessionVersionStatusEnum.IN_PROGRESS)))

    await make_proc()._force_fail_stranded_session("sv1", RuntimeError("boom"))

    assert len(dao.written) == 1
    written = dao.written[0]
    assert written.status == SessionVersionStatusEnum.FAILED
    assert "boom" in written.output_result["error_message"]
    assert written.output_result["error_type"]  # always renderable by the frontend


@pytest.mark.parametrize(
    "status",
    [
        SessionVersionStatusEnum.COMPLETED,
        SessionVersionStatusEnum.FAILED,
        SessionVersionStatusEnum.TERMINATED,
        SessionVersionStatusEnum.SOP_GENERATION_FAILED,
    ],
)
async def test_terminal_session_is_never_overwritten(patch_dao, status):
    """task_exec's own failure path is richer; the net must not clobber it."""
    dao = patch_dao(FakeDao(session_with(status)))

    await make_proc()._force_fail_stranded_session("sv1", RuntimeError("boom"))

    assert dao.written == []


async def test_missing_session_is_a_no_op(patch_dao):
    dao = patch_dao(FakeDao(None))
    await make_proc()._force_fail_stranded_session("gone", RuntimeError("boom"))
    assert dao.written == []


async def test_write_failure_never_escapes(patch_dao):
    """Runs from a done-callback: raising here would be an unretrievable crash."""
    patch_dao(FakeDao(session_with(SessionVersionStatusEnum.IN_PROGRESS), fail_on_write=True))
    await make_proc()._force_fail_stranded_session("sv1", RuntimeError("boom"))  # must not raise


async def test_classifier_failure_still_writes_terminal_status(patch_dao, monkeypatch):
    """Classification is a nicety; the terminal write is the whole point."""
    dao = patch_dao(FakeDao(session_with(SessionVersionStatusEnum.IN_PROGRESS)))
    import bisheng.common.services.llm_error_classifier as classifier

    calls = []

    def explode(_error):
        calls.append(_error)
        raise ValueError("classifier broke")

    monkeypatch.setattr(classifier, "classify_for_event", explode)

    await make_proc()._force_fail_stranded_session("sv1", RuntimeError("boom"))

    # Guard against a false green: prove the patched classifier really ran, so
    # "error_type == unknown" reflects the fallback and not a lucky real answer.
    assert len(calls) == 1
    assert len(dao.written) == 1
    assert dao.written[0].status == SessionVersionStatusEnum.FAILED
    assert dao.written[0].output_result["error_type"] == "unknown"
    assert dao.written[0].output_result["error_code"] is None


# --------------------------------------------------------------------------
# handle_task_result wiring
# --------------------------------------------------------------------------


async def test_failed_task_triggers_the_net(patch_dao):
    dao = patch_dao(FakeDao(session_with(SessionVersionStatusEnum.IN_PROGRESS)))

    async def boom():
        raise RuntimeError("task died")

    task = asyncio.create_task(boom())
    with pytest.raises(RuntimeError):
        await task

    make_proc().handle_task_result(task, session_version_id="sv1")
    await drain_spawned_tasks()

    assert len(dao.written) == 1
    assert dao.written[0].status == SessionVersionStatusEnum.FAILED


async def test_successful_task_does_not_trigger_the_net(patch_dao):
    dao = patch_dao(FakeDao(session_with(SessionVersionStatusEnum.IN_PROGRESS)))

    async def fine():
        return "ok"

    task = asyncio.create_task(fine())
    await task

    make_proc().handle_task_result(task, session_version_id="sv1")
    await drain_spawned_tasks()

    assert dao.written == []


async def test_parked_task_returning_normally_is_left_alone(patch_dao):
    """park-and-release: the coroutine returns while the session is WAITING."""
    dao = patch_dao(FakeDao(session_with(SessionVersionStatusEnum.WAITING_FOR_USER_INPUT)))

    async def parks():
        return None

    task = asyncio.create_task(parks())
    await task

    make_proc().handle_task_result(task, session_version_id="sv1")
    await drain_spawned_tasks()

    assert dao.written == []
