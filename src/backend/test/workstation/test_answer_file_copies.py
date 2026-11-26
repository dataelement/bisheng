"""F004 design §7 item 11: an answer keeps its own copy of the files its run wrote.

A direct run writes its files to ``workspace/{conversation}/output/...``. A later
run may write the same path again. When the answer row is written, each file of
the run is copied to ``chat/{partition}/answers/{run_id}/`` and the row points at
the copy, so the old answer still downloads what it produced.

No MinIO, no Redis server, no database: the object store is a dict, Redis is
fakeredis and the message table is in memory.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
import pytest
from loguru import logger

from bisheng.chat_session.domain import chat as chat_domain
from bisheng.core.storage import chat_attachment
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services import file_events
from bisheng.linsight.domain.services.run_event_stream import RunEventStream
from bisheng.workstation.api.endpoints import chat as chat_endpoints
from bisheng.workstation.domain.services import chat_service, run_files, run_send
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector
from test.workstation.run_persist_support import MessageTable

CID = "conv-copies"
USER = 7
PREFIX = f"workspace/{CID}"
PATH = "output/report.xlsx"
WORKSPACE_KEY = f"{PREFIX}/{PATH}"
WORKSPACE_ID = file_events.workspace_file_id(PREFIX, PATH)


class _Store:
    """The slice of the MinIO client the copies and the links use."""

    bucket = "bisheng"
    tmp_bucket = "tmp-dir"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.copies: list[tuple[str, str, str, str]] = []
        self.signed: list[str] = []
        self.fail_copy_of: set[str] = set()

    async def copy_object(
        self, source_bucket: str = None, source_object: str = None, dest_bucket: str = None, dest_object: str = None
    ) -> None:
        if source_object in self.fail_copy_of:
            raise OSError(f"copy of {source_object} refused")
        self.copies.append((source_bucket, source_object, dest_bucket, dest_object))
        self.objects[dest_object] = self.objects[source_object]

    async def object_exists(self, bucket_name: str = None, object_name: str = None) -> bool:
        return object_name in self.objects

    async def get_share_link(self, object_name: str, *args: Any, **kwargs: Any) -> str:
        self.signed.append(object_name)
        return f"/signed/{object_name}"


@pytest.fixture
def env(monkeypatch):
    table = MessageTable().install(monkeypatch)
    store = _Store()
    redis = fakeredis.aioredis.FakeRedis()

    async def no_citations(**_: Any) -> None:
        return None

    async def object_store() -> _Store:
        return store

    async def attachment_messages(chat_id: str):
        return [r for r in table.rows if r.chat_id == chat_id and r.files]

    async def get_one(chat_id: str):
        return _session() if chat_id == CID else None

    async def get_session(conversation_id: str):
        return _session() if conversation_id == CID else None

    real_stream = RunEventStream
    monkeypatch.setattr(chat_service, "save_message_citations", no_citations)
    monkeypatch.setattr(chat_domain.WorkflowFileRepository, "attachment_messages", attachment_messages)
    monkeypatch.setattr(chat_domain.MessageSessionDao, "async_get_one", get_one)
    monkeypatch.setattr(chat_domain, "get_minio_storage", object_store)
    monkeypatch.setattr(chat_domain, "_resolve_leaf_tenant_id", lambda user: 1)
    monkeypatch.setattr(run_files, "RunEventStream", lambda *a, **k: real_stream(redis))
    monkeypatch.setattr(run_files, "_default_minio", object_store)
    monkeypatch.setattr(run_send, "_get_session", get_session)
    return SimpleNamespace(table=table, store=store, redis=redis, object_store=object_store)


def _session():
    return SimpleNamespace(chat_id=CID, user_id=USER, tenant_id=1, api_subject_type=None, is_delete=False)


def _owner():
    return SimpleNamespace(user_id=USER, tenant_id=1)


def _event(run_id: str, event_type: str, data: dict | None = None) -> dict:
    return run_events.make_event(event_type, data or {}, run_id=run_id)


async def _run(env, run_id: str, content: bytes, terminal: str = run_events.RUN_FINISHED, **overrides: Any):
    """One direct run that writes ``output/report.xlsx`` and ends with ``terminal``.

    Feeds the Redis stream (what a live client reads) and the projector (what
    writes the answer row), like the runner does.
    """
    stream = RunEventStream(env.redis)
    kwargs: dict[str, Any] = {
        "run_id": run_id,
        "conversation_id": CID,
        "user_id": USER,
        "sender": "model",
        "object_store": env.object_store,
    }
    kwargs.update(overrides)
    projector = DirectRunProjector(**kwargs)
    env.store.objects[WORKSPACE_KEY] = content
    data = file_events.file_event_data(PREFIX, PATH, len(content), "write_file")
    terminal_data = {"detail": "boom", "reason": "error"} if terminal == run_events.RUN_FAILED else {}
    for event in (
        _event(run_id, run_events.RUN_STARTED),
        _event(run_id, run_events.FILE, data),
        _event(run_id, run_events.TEXT, {"text": "做好了"}),
        _event(run_id, terminal, terminal_data),
    ):
        await stream.append(CID, event)
        await projector.on_event(event)
    return projector.answer_row


def _files(row) -> list[dict]:
    return json.loads(row.files)


def _capture_errors() -> tuple[list[str], int]:
    lines: list[str] = []
    return lines, logger.add(lambda m: lines.append(str(m)), level="ERROR", format="{message}")


# --------------------------------------------------------------- the copies


async def test_answer_row_points_at_its_own_copy(env):
    row = await _run(env, "run-a", b"version-1")

    (item,) = _files(row)
    copy_key = f"chat/{USER}/answers/run-a/{WORKSPACE_ID}.xlsx"
    assert item == {
        "file_id": chat_attachment.answer_file_id(copy_key),
        "file_name": "report.xlsx",
        "path": PATH,
        "type": item["type"],
        "size": 9,
        "source": "code_interpreter",
        "object_name": copy_key,
        "workspace_file_id": WORKSPACE_ID,
    }
    assert item["file_id"] != WORKSPACE_ID
    # A copy inside the main bucket, made by the object store (no download, no upload).
    assert env.store.copies == [("bisheng", WORKSPACE_KEY, "bisheng", copy_key)]
    assert env.store.objects[copy_key] == b"version-1"
    # The workspace object is still there for the live events and the workspace panel.
    assert env.store.objects[WORKSPACE_KEY] == b"version-1"


async def test_old_answer_keeps_its_content_after_a_later_run_overwrites_the_path(env):
    first = await _run(env, "run-a", b"version-1")
    second = await _run(env, "run-b", b"version-2 longer")

    (old,), (new,) = _files(first), _files(second)
    assert old["object_name"] != new["object_name"] and old["file_id"] != new["file_id"]
    assert env.store.objects[old["object_name"]] == b"version-1"
    assert env.store.objects[new["object_name"]] == b"version-2 longer"
    assert env.store.objects[WORKSPACE_KEY] == b"version-2 longer"


@pytest.mark.parametrize("terminal", [run_events.RUN_STOPPED, run_events.RUN_FAILED])
async def test_stopped_and_failed_runs_keep_copies_too(env, terminal):
    row = await _run(env, "run-a", b"partial", terminal)

    (item,) = _files(row)
    assert item["object_name"] == f"chat/{USER}/answers/run-a/{WORKSPACE_ID}.xlsx"
    assert env.store.objects[item["object_name"]] == b"partial"


async def test_copies_use_the_storage_partition_of_the_conversation(env):
    row = await _run(env, "run-a", b"x", storage_partition="sa-42")

    assert _files(row)[0]["object_name"] == f"chat/sa-42/answers/run-a/{WORKSPACE_ID}.xlsx"


async def test_blocked_answer_keeps_no_file_and_makes_no_copy(env):
    projector = DirectRunProjector(
        run_id="run-a", conversation_id=CID, user_id=USER, sender="model", object_store=env.object_store
    )
    env.store.objects[WORKSPACE_KEY] = b"x"
    data = file_events.file_event_data(PREFIX, PATH, 1, "write_file")
    await projector.on_event(_event("run-a", run_events.FILE, data))
    await projector.on_event(
        _event("run-a", run_events.RUN_FINISHED, {"content_safety": True, "auto_reply": "不能回答"})
    )

    assert not projector.answer_row.files or _files(projector.answer_row) == []
    assert env.store.copies == []


# ----------------------------------------------------------------- failures


async def test_failed_copy_is_logged_and_the_row_keeps_the_workspace_object(env):
    env.store.fail_copy_of.add(WORKSPACE_KEY)
    lines, sink_id = _capture_errors()
    try:
        row = await _run(env, "run-a", b"version-1")
    finally:
        logger.remove(sink_id)

    (item,) = _files(row)
    # As before item 11: the event's id and the workspace object. No ``workspace_file_id``.
    assert item["file_id"] == WORKSPACE_ID
    assert item["object_name"] == WORKSPACE_KEY
    assert "workspace_file_id" not in item
    assert any("failed to copy generated file" in line and WORKSPACE_KEY in line for line in lines)
    assert any("1 of 1 generated file(s) have no copy" in line for line in lines)
    # The answer itself is saved.
    assert json.loads(row.message)["msg"] == "做好了"


async def test_unreachable_object_storage_is_logged_and_the_row_keeps_the_workspace_object(env):
    async def unreachable() -> Any:
        raise ConnectionError("minio down")

    lines, sink_id = _capture_errors()
    try:
        row = await _run(env, "run-a", b"version-1", object_store=unreachable)
    finally:
        logger.remove(sink_id)

    assert _files(row)[0]["object_name"] == WORKSPACE_KEY
    assert any("object storage unavailable" in line for line in lines)


async def test_one_failed_copy_does_not_cost_the_other_files(env):
    other_key = f"{PREFIX}/output/chart.png"
    env.store.objects[other_key] = b"png"
    env.store.objects[WORKSPACE_KEY] = b"sheet"
    env.store.fail_copy_of.add(WORKSPACE_KEY)
    projector = DirectRunProjector(
        run_id="run-a", conversation_id=CID, user_id=USER, sender="model", object_store=env.object_store
    )
    for path, size in ((PATH, 5), ("output/chart.png", 3)):
        await projector.on_event(
            _event("run-a", run_events.FILE, file_events.file_event_data(PREFIX, path, size, "write_file"))
        )
    await projector.on_event(_event("run-a", run_events.RUN_FINISHED))

    sheet, chart = _files(projector.answer_row)
    assert sheet["object_name"] == WORKSPACE_KEY
    assert chart["object_name"].startswith(f"chat/{USER}/answers/run-a/") and chart["object_name"].endswith(".png")
    assert env.store.objects[chart["object_name"]] == b"png"


# ------------------------------------------------------------ the URL route


async def _url(file_id: str) -> str:
    return (await chat_endpoints.conversation_file_url(CID, file_id, login_user=_owner())).data["url"]


async def test_url_route_serves_live_file_and_finished_answer(env):
    first = await _run(env, "run-a", b"version-1")
    old = _files(first)[0]
    second = await _run(env, "run-b", b"version-2")
    new = _files(second)[0]

    # The id of the ``file`` events (the snapshot of run-b is still there): the workspace file.
    assert await _url(WORKSPACE_ID) == f"/signed/{WORKSPACE_KEY}"
    # The ids on the answer rows: each answer's own copy.
    assert await _url(old["file_id"]) == f"/signed/chat/{USER}/answers/run-a/{WORKSPACE_ID}.xlsx"
    assert await _url(new["file_id"]) == f"/signed/chat/{USER}/answers/run-b/{WORKSPACE_ID}.xlsx"


async def test_event_id_resolves_to_the_newest_copy_once_the_snapshot_is_gone(env):
    await _run(env, "run-a", b"version-1")
    await _run(env, "run-b", b"version-2")
    await env.redis.flushall()

    assert await _url(WORKSPACE_ID) == f"/signed/chat/{USER}/answers/run-b/{WORKSPACE_ID}.xlsx"
    with pytest.raises(Exception) as missing:
        await _url("no-such-file")
    assert getattr(missing.value, "status_code", None) == 404


async def test_legacy_attachment_endpoint_does_not_follow_the_alias(env):
    """F016's own endpoint keeps matching ``file_id`` only (switch-off behaviour)."""
    row = await _run(env, "run-a", b"version-1")
    service = chat_domain.ChatSessionService

    assert (await service.resolve_attachment_url(CID, _files(row)[0]["file_id"], _owner())).startswith("/signed/chat/")
    with pytest.raises(Exception) as missing:
        await service.resolve_attachment_url(CID, WORKSPACE_ID, _owner())
    assert getattr(missing.value, "status_code", None) == 404


