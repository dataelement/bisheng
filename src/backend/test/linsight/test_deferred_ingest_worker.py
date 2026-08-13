"""Worker side of the deferred attachment ingest: when it runs, and what it may cost.

Submit now parks the raw file refs in ``pending_files`` (see
``test_deferred_ingest.py`` for why) and the worker materializes them at the top
of the run. That moved a multi-minute, failure-prone step into the middle of the
execution lifecycle, which is where every constraint below comes from:

  * it runs INSIDE the restored tenant context and BEFORE anything reads
    ``files`` — the local prefetch, the code interpreter's ``os.walk`` snapshot,
    the 可用文件 pointer block, and WorkspaceBackend's ``read_file``, which can
    only serve ``workspace/{svid}/uploads/*`` once the ingest has PUT them;
  * the IN_PROGRESS claim moved ahead of it, so the duplicate queue item that
    server-side enqueue made routine (submit enqueues, the browser's
    start-execute lands anyway) cannot re-enter a batch already being parsed;
  * the DB write is followed by a Redis snapshot refresh, or the snapshot cached
    by that same IN_PROGRESS flip shadows the ingested files for the whole run;
  * one unreadable attachment costs its own entry (``valid=False``) and nothing
    more, but a SYSTEMIC failure fails the run — an agent answering a question
    about "the attached report" with no attachment is worse than an error;
  * a stop pressed inside that window wins, even though the very next statement
    of ``_execute_workflow`` writes IN_PROGRESS unconditionally.

External services are faked; no live middleware required.
"""

from __future__ import annotations

import asyncio
import copy
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.context.tenant import current_tenant_id
from bisheng.linsight.domain import task_exec as te
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.schemas.linsight_schema import SubmitFileSchema
from bisheng.linsight.domain.services import workbench_impl
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

TENANT_ID = 3


@pytest.fixture(autouse=True)
def _no_question_row_annotation(monkeypatch: pytest.MonkeyPatch):
    """Keep the post-ingest question-row back-fill off the DB.

    It is a real DAO round-trip on the success path; ``test_unified_task_turn_write``
    owns its behaviour. Here it would only be a connection error swallowed by the
    best-effort guard, plus the wait for it.
    """
    annotate = AsyncMock(return_value=True)
    monkeypatch.setattr(te.linsight_execute_utils, "annotate_task_user_turn_files", annotate)
    return annotate


class FakeMinio:
    def __init__(self) -> None:
        self.bucket = "bisheng"
        self.tmp_bucket = "tmp-dir"
        self.store: dict[tuple[str, str], bytes] = {}

    async def object_exists(self, bucket_name=None, object_name=None):
        return (bucket_name or self.bucket, object_name) in self.store

    async def copy_object(self, source_bucket=None, source_object=None, dest_bucket=None, dest_object=None):
        src = self.store.get((source_bucket or self.tmp_bucket, source_object), b"parsed-md")
        self.store[(dest_bucket or self.bucket, dest_object)] = src

    async def get_object(self, bucket_name=None, object_name=None):
        return self.store.get((bucket_name or self.bucket, object_name))

    async def put_object(self, *, bucket_name=None, object_name, file, **kwargs):
        self.store[(bucket_name or self.bucket, object_name)] = file if isinstance(file, bytes) else bytes(file)


class FakeStateManager:
    """Mirrors the three properties of the real manager this change depends on.

    ``set_session_version_info`` writes the DB row and THEN caches a snapshot;
    ``get_session_version_info`` answers from that snapshot and only falls back
    to the row when there is none (``state_message_manager.py``). Reproducing the
    order is the whole point — a test that reads back the live object would pass
    against a missing refresh.

    The third is ``insert_one``'s closing ``session.refresh()``: a column this
    worker did NOT assign is re-read from the row and lands back in the model, so
    a terminate written by the endpoint mid-ingest arrives in memory. A column it
    DID assign wins over the row instead — which is precisely how
    ``_execute_workflow``'s blind IN_PROGRESS write can undo that terminate.
    ``row_status`` is what an outside writer (the endpoint) pokes.
    """

    def __init__(self, session_model) -> None:
        self.db_row = session_model
        self.snapshot: dict | None = None
        self.steps: list = []
        self.messages: list = []
        self.row_status = session_model.status
        self._model_status = session_model.status

    async def set_session_version_info(self, session_model) -> None:
        if session_model.status == self._model_status:
            session_model.status = self.row_status
        else:
            self.row_status = session_model.status
        self._model_status = session_model.status
        self.db_row = session_model
        self.snapshot = copy.deepcopy(session_model.model_dump())

    async def get_session_version_info(self):
        if self.snapshot is None:
            return self.db_row
        return LinsightSessionVersion.model_validate(self.snapshot)

    async def add_execution_task_step(self, svid, step) -> None:
        self.steps.append(step)

    async def push_message(self, message) -> None:
        self.messages.append(message)


