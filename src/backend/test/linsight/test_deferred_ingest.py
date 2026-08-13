"""Attachment ingestion left the submit request; only the metadata gate stayed.

Parsing one attachment runs the full ETL (600s timeout per file). A production
task with 12 PDFs spent 19 minutes inside ``submit_user_question`` — trace
8467e765, 12:37→12:56, the whole window inside ``knowledge.rag.pipeline`` — and
nginx cut the HTTP request at 300s, so the browser never got the handoff and the
session sat at NOT_STARTED with nobody to pick it up. Submit now parks the raw
refs in ``pending_files`` and the worker materializes them before the run.

What these tests hold in place, request side:

  * submit touches NO storage — no MinIO, no Redis, no ETL — and ``files`` stays
    None, because its contract ("ingested and usable") is what every downstream
    reader depends on;
  * the pure-metadata checks did NOT move: 11021/11022/11023 and the "file still
    parsing" rejection are what the frontend branches on, and minutes later they
    would only be a generic task failure;
  * ``ingest_pending_files`` REBINDS ``files`` — ``JsonType`` carries no
    ``MutableList`` wrapper, so an in-place mutation emits no UPDATE and the
    whole ingest evaporates on commit;
  * ``amget`` drops misses, so its result is never paired positionally.

Worker-side ordering / degradation lives in ``test_deferred_ingest_worker.py``.
External services are faked; no live middleware required.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.common.errcode.linsight import (
    LinsightFolderDepthExceededError,
    LinsightFolderFileCountExceededError,
    LinsightFolderTotalSizeExceededError,
)
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao
from bisheng.linsight.domain.schemas.linsight_schema import LinsightQuestionSubmitSchema, SubmitFileSchema
from bisheng.linsight.domain.services import workbench_impl
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

# The tenant the fake DAO stamps on insert, standing in for the multi-tenant
# listener: the queue item is the worker's ONLY source of tenant context.
FAKE_TENANT_ID = 42


class FakeMinio:
    """Object store with the surface ingestion uses — and a readable ``store``."""

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


def _legacy_file(file_id: str = "f1", name: str = "a.pdf", status: str = "completed") -> SubmitFileSchema:
    """A linsight-pipeline upload: its parsed markdown is looked up in Redis."""
    return SubmitFileSchema(file_id=file_id, file_name=name, parsing_status=status)


def _daily_file(file_id: str = "d1", name: str = "report.pdf") -> SubmitFileSchema:
    """A daily-bucket upload: this is the one that drags the whole ETL in."""
    return SubmitFileSchema(
        file_id=file_id,
        file_name=name,
        parsing_status="completed",
        file_url=f"/tmp-dir/{file_id}.pdf?X-Amz-Algorithm=AWS4",
    )


def _temp_info(file_id: str, name: str) -> dict:
    return {
        "file_id": file_id,
        "original_filename": name,
        "parsing_status": "completed",
        "markdown_filename": f"{file_id}.md",
        "markdown_file_path": f"{file_id}.md",
    }


@pytest.fixture
def submit_env(monkeypatch: pytest.MonkeyPatch):
    """Isolate submit from the DB and wire up probes on every ingestion door.

    The probes are the assertion surface: a regression that puts parsing back in
    the request shows up as bytes in ``minio.store``, a Redis read, a download or
    a constructed ``TempFilePipeline`` — not as a mock call count on a seam that
    may well have been renamed by then.
    """
    env: dict = {"messages": [], "redis_reads": [], "downloads": [], "pipelines": []}
    minio = FakeMinio()
    env["minio"] = minio

    async def _fake_insert_session(_cls, data: MessageSession):
        env["session"] = data
        return data

    async def _fake_insert_version(_cls, data):
        # The tenant listener stamps this on the real INSERT; the worker reads it
        # back off the queue item, so the fake has to stamp it too.
        data.tenant_id = FAKE_TENANT_ID
        env["version"] = data
        return data

    async def _fake_insert_message(_cls, data: ChatMessage):
        env["messages"].append(data)
        return data

    fake_redis = AsyncMock()

    async def _record_amget(keys):
        env["redis_reads"].extend(keys)
        return []

    async def _record_aget(key):
        env["redis_reads"].append(key)
        return None

    fake_redis.amget = AsyncMock(side_effect=_record_amget)
    fake_redis.aget = AsyncMock(side_effect=_record_aget)
    env["redis"] = fake_redis

    async def _record_download(url, *args, **kwargs):
        env["downloads"].append(url)
        return ("/tmp/never-used", "never-used")

    class _RecordingPipeline:
        def __init__(self, *args, **kwargs):
            env["pipelines"].append(kwargs.get("file_name"))

        async def arun(self):
            return SimpleNamespace(documents=[])

    monkeypatch.setattr(MessageSessionDao, "async_insert_one", classmethod(_fake_insert_session))
    monkeypatch.setattr(LinsightSessionVersionDao, "insert_one", classmethod(_fake_insert_version))
    monkeypatch.setattr(ChatMessageDao, "ainsert_one", classmethod(_fake_insert_message))
    monkeypatch.setattr(workbench_impl.telemetry_service, "log_event", AsyncMock(return_value=None))
    # Promoting the display attachments (temp bucket -> permanent) is a cheap
    # copy that has always been in the request; stub it so the storage probes
    # only ever see ingestion traffic.
    monkeypatch.setattr(workbench_impl, "promote_chat_attachments", AsyncMock(side_effect=lambda files, _uid: files))
    monkeypatch.setattr(workbench_impl, "get_minio_storage", AsyncMock(return_value=minio))
    monkeypatch.setattr(LinsightWorkbenchImpl, "_get_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr("bisheng.core.cache.utils.async_file_download", _record_download)
    monkeypatch.setattr("bisheng.knowledge.rag.temp_file_pipeline.TempFilePipeline", _RecordingPipeline)
    return env


def _login_user(user_id: int = 7):
    login_user = MagicMock()
    login_user.user_id = user_id
    return login_user


def _assert_storage_untouched(env: dict) -> None:
    assert env["minio"].store == {}
    assert env["redis_reads"] == []
    assert env["downloads"] == []
    assert env["pipelines"] == []


@pytest.fixture
def queue_env(monkeypatch: pytest.MonkeyPatch):
    """Stub the worker queue behind the unified task-mode entry; hand back ``put``."""
    from bisheng.workstation.domain.services import chat_service

    put = AsyncMock()
    # LinsightQueue / encode_queue_item are imported function-locally from
    # bisheng.linsight.worker; a stub module keeps the heavy worker import chain
    # out of the test, and it must export BOTH names or the ImportError escapes.
    fake_worker = ModuleType("bisheng.linsight.worker")
    fake_worker.LinsightQueue = lambda *a, **k: SimpleNamespace(put=put)
    fake_worker.encode_queue_item = lambda session_version_id, **kwargs: {
        "session_version_id": session_version_id,
        **kwargs,
    }
    monkeypatch.setitem(sys.modules, "bisheng.linsight.worker", fake_worker)
    # Enqueueing lives in linsight_execute_utils, so the Redis stub belongs on
    # THAT module — stubbing only the caller's namespace lets a real client
    # through and the call reaches the DB.
    monkeypatch.setattr(linsight_execute_utils, "get_redis_client", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(linsight_execute_utils, "persist_task_turn_message", AsyncMock())
    monkeypatch.setattr(chat_service.LLMService, "get_bisheng_llm", AsyncMock(return_value=MagicMock()))
    return chat_service, put


def _task_mode_request(files: list[dict] | None) -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="1755000000",
        model="m1",
        text="总结下附件",
        task_mode=True,
        files=files,
    )


# ---------------------------------------------------------------------------
# Submit: park the refs, touch nothing
# ---------------------------------------------------------------------------
async def test_submit_parks_the_refs_and_does_no_ingestion_io(submit_env):
    """The 19-minute submit: three attachments must cost zero storage round-trips.

    Both upload shapes are present because they fail differently — a daily file
    drags in ``TempFilePipeline``, a legacy one a Redis lookup plus a bucket copy.
    """
    files = [_legacy_file("f1", "a.pdf"), _legacy_file("f2", "b.pdf"), _daily_file("d1", "c.pdf")]
    submit_obj = LinsightQuestionSubmitSchema(question="总结下附件", files=files)

    await LinsightWorkbenchImpl.submit_user_question(submit_obj, _login_user())

    _assert_storage_untouched(submit_env)
    version = submit_env["version"]
    assert version.files is None
    assert [item["file_id"] for item in version.pending_files] == ["f1", "f2", "d1"]


async def test_submit_without_files_parks_nothing(submit_env):
    """An empty batch must leave the staging column NULL, not an empty list — a
    ``[]`` there would send the worker into the ingest path for every text-only
    task ever submitted."""
    await LinsightWorkbenchImpl.submit_user_question(LinsightQuestionSubmitSchema(question="写个周报"), _login_user())

    version = submit_env["version"]
    assert version.pending_files is None
    assert version.files is None


async def test_submit_with_defer_disabled_still_ingests_inline(submit_env, monkeypatch: pytest.MonkeyPatch):
    """The inline path stays reachable for a caller that needs the bytes now."""
    process = AsyncMock(return_value=[{"file_id": "f1", "valid": True}])
    monkeypatch.setattr(LinsightWorkbenchImpl, "_process_submitted_files", process)
    submit_obj = LinsightQuestionSubmitSchema(question="总结下附件", files=[_legacy_file()])

    await LinsightWorkbenchImpl.submit_user_question(submit_obj, _login_user(), defer_ingest=False)

    process.assert_awaited_once()
    version = submit_env["version"]
    assert version.files == [{"file_id": "f1", "valid": True}]
    assert version.pending_files is None


async def test_task_mode_submit_enqueues_once_carrying_the_tenant(submit_env, queue_env):
    """End of the request: the row is parked and handed to the worker exactly once.

    The queue item is the worker's only source of tenant context (it runs outside
    any request), and the enqueue is what makes the run independent of the
    browser ever coming back — the two halves that together replace the old
    "parse inline, then wait for start-execute".
    """
    chat_service, put = queue_env
    data = _task_mode_request(
        [{"file_id": "d1", "filename": "report.pdf", "filepath": "/tmp-dir/d1.pdf?X-Amz-Algorithm=AWS4"}]
    )

    await chat_service._task_mode_stream_completion(MagicMock(), data, _login_user())

    _assert_storage_untouched(submit_env)
    assert submit_env["version"].files is None
    assert submit_env["version"].pending_files
    put.assert_awaited_once()
    queued = put.await_args.kwargs["data"]
    assert queued["session_version_id"] == submit_env["version"].id
    assert queued["tenant_id"] == FAKE_TENANT_ID


# ---------------------------------------------------------------------------
# Validation: the metadata gate did NOT move
# ---------------------------------------------------------------------------
async def test_submit_still_rejects_a_file_that_is_still_parsing(submit_env):
    """Deferring the BYTES must not defer this: the request is where the user is
    still watching, and the worker could only report it as a dead task."""
    submit_obj = LinsightQuestionSubmitSchema(question="q", files=[_legacy_file(status="parsing")])

    with pytest.raises(LinsightWorkbenchImpl.LinsightError):
        await LinsightWorkbenchImpl.submit_user_question(submit_obj, _login_user())

    _assert_storage_untouched(submit_env)
    assert "version" not in submit_env


def _folder_batch(kind: str) -> list[SubmitFileSchema]:
    if kind == "count":
        return [
            SubmitFileSchema(
                file_id=f"f{i}", file_name=f"{i}.pdf", parsing_status="completed", relative_path=f"docs/{i}.pdf"
            )
            for i in range(LinsightWorkbenchImpl._FOLDER_MAX_FILES + 1)
        ]
    if kind == "size":
        half = LinsightWorkbenchImpl._FOLDER_MAX_TOTAL_BYTES // 2 + 1
        return [
            SubmitFileSchema(
                file_id=f"f{i}",
                file_name=f"{i}.pdf",
                parsing_status="completed",
                relative_path=f"docs/{i}.pdf",
                size=half,
            )
            for i in range(2)
        ]
    deep = "/".join(f"d{i}" for i in range(LinsightWorkbenchImpl._FOLDER_MAX_DEPTH + 1)) + "/f.pdf"
    return [SubmitFileSchema(file_id="f1", file_name="f.pdf", parsing_status="completed", relative_path=deep)]


@pytest.mark.parametrize(
    ("kind", "error", "code"),
    [
        ("count", LinsightFolderFileCountExceededError, 11021),
        ("size", LinsightFolderTotalSizeExceededError, 11022),
        ("depth", LinsightFolderDepthExceededError, 11023),
    ],
)
async def test_folder_limits_raise_their_typed_code_before_any_byte_moves(submit_env, kind, error, code):
    """These three codes have frontend copy hanging off them. Sunk into the
    worker they would surface as "task failed" minutes after the user dropped the
    folder, with nothing to retry against."""
    submit_obj = LinsightQuestionSubmitSchema(question="q", files=_folder_batch(kind))

    with pytest.raises(error) as exc_info:
        await LinsightWorkbenchImpl.submit_user_question(submit_obj, _login_user())

    assert exc_info.value.Code == code
    _assert_storage_untouched(submit_env)
    assert "version" not in submit_env


async def test_a_rejected_batch_never_reaches_the_worker_queue(submit_env, queue_env):
    """A rejected submit must leave nothing behind for the worker to pick up.

    Enqueueing is server-side now, so "the request failed" and "the task never
    runs" are no longer the same statement: a queue item written next to a
    refused batch would be a ghost task nobody asked for, and the user has
    already been told the upload was rejected.
    """
    chat_service, put = queue_env
    over_count = [
        {"file_id": f"f{i}", "filename": f"{i}.pdf", "relative_path": f"docs/{i}.pdf"}
        for i in range(LinsightWorkbenchImpl._FOLDER_MAX_FILES + 1)
    ]

    with pytest.raises(LinsightFolderFileCountExceededError):
        await chat_service._task_mode_stream_completion(MagicMock(), _task_mode_request(over_count), _login_user())

    put.assert_not_awaited()
    _assert_storage_untouched(submit_env)
    assert "version" not in submit_env


# ---------------------------------------------------------------------------
# ingest_pending_files: the worker-side entry point
# ---------------------------------------------------------------------------
async def test_ingest_rebinds_files_and_clears_pending(monkeypatch: pytest.MonkeyPatch):
    """Whole-attribute rebind, deliberately: ``JsonType`` is a bare JSON column
    with no ``MutableList`` wrapper anywhere in this repo, so a ``.extend()`` on
    the loaded list leaves SQLAlchemy with no attribute change and the UPDATE is
    never emitted — the ingest would vanish at commit."""
    processed = [{"file_id": "f1", "valid": True}]
    monkeypatch.setattr(LinsightWorkbenchImpl, "_process_submitted_files", AsyncMock(return_value=processed))
    session_model = SimpleNamespace(id="svid1", user_id=7, files=None, pending_files=[_legacy_file().model_dump()])

    assert await LinsightWorkbenchImpl.ingest_pending_files(session_model) is True
    assert session_model.files == processed
    assert session_model.pending_files is None


async def test_ingest_without_pending_files_is_a_no_op():
    """Every non-deferred session (resume, continue, a pre-upgrade row) reaches
    this with pending_files NULL — it must not clear or re-write ``files``."""
    session_model = SimpleNamespace(id="svid1", user_id=7, files=[{"file_id": "old"}], pending_files=None)

    assert await LinsightWorkbenchImpl.ingest_pending_files(session_model) is False
    assert session_model.files == [{"file_id": "old"}]


async def test_ingest_reports_progress_per_file_and_honours_abort(monkeypatch: pytest.MonkeyPatch):
    """A stop request must not have to wait out a 600s-per-file batch, and the
    timeline needs a frame per file or the panel sits empty for the whole ingest."""
    seen: list[str] = []
    progress: list[tuple[int, int, str]] = []

    async def _fake_ingest_one(cls, submit_file, *args, **kwargs):
        seen.append(submit_file.file_id)
        return {"file_id": submit_file.file_id}

    async def _on_progress(done, total, name):
        progress.append((done, total, name))

    monkeypatch.setattr(LinsightWorkbenchImpl, "_ingest_one_file", classmethod(_fake_ingest_one))
    monkeypatch.setattr(LinsightWorkbenchImpl, "_get_redis", AsyncMock(return_value=AsyncMock(amget=AsyncMock())))
    monkeypatch.setattr(workbench_impl, "get_minio_storage", AsyncMock(return_value=MagicMock()))

    result = await LinsightWorkbenchImpl._process_submitted_files(
        [_legacy_file("f1", "a.pdf"), _legacy_file("f2", "b.pdf"), _legacy_file("f3", "c.pdf")],
        "svid1",
        7,
        on_progress=_on_progress,
        should_abort=lambda: len(seen) >= 2,
    )

    assert seen == ["f1", "f2"]
    assert [entry["file_id"] for entry in result] == ["f1", "f2"]
    assert progress == [(1, 3, "a.pdf"), (2, 3, "b.pdf")]


async def test_one_file_blowing_up_costs_only_that_file(monkeypatch: pytest.MonkeyPatch):
    """The linsight branch makes bare ``copy_object`` calls with no guard of its
    own, so one MinIO hiccup used to abandon every remaining attachment. In the
    request that surfaced as a failed submit; from the worker it is silent — the
    run simply proceeds with fewer files than the user attached, and nothing says
    so. Degrade the one file, keep the batch."""
    seen: list[str] = []

    async def _flaky_ingest_one(cls, submit_file, *args, **kwargs):
        seen.append(submit_file.file_id)
        if submit_file.file_id == "f2":
            raise RuntimeError("S3 connection reset")
        return {"file_id": submit_file.file_id, "valid": True}

    monkeypatch.setattr(LinsightWorkbenchImpl, "_ingest_one_file", classmethod(_flaky_ingest_one))
    monkeypatch.setattr(LinsightWorkbenchImpl, "_get_redis", AsyncMock(return_value=AsyncMock(amget=AsyncMock())))
    monkeypatch.setattr(workbench_impl, "get_minio_storage", AsyncMock(return_value=MagicMock()))

    result = await LinsightWorkbenchImpl._process_submitted_files(
        [_legacy_file("f1", "a.pdf"), _legacy_file("f2", "b.pdf"), _legacy_file("f3", "c.pdf")], "svid1", 7
    )

    assert seen == ["f1", "f2", "f3"]
    by_id = {entry["file_id"]: entry for entry in result}
    assert by_id["f1"]["valid"] is True
    assert by_id["f3"]["valid"] is True
    assert by_id["f2"]["valid"] is False
    assert "S3 connection reset" in by_id["f2"]["error_message"]


async def test_the_staging_column_never_leaves_the_server(submit_env):
    """``pending_files`` carries the presigned temp-bucket link the browser
    uploaded with (7-day validity), and the version list is reachable through a
    share link — so a plain ``model_dump`` would hand a share recipient direct
    URLs to the submitter's originals. Both public read surfaces go through
    ``public_dump``; the worker reads the column off the row, never off a
    response."""
    submit_obj = LinsightQuestionSubmitSchema(question="总结下附件", files=[_daily_file("d1", "报告.pdf")])

    await LinsightWorkbenchImpl.submit_user_question(submit_obj, _login_user())

    version = submit_env["version"]
    assert version.pending_files[0]["file_url"].startswith("/tmp-dir/")
    assert "pending_files" not in version.public_dump()
    # Everything else still ships, including the (empty) ingested list.
    assert version.public_dump()["files"] is None
    assert version.public_dump()["id"] == version.id


# ---------------------------------------------------------------------------
# amget misalignment (pre-existing bug, widened by the longer deferral window)
# ---------------------------------------------------------------------------
async def test_an_expired_temp_key_cannot_hand_its_neighbour_the_wrong_markdown():
    """``amget`` is ``[loads(v) for v in values if v is not None]`` — a miss makes
    the returned list SHORTER than the keys, so pairing it positionally with the
    file list handed file A the markdown that belongs to file B. Deferring the
    ingest by minutes only makes an expired temp key likelier.
    """
    minio = FakeMinio()
    info2 = _temp_info("f2", "b.pdf")
    minio.store[(minio.tmp_bucket, info2["markdown_file_path"])] = b"# B\nbody of b\n"

    fake_redis = AsyncMock()
    # f1's temp key expired; only f2's value survives the mget.
    fake_redis.amget = AsyncMock(return_value=[info2])
    fake_redis.aget = AsyncMock(side_effect=lambda key: None if key.endswith("f1") else info2)

    with (
        patch.object(LinsightWorkbenchImpl, "_get_redis", return_value=fake_redis),
        patch.object(workbench_impl, "get_minio_storage", new=AsyncMock(return_value=minio)),
    ):
        result = await LinsightWorkbenchImpl._process_submitted_files(
            [_legacy_file("f1", "a.pdf"), _legacy_file("f2", "b.pdf")], "svid1", 7
        )

    by_id = {entry["file_id"]: entry for entry in result}
    # The expired one is reported as expired instead of quietly wearing b.pdf's body.
    assert by_id["f1"]["valid"] is False
    assert by_id["f1"].get("parsing_status") in ("expired", "invalid")
    assert by_id["f2"]["valid"] is True
    assert by_id["f2"]["workspace_path"] == "/uploads/b.md"
    assert minio.store[("bisheng", "workspace/svid1/uploads/b.md")] == b"# B\nbody of b\n"
    assert not [key for (_bucket, key) in minio.store if key.startswith("workspace/svid1/uploads/a")]