async def test_auditor_gets_the_copy(env):
    row = await _run(env, "run-a", b"version-1")
    item = _files(row)[0]

    url = await chat_domain.ChatSessionService.resolve_audit_attachment_url(CID, item["file_id"])

    assert url == f"/signed/{item['object_name']}"


# ------------------------------------------------------------------- naming


def test_answer_object_name_is_stable_and_safe():
    name = chat_attachment.build_answer_file_object_name(7, "run-a", "abc123", "报告 final.XLSX")
    assert name == "chat/7/answers/run-a/abc123.xlsx"
    assert name == chat_attachment.build_answer_file_object_name(7, "run-a", "abc123", "报告 final.XLSX")
    # A run id or key that is not safe inside an object key is replaced by its digest.
    odd = chat_attachment.build_answer_file_object_name(7, "../../etc", "a/b", "x")
    assert ".." not in odd and odd.count("/") == 4


# ------------------------------------------- the terminal event names the copies


async def _prepared(env, terminal_data: dict | None = None, terminal: str = run_events.RUN_FINISHED):
    """A projector that saw one file event, asked before the terminal event is written."""
    projector = DirectRunProjector(
        run_id="run-a", conversation_id=CID, user_id=USER, sender="model", object_store=env.object_store
    )
    env.store.objects[WORKSPACE_KEY] = b"version-1"
    data = file_events.file_event_data(PREFIX, PATH, 9, "write_file")
    await projector.on_event(_event("run-a", run_events.FILE, data))
    event = _event("run-a", terminal, terminal_data)
    extra = await projector.before_terminal(event)
    return projector, event, extra