def _pending(file_id: str = "f1", name: str = "a.pdf") -> dict:
    return SubmitFileSchema(file_id=file_id, file_name=name, parsing_status="completed").model_dump()


def _daily_pending(file_id: str, name: str) -> dict:
    return SubmitFileSchema(
        file_id=file_id,
        file_name=name,
        parsing_status="completed",
        file_url=f"/tmp-dir/{file_id}.pdf?X-Amz-Algorithm=AWS4",
    ).model_dump()


def _session(pending: list[dict] | None, status=SessionVersionStatusEnum.NOT_STARTED) -> LinsightSessionVersion:
    return LinsightSessionVersion(
        id="svid1",
        session_id="chat1",
        user_id=7,
        question="总结下附件",
        status=status,
        tenant_id=TENANT_ID,
        pending_files=pending,
    )


def _task(session_model) -> tuple[LinsightWorkflowTask, FakeStateManager]:
    task = LinsightWorkflowTask()
    task.session_version_id = session_model.id
    state = FakeStateManager(session_model)
    task._state_manager = state
    return task, state


# ---------------------------------------------------------------------------
# Ordering inside the run
# ---------------------------------------------------------------------------
async def test_ingest_runs_in_tenant_context_before_anything_reads_the_files(monkeypatch: pytest.MonkeyPatch):
    """The ingest sits between the tenant restore and every reader of ``files``.

    Moving it later (or earlier, into the queue consumer) breaks two different
    things at once: the workspace PUTs and DB reads would run with no tenant
    bound, and the local prefetch / tool construction / pointer block would all
    snapshot an empty ``uploads/``.
    """
    session_model = _session([_pending()])
    task, state = _task(session_model)
    order: list[str] = []
    observed: dict = {}

    async def _fake_ingest(model, **kwargs):
        observed["tenant_id"] = current_tenant_id.get()
        observed["status"] = model.status
        order.append("ingest")
        model.files = [{"file_id": "f1", "valid": True}]
        model.pending_files = None
        return True

    async def _fake_init_dir(model):
        observed["files_at_prefetch"] = list(model.files or [])
        order.append("init_file_directory")
        return "/tmp/linsight-svid1"

    async def _fake_execute(model):
        order.append("execute_workflow")

    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    monkeypatch.setattr(te, "ensure_linsight_permission_runtime", AsyncMock(return_value={}))
    monkeypatch.setattr(LinsightWorkbenchImpl, "ingest_pending_files", _fake_ingest)
    task._ensure_session_pseudo_task = AsyncMock(side_effect=lambda _m: order.append("pseudo_task"))
    task._init_file_directory = _fake_init_dir
    task._execute_workflow = _fake_execute

    await task.async_run("svid1", tenant_id=TENANT_ID)

    assert order == ["pseudo_task", "ingest", "init_file_directory", "execute_workflow"]
    # The worker owns no request context, so a missing restore reads as None here.
    assert observed["tenant_id"] == TENANT_ID
    # The pseudo task row must already exist: the progress steps hang off it.
    assert observed["status"] == SessionVersionStatusEnum.IN_PROGRESS
    # Whatever runs next sees the materialized list, not the staging column.
    assert observed["files_at_prefetch"] == [{"file_id": "f1", "valid": True}]
    assert session_model.pending_files is None


