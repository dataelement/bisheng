"""F016: files the code interpreter leaves under output/ ride on the daily-chat answer.

See features/v3.1.0-beta1/016-daily-chat-generated-files/design.md decisions 1, 2, 6.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.workstation.domain.services import chat_service


def _entry(path: str, url: str | None = None, size: int = 3) -> dict:
    name = path.rsplit("/", 1)[-1]
    return {"path": path, "name": name, "size": size, "url": url or f"http://h/tmp-dir/{name}.obj?sig"}


def _code_tool(entries: list[dict]):
    executor = SimpleNamespace(collect_deliverables=True, published_deliverables=entries)
    return SimpleNamespace(name="bisheng_code_interpreter", description="code", executor=executor)


# ---------------------------------------------------------------- pure helpers


def test_enable_sets_flag_and_appends_hint():
    inner = SimpleNamespace(description="Run python.", executor=SimpleNamespace(collect_deliverables=False))
    wrapper = SimpleNamespace(description="Run python.", tool_instance=inner)

    chat_service._enable_deliverable_collection(wrapper)

    assert inner.executor.collect_deliverables is True
    assert inner.description.startswith("Run python.")
    assert "attached to your reply automatically" in inner.description
    assert wrapper.description == inner.description


def test_enable_keeps_e2b_sandbox_for_the_turn():
    executor = SimpleNamespace(collect_deliverables=False, keep_sandbox=False)
    tool = SimpleNamespace(description="Run python.", executor=executor)

    chat_service._enable_deliverable_collection(tool)

    assert executor.keep_sandbox is True


def test_enable_leaves_executors_without_keep_sandbox_alone():
    executor = SimpleNamespace(collect_deliverables=False)

    chat_service._enable_deliverable_collection(SimpleNamespace(description="Run python.", executor=executor))

    assert not hasattr(executor, "keep_sandbox")


class _InlineThread:
    def __init__(self, target, args=(), **_):
        self._run = lambda: target(*args)

    def start(self):
        self._run()


def test_release_closes_only_kept_live_sandboxes(monkeypatch):
    monkeypatch.setattr(chat_service.threading, "Thread", _InlineThread)
    kept = SimpleNamespace(keep_sandbox=True, sandbox=object(), close=MagicMock())
    idle = SimpleNamespace(keep_sandbox=True, sandbox=None, close=MagicMock())
    container = SimpleNamespace(close=MagicMock())
    tools = [SimpleNamespace(executor=e) for e in (kept, idle, container)] + [SimpleNamespace(name="web_search")]

    chat_service._release_code_sandboxes(tools)

    kept.close.assert_called_once()
    idle.close.assert_not_called()
    container.close.assert_not_called()


def test_enable_ignores_tools_without_collection():
    tool = SimpleNamespace(description="search", executor=SimpleNamespace())

    chat_service._enable_deliverable_collection(tool)

    assert tool.description == "search"


def test_collect_dedup_keeps_last():
    tool = _code_tool(
        [_entry("output/a.docx", "http://h/tmp-dir/v1.docx"), _entry("output/a.docx", "http://h/tmp-dir/v2.docx")]
    )

    files = chat_service._collect_generated_files([tool])

    assert [f["filepath"] for f in files] == ["http://h/tmp-dir/v2.docx"]


def test_collect_caps_last_50():
    tool = _code_tool([_entry(f"output/f{i:02d}.txt") for i in range(60)])

    files = chat_service._collect_generated_files([tool])

    assert len(files) == chat_service.GENERATED_FILES_LIMIT == 50
    assert files[0]["path"] == "output/f10.txt"
    assert files[-1]["path"] == "output/f59.txt"


def test_item_shape():
    tool = _code_tool([_entry("output/北京今日天气.docx", "http://h/tmp-dir/x.docx?sig", size=12)])

    (item,) = chat_service._collect_generated_files([tool, SimpleNamespace(name="web_search")])

    assert len(item["file_id"]) == 32
    assert item == {
        "file_id": item["file_id"],
        "file_name": "北京今日天气.docx",
        "path": "output/北京今日天气.docx",
        "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 12,
        "source": "code_interpreter",
        "filepath": "http://h/tmp-dir/x.docx?sig",
    }


@pytest.fixture
def storage(monkeypatch):
    client = MagicMock()
    client.tmp_bucket = "tmp-dir"
    client.bucket = "bisheng"

    async def copy_object(*, source_object, **_):
        if source_object.startswith("broken"):
            raise RuntimeError("copy failed")

    client.copy_object = AsyncMock(side_effect=copy_object)
    monkeypatch.setattr("bisheng.core.storage.chat_attachment.get_minio_storage", AsyncMock(return_value=client))
    return client


async def test_promote_partial_failure_keeps_others(storage):
    tool = _code_tool(
        [
            _entry("output/a.docx", "http://h/tmp-dir/broken.docx?sig"),
            _entry("output/b.xlsx", "http://h/tmp-dir/ok.xlsx?sig"),
        ]
    )

    files = await chat_service._promote_generated_files([tool], "chat-1", 7, "t1-7")

    assert len(files) == 2
    assert "object_name" not in files[0]
    assert files[0]["filepath"] == "http://h/tmp-dir/broken.docx?sig"
    assert files[1]["object_name"]


async def test_promoted_item_has_object_name(storage):
    tool = _code_tool([_entry("output/b.xlsx", "http://h/tmp-dir/ok.xlsx?sig")])

    (item,) = await chat_service._promote_generated_files([tool], "chat-1", 7, "t1-7")

    assert item["object_name"].startswith("chat/t1-7/")
    assert item["object_name"].endswith(".xlsx")
    assert storage.copy_object.await_args.kwargs["source_object"] == "ok.xlsx"
    # Kept so the card stays clickable; opening re-signs from object_name.
    assert item["filepath"] == "http://h/tmp-dir/ok.xlsx?sig"


# ---------------------------------------------------------------- stream wiring


class _Chunk:
    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs: dict = {}


def _data() -> APIChatCompletion:
    return APIChatCompletion(
        clientTimestamp="2026-11-13T00:00:00Z", conversationId="chat-1", model="m1", text="生成报告"
    )


@pytest.fixture
def stream_env(monkeypatch: pytest.MonkeyPatch):
    inserted: list = []
    conversation = SimpleNamespace(chat_id="chat-1", user_id=7, name="New Chat")
    message = SimpleNamespace(id=101)
    ws_config = SimpleNamespace(systemPrompt="")
    model_info = SimpleNamespace(displayName="qwen3.7-plus")
    state = {"after": None}
    tool = _code_tool([_entry("output/report.docx", "http://h/tmp-dir/r.docx?sig")])

    class _Agent:
        async def astream_events(self, *_a, **_k):
            for text in ["报告已生成 ", "见 report.docx"]:
                yield {"event": "on_chat_model_stream", "name": "model", "data": {"chunk": _Chunk(text)}}
            if state["after"] is not None:
                raise state["after"]

    monkeypatch.setattr(
        chat_service,
        "_agent_initialize_chat",
        AsyncMock(return_value=(ws_config, conversation, message, MagicMock(), model_info, False)),
    )
    monkeypatch.setattr(chat_service, "_resolve_user_kb_selection", AsyncMock(return_value=[]))
    monkeypatch.setattr("bisheng.common.image_view.loop.image_view_configured", AsyncMock(return_value=False))
    monkeypatch.setattr(chat_service.DailyCitationScope, "load", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "gen_title", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "_prepare_tools", AsyncMock(return_value=([tool], [])))
    monkeypatch.setattr(chat_service, "_get_agent_max_iterations", AsyncMock(return_value=8))
    monkeypatch.setattr("langgraph.prebuilt.ToolNode", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr("langgraph.prebuilt.create_react_agent", lambda *_a, **_k: _Agent())
    monkeypatch.setattr(chat_service, "_process_agent_files", AsyncMock(return_value=("", [], [])))
    monkeypatch.setattr(chat_service, "_get_history_max_tokens", AsyncMock(return_value=4096))
    monkeypatch.setattr(chat_service.WorkStationService, "get_chat_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat_service.DepartmentFlowService, "resolve_limit_and_dept", AsyncMock(return_value=(0, None)))
    monkeypatch.setattr(chat_service, "log_telemetry_events", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "save_message_citations_sync", MagicMock(return_value=None))
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService, "evaluate_workbench_user_text", staticmethod(lambda *_a, **_k: None)
    )
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService,
        "is_workbench_content_safety_active",
        staticmethod(lambda *_a, **_k: False),
    )

    async def promote(files, _user_id, *, storage_partition=None):
        for f in files:
            f["object_name"] = f"chat/{storage_partition or _user_id}/x.docx"
        return files

    def promote_sync(files, partition):
        for f in files:
            f["object_name"] = f"chat/{partition}/x.docx"
        return files

    promote_async = AsyncMock(side_effect=promote)
    promote_blocking = MagicMock(side_effect=promote_sync)
    monkeypatch.setattr(chat_service, "promote_chat_attachments", promote_async)
    monkeypatch.setattr(chat_service, "promote_chat_attachments_sync", promote_blocking)

    def _record(row):
        inserted.append(row)
        row.id = 900 + len(inserted)
        return row

    monkeypatch.setattr(chat_service.ChatMessageDao, "insert_one", MagicMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(side_effect=_record))
    monkeypatch.setattr(chat_service.ChatMessageDao, "aupdate_message_model", AsyncMock())
    monkeypatch.setattr(chat_service, "mark_session_content_violation", MagicMock())
    return SimpleNamespace(
        inserted=inserted, state=state, promote_async=promote_async, promote_blocking=promote_blocking
    )


def _login_user():
    user = MagicMock()
    user.user_id = 7
    return user


def _answer_rows(inserted: list):
    return [row for row in inserted if row.category == "agent_answer"]


def _end_event(chunks: list[str]) -> dict:
    for chunk in chunks:
        if '"agent_answer"' in chunk and '"end"' in chunk:
            return json.loads(chunk.split("data: ", 1)[1])
    raise AssertionError("no agent_answer end event")


async def test_answer_row_and_end_event_carry_files(stream_env):
    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), _login_user())
    chunks = [c async for c in response.body_iterator]

    (row,) = _answer_rows(stream_env.inserted)
    (stored,) = json.loads(row.files)
    assert stored["path"] == "output/report.docx"
    assert stored["object_name"] == "chat/7/x.docx"
    assert set(json.loads(row.message)) == {"msg", "events"}

    end_message = _end_event(chunks)["message"]
    assert end_message["files"] == [stored]
    assert end_message["msg"] == "报告已生成 见 report.docx"


async def test_stream_end_releases_turn_sandboxes(stream_env, monkeypatch):
    release = MagicMock()
    monkeypatch.setattr(chat_service, "_release_code_sandboxes", release)

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), _login_user())
    _ = [c async for c in response.body_iterator]

    (tools,) = release.call_args.args
    assert [t.name for t in tools] == ["bisheng_code_interpreter"]


async def test_stop_releases_turn_sandboxes(stream_env, monkeypatch):
    stream_env.state["after"] = asyncio.CancelledError()
    release = MagicMock()
    monkeypatch.setattr(chat_service, "_release_code_sandboxes", release)

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), _login_user())
    with pytest.raises(asyncio.CancelledError):
        _ = [c async for c in response.body_iterator]

    release.assert_called_once()


async def test_safety_replacement_has_no_files(stream_env, monkeypatch):
    monkeypatch.setattr(
        chat_service.SensitiveWordPolicyService, "is_workbench_content_safety_active", lambda *_a, **_k: True
    )
    scanner = SimpleNamespace(feed=lambda _d: None, finish=lambda: SimpleNamespace(auto_reply="已替换"))
    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.services.stream_scanner.StreamContentSafetyScanner", lambda _t: scanner
    )

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), _login_user())
    chunks = [c async for c in response.body_iterator]

    (row,) = _answer_rows(stream_env.inserted)
    assert row.files is None
    assert "files" not in _end_event(chunks)["message"]
    stream_env.promote_async.assert_not_awaited()


async def test_stop_path_uses_sync_promotion(stream_env):
    stream_env.state["after"] = asyncio.CancelledError()

    response = await chat_service._agent_stream_chat_completion(MagicMock(), _data(), _login_user())
    with pytest.raises(asyncio.CancelledError):
        _ = [c async for c in response.body_iterator]

    (row,) = _answer_rows(stream_env.inserted)
    (stored,) = json.loads(row.files)
    assert stored["object_name"] == "chat/7/x.docx"
    stream_env.promote_blocking.assert_called_once()
    stream_env.promote_async.assert_not_awaited()