@pytest.mark.parametrize("terminal", [run_events.RUN_FINISHED, run_events.RUN_STOPPED, run_events.RUN_FAILED])
async def test_before_terminal_returns_the_files_the_row_stores(env, terminal):
    terminal_data = {"detail": "boom", "reason": "error"} if terminal == run_events.RUN_FAILED else {}
    projector, event, extra = await _prepared(env, terminal_data, terminal)

    (item,) = extra[run_events.ANSWER_FILES_FIELD]
    assert item["file_id"] == chat_attachment.answer_file_id(f"chat/{USER}/answers/run-a/{WORKSPACE_ID}.xlsx")
    assert item["workspace_file_id"] == WORKSPACE_ID
    assert item["path"] == PATH

    await projector.on_event(event)
    # The row stores the same items, and the copy was made once.
    assert _files(projector.answer_row) == extra[run_events.ANSWER_FILES_FIELD]
    assert len(env.store.copies) == 1


async def test_before_terminal_with_a_failed_copy_keeps_the_live_id(env):
    env.store.fail_copy_of.add(WORKSPACE_KEY)
    projector, event, extra = await _prepared(env)

    (item,) = extra[run_events.ANSWER_FILES_FIELD]
    assert item["file_id"] == WORKSPACE_ID
    assert "workspace_file_id" not in item
    await projector.on_event(event)
    assert _files(projector.answer_row) == [item]


async def test_before_terminal_of_a_blocked_answer_adds_nothing(env):
    projector, event, extra = await _prepared(env, {"content_safety": True, "auto_reply": "不能回答"})

    assert extra is None
    await projector.on_event(event)
    assert env.store.copies == []
    assert not projector.answer_row.files or _files(projector.answer_row) == []


async def test_before_terminal_without_files_adds_nothing(env):
    projector = DirectRunProjector(
        run_id="run-a", conversation_id=CID, user_id=USER, sender="model", object_store=env.object_store
    )
    await projector.on_event(_event("run-a", run_events.TEXT, {"text": "你好"}))

    assert await projector.before_terminal(_event("run-a", run_events.RUN_FINISHED)) is None