async def test_worker_ingest_rebinds_files_so_the_next_reader_sees_them(monkeypatch: pytest.MonkeyPatch):
    """``files`` is replaced wholesale, never appended to in place: ``JsonType``
    has no ``MutableList`` wrapper, so an in-place mutation emits no UPDATE and
    the run would still be the only thing that ever saw the attachments."""
    session_model = _session([_pending("f1"), _pending("f2", "b.pdf")])
    # Anything already on the row (a HITL-added file, say) has to survive, which
    # is exactly the case an ``.extend()`` would look correct on in memory.
    session_model.files = [{"file_id": "old", "valid": True}]
    loaded_list = session_model.files
    processed = [{"file_id": "f1", "valid": True}, {"file_id": "f2", "valid": True}]
    monkeypatch.setattr(LinsightWorkbenchImpl, "_process_submitted_files", AsyncMock(return_value=processed))

    await _task(session_model)[0]._ingest_pending_attachments(session_model)

    assert [entry["file_id"] for entry in session_model.files] == ["old", "f1", "f2"]
    # A new list object, and the one SQLAlchemy loaded was never touched.
    assert session_model.files is not loaded_list
    assert loaded_list == [{"file_id": "old", "valid": True}]
    assert session_model.pending_files is None


async def test_ingested_files_are_not_shadowed_by_the_earlier_redis_snapshot():
    """``get_session_version_info`` reads Redis first, and the IN_PROGRESS flip
    already cached a snapshot carrying ``files=None``. Without a refresh right
    after the ingest, every reader for the rest of the run gets that stale
    snapshot and the task behaves as if nothing was ever uploaded."""
    session_model = _session([_pending()])
    task, state = _task(session_model)

    # The claim at the top of _managed_execution: this is what caches files=None.
    await task._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)
    assert (await state.get_session_version_info()).files is None

    with patch.object(
        LinsightWorkbenchImpl, "_process_submitted_files", new=AsyncMock(return_value=[{"file_id": "f1"}])
    ):
        await task._ingest_pending_attachments(session_model)

    cached = await state.get_session_version_info()
    assert cached.files == [{"file_id": "f1"}]
    assert cached.pending_files is None


# ---------------------------------------------------------------------------
# Degradation: a bad attachment costs its own entry, nothing more
# ---------------------------------------------------------------------------
async def test_one_unreadable_attachment_does_not_fail_the_session(monkeypatch: pytest.MonkeyPatch):
    """A ten-file task must not die because one file's download failed. The bad
    entry is marked ``valid=False`` for the chip, the others ingest normally, and
    the session status is left exactly where the run put it."""
    session_model = _session([_daily_pending("good", "ok.pdf"), _daily_pending("bad", "broken.pdf")])
    task, state = _task(session_model)
    await task._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

    class _Doc:
        page_content = "# parsed\nbody\n"

    class _OkPipeline:
        def __init__(self, *args, **kwargs):
            pass

        async def arun(self):
            return SimpleNamespace(documents=[_Doc()])

    async def _download(url, *args, **kwargs):
        if "bad" in url:
            raise ValueError("minio download boom")
        return ("/tmp/ok.pdf", "ok.pdf")

    with (
        patch.object(workbench_impl, "get_minio_storage", new=AsyncMock(return_value=FakeMinio())),
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=AsyncMock()),
        patch("bisheng.core.cache.utils.async_file_download", new=_download),
        patch("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _OkPipeline),
    ):
        await task._ingest_pending_attachments(session_model)

    by_id = {entry["file_id"]: entry for entry in session_model.files}
    assert by_id["good"]["valid"] is True
    assert by_id["bad"]["valid"] is False
    assert "boom" in by_id["bad"]["error_message"]
    assert session_model.pending_files is None
    assert session_model.status == SessionVersionStatusEnum.IN_PROGRESS
    assert (await state.get_session_version_info()).status == SessionVersionStatusEnum.IN_PROGRESS


async def test_a_systemic_ingest_failure_fails_the_run_instead_of_answering_blind(
    monkeypatch: pytest.MonkeyPatch,
):
    """Per-file failures never reach here — ``_process_submitted_files`` degrades
    them. What does reach here is systemic (storage unreachable, a malformed ref),
    and swallowing it leaves ``files`` empty while the run carries on: the model
    is asked about "the attached report" with no attachment and answers anyway,
    confidently, about a document it never saw. Fail loudly instead, and leave
    ``pending_files`` for /workbench/continue to retry.
    """
    session_model = _session([_pending()])
    task, state = _task(session_model)
    monkeypatch.setattr(
        LinsightWorkbenchImpl, "ingest_pending_files", AsyncMock(side_effect=RuntimeError("minio down"))
    )

    with pytest.raises(te.TaskExecutionError, match="ingest uploaded attachments"):
        await task._ingest_pending_attachments(session_model)

    assert session_model.files is None
    assert session_model.pending_files == [_pending()]
    # And it is visible in the timeline, not only in the worker log. Asserted on
    # the structured payload rather than the label: the row carries no prose at
    # all, because the copy is the client's (a backend-formatted string would show
    # Chinese to a Japanese user and would be frozen wrong in persisted history).
    assert state.steps and state.steps[-1].status == "end"
    assert state.steps[-1].name == te._INGEST_STEP_NAME
    assert state.steps[-1].extra_info["ingest_progress"]["phase"] == "failed"
    assert "minio down" in state.steps[-1].output


