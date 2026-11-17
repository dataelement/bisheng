"""F004 T054: ``file`` events and access control of generated files.

Covers AC-24 (a file is announced when it is stored, not at the end of the run),
AC-25 (a code-generated file of a direct run is on the stream and on the answer
row), AC-27 (stored in the main bucket, links signed on demand) and AC-28 (only
the owner, or an auditor through the audit endpoint, gets a link).

No MinIO, no Redis server, no database, no LLM: the object store is a dict,
Redis is fakeredis, the message table is in memory and the direct run is driven
by the scripted model of ``test_direct_run``.
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
import pytest
from langchain_core.messages import AIMessage

from bisheng.chat_session.domain import chat as chat_domain
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import file_events
from bisheng.linsight.domain.services.file_events import FileEventRelay, workspace_file_id
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend
from bisheng.workstation.api.endpoints import chat as chat_endpoints
from bisheng.workstation.domain.services import chat_service, run_files, run_send
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor
from test.linsight.test_planned_run_unified import CHAT, SVID
from test.linsight.test_planned_run_unified import _Env as _PlannedEnv
from test.workstation.test_direct_run import CID, USER, make_env  # noqa: F401
from test.workstation.test_direct_workspace_and_skills import CODE_PAYLOAD, RUN_CODE, _real_assembly

PREFIX = "workspace/conv-files"
RUN = "run-files"


class _Store:
    """The slice of the MinIO client the workspace uses; records the bucket of every write."""

    bucket = "bisheng"
    tmp_bucket = "tmp-dir"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.buckets: dict[str, str] = {}
        self.signed: list[str] = []
        self.minio_client_sync = self

    async def put_object(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.put_object_sync(bucket_name, object_name, file)

    def put_object_sync(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self.objects[object_name] = file
        self.buckets[object_name] = bucket_name

    def get_object_sync(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    async def get_object(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self.objects[object_name]

    def list_objects(self, bucket: str, prefix: str = "", recursive: bool = False):
        return [
            SimpleNamespace(object_name=name, size=len(data), is_dir=False, etag=f"etag-{hash(data)}")
            for name, data in sorted(self.objects.items())
            if name.startswith(prefix)
        ]

    async def object_exists(self, bucket_name: str = None, object_name: str = None) -> bool:
        return object_name in self.objects

    async def get_share_link(self, object_name: str, *args: Any, **kwargs: Any) -> str:
        self.signed.append(object_name)
        return f"/signed/{object_name}"


def _backend(tmp_path, store: _Store | None = None) -> tuple[WorkspaceBackend, FileEventRelay, list[dict], _Store]:
    """A workspace whose file events go to a list. Call inside a running loop."""
    store = store or _Store()
    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    relay = FileEventRelay(emit, run_id=RUN, workspace_prefix=PREFIX)
    backend = WorkspaceBackend(
        minio=store, file_dir=str(tmp_path / "cache"), workspace_prefix=PREFIX, on_output_file=relay
    )
    return backend, relay, events, store


def _files(events: list[dict]) -> list[dict]:
    return [event["data"] for event in events if event["type"] == run_events.FILE]


# --------------------------------------------------------------------- AC-24


async def test_file_event_on_output_write(tmp_path):
    backend, relay, events, store = _backend(tmp_path)

    result = await backend.awrite("/output/报告.md", "# 标题\n")
    await relay.drain()

    assert result.error is None
    # The event is written after the object store accepted the file.
    assert f"{PREFIX}/output/报告.md" in store.objects
    size = len("# 标题\n".encode())
    assert events == [
        {
            "type": "file",
            "run_id": RUN,
            "data": {
                "file_id": workspace_file_id(PREFIX, "output/报告.md"),
                "name": "报告.md",
                "path": "output/报告.md",
                "size": size,
                "source": "write_file",
            },
        }
    ]
    run_events.FileData.model_validate(events[0]["data"])

    # The synchronous surface runs on a worker thread (``aedit`` -> ``to_thread``).
    await backend.aedit("/output/报告.md", "标题", "新的标题")
    await asyncio.to_thread(backend.write, "/output/data.csv", "a,b\n")
    await relay.drain()
    assert [(f["path"], f["source"]) for f in _files(events)[1:]] == [
        ("output/报告.md", "edit_file"),
        ("output/data.csv", "write_file"),
    ]


async def test_backend_without_callback_writes_no_event(tmp_path):
    """The legacy path builds the backend without a callback: nothing changes there."""
    store = _Store()
    backend = WorkspaceBackend(minio=store, file_dir=str(tmp_path / "cache"), workspace_prefix=PREFIX)

    assert (await backend.awrite("/output/a.md", "x")).error is None
    assert backend.on_output_file is None


async def test_failing_callback_does_not_fail_the_write(tmp_path):
    store = _Store()

    def broken(_data: dict) -> None:
        raise RuntimeError("stream is down")

    backend = WorkspaceBackend(
        minio=store, file_dir=str(tmp_path / "cache"), workspace_prefix=PREFIX, on_output_file=broken
    )

    result = await backend.awrite("/output/a.md", "x")

    assert result.error is None and store.objects[f"{PREFIX}/output/a.md"] == b"x"


async def test_file_event_from_executor_sync(tmp_path):
    _backend_unused, relay, events, _store = _backend(tmp_path)
    work_dir = tmp_path / "work"
    for rel in ("output/deck.pptx", "scratch/chart.png"):
        path = work_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")
    uploads: list[tuple[str, str]] = []
    fake_minio = SimpleNamespace(
        fput_object=lambda bucket_name, object_name, file_path: uploads.append((bucket_name, object_name))
    )
    executor = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix=PREFIX)
    executor._minio_client = lambda: fake_minio
    # What ``DirectRunner._attach_run_extras`` and ``_attach_file_events`` set.
    executor.on_workspace_file = relay.synced

    # The executor mirrors its files on a worker thread.
    synced = await asyncio.to_thread(
        executor.sync_to_workspace, str(work_dir), ["output/deck.pptx", "scratch/chart.png"]
    )
    await relay.drain()

    assert synced == 2
    assert uploads == [("bisheng", f"{PREFIX}/output/deck.pptx"), ("bisheng", f"{PREFIX}/scratch/chart.png")]
    assert _files(events) == [
        {
            "file_id": workspace_file_id(PREFIX, "output/deck.pptx"),
            "name": "deck.pptx",
            "path": "output/deck.pptx",
            "size": 7,
            "source": "code_interpreter",
        }
    ]


async def test_executor_file_that_failed_to_mirror_is_not_announced(tmp_path):
    _backend_unused, relay, events, _store = _backend(tmp_path)
    work_dir = tmp_path / "work"
    (work_dir / "output").mkdir(parents=True)
    (work_dir / "output" / "a.txt").write_bytes(b"x")

    def fail(**_: Any) -> None:
        raise RuntimeError("object storage is down")

    executor = LocalExecutor(minio={"public_bucket": "bisheng"}, workspace_prefix=PREFIX)
    executor._minio_client = lambda: SimpleNamespace(fput_object=fail)
    executor.on_workspace_file = relay.synced

    assert executor.sync_to_workspace(str(work_dir), ["output/a.txt"]) == 0
    await relay.drain()
    assert events == []


async def test_same_path_updates(tmp_path):
    backend, relay, _events, _store = _backend(tmp_path)
    stream = RunEventStream(fakeredis.aioredis.FakeRedis())
    await stream.append("conv-files", run_events.make_event(run_events.RUN_STARTED, {}, run_id=RUN))

    async def emit(event: dict) -> None:
        await stream.append("conv-files", event)

    relay._emit_event = emit

    await backend.awrite("/output/a.md", "v1")
    await relay.drain()
    await backend.awrite("/output/a.md", "version two")
    await backend.awrite("/output/b.md", "b")
    await relay.drain()

    events = [e async for e in stream.read("conv-files")]
    ids = [e["data"]["file_id"] for e in events if e["type"] == "file"]
    # Every write is announced, always with the id of the path ...
    assert len(ids) == 3 and ids[0] == ids[1] != ids[2]
    # ... so the accumulated state holds one entry per file, with the newest data.
    files = (await stream.snapshot("conv-files"))["files"]
    assert [(f["path"], f["size"]) for f in files] == [("output/a.md", len("version two")), ("output/b.md", 1)]


async def test_scratch_is_silent(tmp_path):
    backend, relay, events, store = _backend(tmp_path)

    await backend.awrite("/scratch/notes.md", "draft")
    await backend.awrite("/uploads/source.md", "copy")
    await backend.awrite("/report.md", "root level")
    await asyncio.to_thread(backend.write, "/large_tool_results/call-1", "raw")
    relay.synced("scratch/chart.png", 10)
    relay.synced("output/../scratch/escape.png", 10)
    await relay.drain()

    assert len(store.objects) == 4
    assert events == []


# ------------------------------------------------------------------ reconcile


async def test_reconcile_at_run_end(tmp_path):
    backend, relay, events, store = _backend(tmp_path)
    store.objects[f"{PREFIX}/output/earlier.csv"] = b"left by an earlier run"
    store.objects[f"{PREFIX}/output/rewritten.csv"] = b"old"
    relay.take_baseline(backend.output_listing())

    await backend.awrite("/output/reported.md", "known")
    # Written by code whose notice never arrived.
    store.objects[f"{PREFIX}/output/missed.xlsx"] = b"12345"
    store.objects[f"{PREFIX}/output/rewritten.csv"] = b"new content"
    store.objects[f"{PREFIX}/scratch/tmp.bin"] = b"1"

    written = await relay.reconcile(backend.output_listing())

    assert written == 2
    by_path = {f["path"]: f for f in _files(events)}
    assert sorted(by_path) == ["output/missed.xlsx", "output/reported.md", "output/rewritten.csv"]
    assert by_path["output/missed.xlsx"] == {
        "file_id": workspace_file_id(PREFIX, "output/missed.xlsx"),
        "name": "missed.xlsx",
        "path": "output/missed.xlsx",
        "size": 5,
        "source": "workspace",
    }
    # A second reconcile finds nothing new.
    assert await relay.reconcile(backend.output_listing()) == 0


async def test_direct_run_reconciles_code_output_into_stream_and_row(make_env, monkeypatch):  # noqa: F811
    """AC-25: the stand-in interpreter stores its file without any notice."""
    from test.workstation.run_persist_support import MessageTable

    table = MessageTable().install(monkeypatch)

    async def no_citations(**_: Any) -> None:
        return None

    monkeypatch.setattr(chat_service, "save_message_citations", no_citations)
    env = make_env([RUN_CODE, AIMessage(content="图表已生成")])
    runner, _binder = _real_assembly(env, monkeypatch)
    env.store.objects[f"workspace/{CID}/output/earlier.csv"] = b"a,b\n"
    ctx = await env.submit("画一张图")
    ctx.tools = [CODE_PAYLOAD]
    projector = DirectRunProjector(run_id=ctx.run_id, conversation_id=CID, user_id=USER, sender="model")
    env.hook = projector.on_event

    assert (await env.run(ctx, runner)).status == "finished"

    events = await env.events()
    files = [e["data"] for e in events if e["type"] == "file"]
    file_id = workspace_file_id(f"workspace/{CID}", "output/chart.txt")
    # Only the file of this run; the leftover of an earlier run is not announced.
    assert files == [
        {"file_id": file_id, "name": "chart.txt", "path": "output/chart.txt", "size": 5, "source": "workspace"}
    ]
    # Announced before the terminal event, which is the last event of the run.
    assert [e["type"] for e in events][-2:] == ["file", "run_finished"]
    # The answer row carries the same file with the same id (F016).
    (row,) = table.answers()
    assert json.loads(row.files) == [
        {
            "file_id": file_id,
            "file_name": "chart.txt",
            "path": "output/chart.txt",
            "type": "text/plain",
            "size": 5,
            "source": "code_interpreter",
            "object_name": f"workspace/{CID}/output/chart.txt",
        }
    ]
    # The local cache is gone; the reconcile read object storage (C8).
    assert not os.path.exists(env.file_dir)


async def test_direct_run_without_code_lists_nothing(make_env, monkeypatch):  # noqa: F811
    """A run that touches no file pays for no listing of the workspace (K1)."""
    env = make_env([AIMessage(content="你好")])
    listed: list[str] = []
    env.store.list_objects = lambda bucket, prefix="", recursive=False: listed.append(prefix) or []

    assert (await env.run(await env.submit("你好"))).status == "finished"

    assert listed == []
    assert "file" not in await env.types()


async def test_planned_run_announces_live_and_reconciles_final_files(monkeypatch, tmp_path):
    env = _PlannedEnv(monkeypatch, tmp_path)
    task = env.task()
    prefix = f"workspace/{CHAT}"
    out = tmp_path / "output"
    out.mkdir()
    (out / "报告.md").write_bytes(b"final")
    (out / "数据.xlsx").write_bytes(b"12345678")

    async with task._acquire_session_run_lock():
        await task._enter_conversation_thread(env.version)
        backend = task._workspace_backend(env.version, env.store)
        executor = SimpleNamespace(workspace_prefix=prefix)
        task._attach_file_events([SimpleNamespace(name="bisheng_code_interpreter", executor=executor)], env.version)
        # Live: the file tool writes the report; the executor never reports the sheet.
        await backend.awrite("/output/报告.md", "draft")
        env.version.output_result = {
            "final_files": [
                {
                    "file_id": "aaaa1111",
                    "file_name": "报告.md",
                    "file_path": str(out / "报告.md"),
                    "file_url": f"linsight/final_result/{SVID}/aaaa1111.md",
                },
                {
                    "file_id": "bbbb2222",
                    "file_name": "数据.xlsx",
                    "file_path": str(out / "数据.xlsx"),
                    "file_url": f"linsight/final_result/{SVID}/bbbb2222.xlsx",
                },
            ]
        }
        await task._finish_unified_run(env.version)

    assert executor.on_workspace_file.__self__ is backend.on_output_file
    events = await env.events()
    files = [e["data"] for e in events if e["type"] == "file"]
    report_id = workspace_file_id(prefix, "output/报告.md")
    sheet_id = workspace_file_id(prefix, "output/数据.xlsx")
    assert files == [
        {"file_id": report_id, "name": "报告.md", "path": "output/报告.md", "size": 5, "source": "write_file"},
        # Same id: the entry the client shows now points at the stored result.
        {
            "file_id": report_id,
            "name": "报告.md",
            "path": f"linsight/final_result/{SVID}/aaaa1111.md",
            "size": 5,
            "source": "final_result",
        },
        # Never announced while the run wrote it: announced by the reconcile.
        {
            "file_id": sheet_id,
            "name": "数据.xlsx",
            "path": f"linsight/final_result/{SVID}/bbbb2222.xlsx",
            "size": 8,
            "source": "final_result",
        },
    ]
    assert events[-1]["type"] == "run_finished"
    snapshot = await env.stream.snapshot(CHAT)
    assert [f["file_id"] for f in snapshot["files"]] == [report_id, sheet_id]


async def test_planned_legacy_path_builds_backend_without_callback(monkeypatch, tmp_path):
    env = _PlannedEnv(monkeypatch, tmp_path, unified=False)
    task = env.task()

    async with task._acquire_session_run_lock():
        backend = task._workspace_backend(env.version, env.store)
        executor = SimpleNamespace(workspace_prefix=f"workspace/{SVID}")
        task._attach_file_events([SimpleNamespace(name="bisheng_code_interpreter", executor=executor)], env.version)

    assert backend.on_output_file is None
    assert not hasattr(executor, "on_workspace_file")


# --------------------------------------------------------------------- AC-27


async def test_stored_in_main_bucket(tmp_path):
    backend, relay, events, store = _backend(tmp_path)

    await backend.awrite("/output/a.md", "x")
    await asyncio.to_thread(backend.write, "/output/b.md", "y")
    await relay.drain()

    # Main bucket (no lifecycle rule), under the workspace of the conversation.
    assert store.buckets == {f"{PREFIX}/output/a.md": "bisheng", f"{PREFIX}/output/b.md": "bisheng"}
    assert store.bucket != store.tmp_bucket
    # The event carries no link: links are signed when asked for.
    assert all("url" not in f and "filepath" not in f for f in _files(events))


# --------------------------------------------------------------------- AC-28


def _owner_session(user_id: int = USER):
    return SimpleNamespace(chat_id=CID, user_id=user_id, tenant_id=1, api_subject_type=None)


async def _live_file(redis, store: _Store, name: str = "report.xlsx") -> str:
    stream = RunEventStream(redis)
    prefix = f"workspace/{CID}"
    store.objects[f"{prefix}/output/{name}"] = b"sheet"
    await stream.append(CID, run_events.make_event(run_events.RUN_STARTED, {}, run_id=RUN))
    data = file_events.file_event_data(prefix, f"output/{name}", 5, "code_interpreter")
    await stream.append(CID, run_events.make_event(run_events.FILE, data, run_id=RUN))
    return data["file_id"]


@pytest.fixture
def live(monkeypatch):
    redis = fakeredis.aioredis.FakeRedis()
    store = _Store()

    async def minio():
        return store

    async def get_session(conversation_id: str):
        return _owner_session() if conversation_id == CID else None

    real_stream = RunEventStream
    monkeypatch.setattr(run_files, "RunEventStream", lambda *a, **k: real_stream(redis))
    monkeypatch.setattr(run_files, "_default_minio", minio)
    monkeypatch.setattr(run_send, "_get_session", get_session)
    return SimpleNamespace(redis=redis, store=store)


async def test_non_owner_denied(live, monkeypatch):
    file_id = await _live_file(live.redis, live.store)
    fallbacks: list[tuple] = []

    async def stored_rows(chat_id, fid, login_user):
        fallbacks.append((chat_id, fid))
        raise chat_domain.NotFoundError.http_exception()

    monkeypatch.setattr(ChatSessionService, "resolve_attachment_url", stored_rows)

    # Another user of the same tenant: refused before anything is looked up or signed.
    stranger = SimpleNamespace(user_id=USER + 1)
    refused = await chat_endpoints.conversation_file_url(CID, file_id, login_user=stranger)
    assert refused.status_code == UnAuthorizedError.Code
    assert await chat_endpoints.conversation_file_url("no-such-conversation", file_id, login_user=stranger) == refused
    assert live.store.signed == [] and fallbacks == []

    # The owner gets a link to the workspace object of that file.
    owner = SimpleNamespace(user_id=USER)
    allowed = await chat_endpoints.conversation_file_url(CID, file_id, login_user=owner)
    assert allowed.data == {"url": f"/signed/workspace/{CID}/output/report.xlsx"}

    # The object key never comes from the caller: an unknown id goes to the stored rows.
    with pytest.raises(Exception) as missing:
        await chat_endpoints.conversation_file_url(CID, f"workspace/{CID}/output/report.xlsx", login_user=owner)
    assert getattr(missing.value, "status_code", None) == 404
    assert fallbacks and live.store.signed == [f"workspace/{CID}/output/report.xlsx"]


async def test_snapshot_path_outside_output_is_not_signed(live):
    stream = RunEventStream(live.redis)
    await stream.append(CID, run_events.make_event(run_events.RUN_STARTED, {}, run_id=RUN))
    for file_id, path in (("f-up", "output/../uploads/secret.pdf"), ("f-task", "linsight/final_result/sv/a.md")):
        await stream.append(
            CID, run_events.make_event(run_events.FILE, {"file_id": file_id, "name": "x", "path": path}, run_id=RUN)
        )
    snapshot = await stream.snapshot(CID)

    assert run_files.live_file_object_key(CID, snapshot, "f-up") is None
    assert run_files.live_file_object_key(CID, snapshot, "f-task") is None


async def test_audit_allowed(live, monkeypatch):
    """The audit endpoint of F016 signs the file from the answer row the projector wrote."""
    from test.workstation.run_persist_support import MessageTable

    table = MessageTable().install(monkeypatch)

    async def no_citations(**_: Any) -> None:
        return None

    monkeypatch.setattr(chat_service, "save_message_citations", no_citations)
    prefix = f"workspace/{CID}"
    data = file_events.file_event_data(prefix, "output/report.xlsx", 5, "write_file")
    live.store.objects[f"{prefix}/output/report.xlsx"] = b"sheet"
    projector = DirectRunProjector(run_id=RUN, conversation_id=CID, user_id=USER, sender="model")
    await projector.on_event(run_events.make_event(run_events.FILE, data, run_id=RUN))
    await projector.on_event(run_events.make_event(run_events.TEXT, {"text": "做好了"}, run_id=RUN))
    await projector.on_event(run_events.make_event(run_events.RUN_FINISHED, {}, run_id=RUN))
    (row,) = table.answers()

    async def attachment_messages(chat_id: str):
        return [r for r in table.rows if r.chat_id == chat_id]

    async def get_one(chat_id: str):
        return _owner_session() if chat_id == CID else None

    async def minio():
        return live.store

    monkeypatch.setattr(chat_domain.WorkflowFileRepository, "attachment_messages", attachment_messages)
    monkeypatch.setattr(chat_domain.MessageSessionDao, "async_get_one", get_one)
    monkeypatch.setattr(chat_domain, "get_minio_storage", minio)

    # The auditor is not the owner; the endpoint checked the audit scope before this call.
    url = await ChatSessionService.resolve_audit_attachment_url(CID, data["file_id"])

    assert url == f"/signed/{prefix}/output/report.xlsx"
    assert json.loads(row.files)[0]["source"] == "code_interpreter"
    # A user upload of the same conversation stays out of the auditor's reach.
    table.rows[0].files = json.dumps([{"file_id": "u1", "object_name": "chat/7/u1.pdf", "source": "upload"}])
    with pytest.raises(Exception) as denied:
        await ChatSessionService.resolve_audit_attachment_url(CID, "u1")
    assert getattr(denied.value, "status_code", None) == 404