async def test_a_failed_ingest_reaches_the_users_error_instead_of_the_stranded_net(
    monkeypatch: pytest.MonkeyPatch,
):
    """``TaskExecutionError`` out of ``_managed_execution`` is the controlled
    route: ``async_run`` hands it to ``_handle_execution_error``, which writes a
    FAILED session carrying the reason. The alternative is the startup sweep's
    "Worker node crash detected", minutes later and about the wrong thing."""
    session_model = _session([_pending()])
    task, state = _task(session_model)
    failures: list[str] = []

    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    monkeypatch.setattr(te, "ensure_linsight_permission_runtime", AsyncMock(return_value={}))
    monkeypatch.setattr(
        LinsightWorkbenchImpl, "ingest_pending_files", AsyncMock(side_effect=RuntimeError("minio down"))
    )
    task._ensure_session_pseudo_task = AsyncMock()
    task._init_file_directory = AsyncMock(side_effect=AssertionError("prefetch must not run without the files"))
    task._execute_workflow = AsyncMock(side_effect=AssertionError("the agent must not run without the files"))
    task._handle_execution_error = AsyncMock(side_effect=lambda err: failures.append(str(err)))

    await task.async_run("svid1", tenant_id=TENANT_ID)

    assert failures and "minio down" in failures[0]


# ---------------------------------------------------------------------------
# Double pick-up and termination
# ---------------------------------------------------------------------------
async def test_a_duplicate_queue_item_cannot_re_enter_the_ingest(monkeypatch: pytest.MonkeyPatch):
    """Two queue items for one svid is the NORMAL case since submit enqueues
    server-side and the browser's start-execute still lands. The IN_PROGRESS
    claim therefore had to move ahead of the ingest: with the claim still inside
    ``_execute_workflow``, the second worker walked straight into the same batch
    and parsed every attachment a second time, on top of the first.
    """
    session_model = _session([_pending()])
    first, state = _task(session_model)
    second, _ = _task(session_model)
    second._state_manager = state
    ingesting = asyncio.Event()
    release = asyncio.Event()
    entered: list[str] = []

    async def _slow_ingest(model, **kwargs):
        entered.append(model.id)
        ingesting.set()
        # Bounded on purpose: if the claim ever slips back behind the ingest the
        # second worker lands here too, and an unbounded wait would hang the
        # suite instead of failing the assertion below.
        with suppress(TimeoutError):
            await asyncio.wait_for(release.wait(), timeout=2)
        model.files = [{"file_id": "f1"}]
        model.pending_files = None
        return True

    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    # _managed_execution mints its own state manager, so both workers must be
    # given the shared fake or they talk to a real Redis.
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    monkeypatch.setattr(LinsightWorkbenchImpl, "ingest_pending_files", _slow_ingest)
    for task in (first, second):
        task._ensure_session_pseudo_task = AsyncMock()
        task._init_file_directory = AsyncMock(return_value="/tmp/linsight-svid1")

    async def _run(task):
        async with task._managed_execution():
            pass

    running = asyncio.create_task(_run(first))
    await asyncio.wait_for(ingesting.wait(), timeout=5)

    with pytest.raises(te.TaskAlreadyInProgressError):
        await _run(second)

    release.set()
    await asyncio.wait_for(running, timeout=5)

    assert entered == ["svid1"]


async def test_a_stop_request_lands_between_files_instead_of_after_the_batch(monkeypatch: pytest.MonkeyPatch):
    """Stop used to be answerable within a step; a deferred ingest can hold the
    task for minutes before the agent ever starts. The abort flag is polled
    before each file so the user's stop costs at most one file, not the batch."""
    session_model = _session([_pending("f1", "a.pdf"), _pending("f2", "b.pdf"), _pending("f3", "c.pdf")])
    task, _state = _task(session_model)
    ingested: list[str] = []

    async def _fake_ingest_one(cls, submit_file, *args, **kwargs):
        ingested.append(submit_file.file_id)
        # The user hits stop while the first file is being parsed.
        task._is_terminated = True
        return {"file_id": submit_file.file_id, "valid": True}

    monkeypatch.setattr(LinsightWorkbenchImpl, "_ingest_one_file", classmethod(_fake_ingest_one))
    monkeypatch.setattr(LinsightWorkbenchImpl, "_get_redis", AsyncMock(return_value=AsyncMock(amget=AsyncMock())))
    monkeypatch.setattr(workbench_impl, "get_minio_storage", AsyncMock(return_value=MagicMock()))

    await task._ingest_pending_attachments(session_model)

    assert ingested == ["f1"]
    assert [entry["file_id"] for entry in session_model.files] == ["f1"]


async def test_a_stop_during_the_ingest_is_not_undone_by_the_run(monkeypatch: pytest.MonkeyPatch):
    """The stop has to survive the very next statement of the run.

    ``_execute_workflow`` opens with an UNCONDITIONAL IN_PROGRESS write, and the
    ingest's own DB write refreshes the model straight from the row — so a
    terminate that landed mid-ingest arrives in memory just in time to be
    overwritten. Nothing writes a terminal status after that: the session shows
    as running forever and pressing 停止 again is the only way out, if it wins the
    race at all. ``_managed_execution`` therefore re-reads the authoritative
    status once the ingest returns and bails before any of that.
    """
    session_model = _session([_pending()])
    task, state = _task(session_model)
    ran: list[str] = []

    async def _terminating_ingest(model, **kwargs):
        # What terminate_execute does: write TERMINATED straight to the row while
        # this worker is still parsing and has not polled the monitor yet.
        state.row_status = SessionVersionStatusEnum.TERMINATED
        model.files = [{"file_id": "f1", "valid": True}]
        model.pending_files = None
        return True

    async def _blind_claim(model):
        # The first statement of the real _execute_workflow, verbatim in effect.
        ran.append("execute_workflow")
        await task._update_session_status(model, SessionVersionStatusEnum.IN_PROGRESS)

    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    monkeypatch.setattr(te, "ensure_linsight_permission_runtime", AsyncMock(return_value={}))
    monkeypatch.setattr(LinsightWorkbenchImpl, "ingest_pending_files", _terminating_ingest)
    task._ensure_session_pseudo_task = AsyncMock()
    task._init_file_directory = AsyncMock(return_value="/tmp/linsight-svid1")
    task._execute_workflow = _blind_claim

    # async_run swallows UserTerminationError by design (the endpoint already
    # wrote the terminal state); the assertion is that nothing resurrected it.
    await task.async_run("svid1", tenant_id=TENANT_ID)

    assert ran == []
    assert (await state.get_session_version_info()).status == SessionVersionStatusEnum.TERMINATED


async def test_resume_ingests_a_batch_a_crashed_worker_left_behind(monkeypatch: pytest.MonkeyPatch):
    """The resume/continue path is the column's only second chance.

    A worker killed mid-ingest leaves the row IN_PROGRESS with ``pending_files``
    intact; the startup sweep then force-writes FAILED, and FAILED is one of the
    two statuses /workbench/continue accepts. Without an ingest here the
    follow-up turn runs with no attachments at all and the refs are stranded on
    the row forever.
    """
    session_model = _session([_pending()], status=SessionVersionStatusEnum.FAILED)
    task, state = _task(session_model)
    order: list[str] = []

    async def _fake_ingest(model, **kwargs):
        order.append("ingest")
        model.files = [{"file_id": "f1", "valid": True}]
        model.pending_files = None
        return True

    async def _fake_init_dir(model):
        order.append("init_file_directory")
        return "/tmp/linsight-svid1"

    monkeypatch.setattr(te.LinsightSessionVersionDao, "get_by_id", AsyncMock(return_value=session_model))
    monkeypatch.setattr(te, "LinsightStateMessageManager", lambda _svid: state)
    monkeypatch.setattr(LinsightWorkbenchImpl, "ingest_pending_files", _fake_ingest)
    task._start_termination_monitor = AsyncMock()
    task._ensure_session_pseudo_task = AsyncMock()
    task._init_file_directory = _fake_init_dir

    async with task._managed_resume() as resumed:
        pass

    # Still ahead of the local prefetch, same as the fresh path.
    assert order == ["ingest", "init_file_directory"]
    assert resumed.files == [{"file_id": "f1", "valid": True}]
    assert resumed.pending_files is None
