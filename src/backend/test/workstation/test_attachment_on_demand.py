"""F004 T056: attachments of a ``direct`` run are read on demand (design 决策 12).

Covers AC-26 (an attachment lands in ``workspace/{conversation_id}/uploads/``),
AC-34 (the model request does not wait for parsing) and AC-51 (the "reading
attachments" frame is open whenever the run waits for parsing).

The REAL graph runs with a scripted model. Redis is fakeredis, the object store
is a dict. The runner-level tests use a fake attachment source; the production
source is tested against the dict store with a fake parser.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from bisheng.linsight.domain.services.workspace_backend import BINARY_READ_ERROR_PREFIX, WorkspaceBackend
from bisheng.workstation.domain.services import direct_attachments, direct_run
from bisheng.workstation.domain.services.direct_run import DirectRunContext
from test.workstation.test_direct_run import CID, TENANT, USER, _call, _Env

DOCX = {"filepath": "tmp/a.docx?sig=1", "file_name": "a.docx", "file_id": "f" * 32}
PDF = {"filepath": "tmp/b.pdf?sig=1", "file_name": "b.pdf", "file_id": "e" * 32}
BODY = "合同金额 300 万，签署日期 2026 年 3 月 1 日。"
LIMITS = {"inline_chars": 4000, "inline_total_chars": 15000}


@pytest.fixture
def make_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _make(script: list[Any]) -> _Env:
        return _Env(monkeypatch, tmp_path, script)

    return _make


def _frames(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == direct_run.ATTACHMENT_TOOL_NAME]


def _tool_frames(events: list[dict], name: str) -> list[dict]:
    return [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == name]


def _first_user_text(env: _Env) -> str:
    return str(next(m for m in env.model.inputs[0] if m.type == "human").content)


class _FakeSource:
    """Stands for the upload-parse state and the workspace copy.

    ``parsed``  file name -> text of the files whose upload-time parsing has finished.
    ``slow``    file name -> text of the files still being parsed; each one is
                released by ``release(name)``.
    """

    def __init__(self, env: _Env, *, parsed: dict[str, str] | None = None, slow: dict[str, str] | None = None):
        self.env = env
        self.parsed = dict(parsed or {})
        self.slow = dict(slow or {})
        self.gates = {name: asyncio.Event() for name in self.slow}
        self.inline_chars = 100
        self.inline_total_chars = 150
        self.ingested: list[str] = []
        self.fail: dict[str, BaseException] = {}

    def release(self, name: str) -> None:
        self.gates[name].set()

    async def ready(self, ctx: DirectRunContext, file: dict) -> bool:
        return file["file_name"] in self.parsed

    async def visual(self, ctx: DirectRunContext) -> bool:
        return False

    async def ingest(self, ctx: DirectRunContext, file: dict, used_names: set[str]) -> dict:
        name = file["file_name"]
        if name in self.gates:
            await self.gates[name].wait()
        if name in self.fail:
            raise self.fail[name]
        text = self.parsed.get(name) or self.slow[name]
        stem = name.rsplit(".", 1)[0]
        rel = f"uploads/{stem}.md"
        self.env.store.objects[f"workspace/{ctx.conversation_id}/{rel}"] = text.encode()
        self.ingested.append(name)
        return {
            "file_id": file["file_id"],
            "original_filename": name,
            "parsing_status": "completed",
            "valid": True,
            "workspace_path": f"/{rel}",
            "markdown_filename": f"{stem}.md",
            "line_count": text.count("\n") + 1,
            "image_count": 0,
        }

    async def text(self, ctx: DirectRunContext, entry: dict) -> str | None:
        key = f"workspace/{ctx.conversation_id}{entry['workspace_path']}"
        return self.env.store.objects[key].decode()


async def _submit(env: _Env, text: str, files: list[dict]) -> DirectRunContext:
    ctx = await env.submit(text)
    ctx.files = [dict(f) for f in files]
    return ctx


# --------------------------------------------------------------------- runner


async def test_run_does_not_wait_for_parsing(make_env):
    seen: dict[str, Any] = {}

    async def answer(messages: list) -> AIMessage:
        # The model is asked while b.pdf is still being parsed.
        seen["ingested"] = list(source.ingested)
        seen["frames"] = [f["data"]["status"] for f in _frames(await env.events())]
        source.release("b.pdf")
        return AIMessage(content="先回答")

    env = make_env([answer])
    source = _FakeSource(env, slow={"b.pdf": BODY})
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "合同金额是多少", [PDF])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert seen == {"ingested": [], "frames": ["start"]}
    # The model input names the attachment and the path it will have; no body yet.
    first = _first_user_text(env)
    assert "b.pdf" in first and "/uploads/b.md" in first
    assert BODY not in first
    events = await env.events()
    assert [f["data"]["status"] for f in _frames(events)] == ["start", "end"]
    assert events[-1]["type"] == "run_finished"
    assert events.index(_frames(events)[1]) < len(events) - 1


async def test_small_parsed_file_inlined(make_env):
    long_text = "长文档内容。" * 100
    big = {"filepath": "tmp/big.docx", "file_name": "big.docx", "file_id": "b" * 32}
    env = make_env([AIMessage(content="合同金额是 300 万")])
    source = _FakeSource(env, parsed={"a.docx": BODY, "big.docx": long_text})
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "合同金额是多少", [DOCX, big])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    first = _first_user_text(env)
    # Below the threshold and already parsed: the text is in the first request.
    assert BODY in first and "/uploads/a.md" in first
    # Above the threshold: listed with its path, read on demand.
    assert "/uploads/big.md" in first and "big.docx" in first
    assert long_text not in first
    assert env.model.calls == 1
    # Both files are in the workspace of the conversation (AC-26).
    assert f"workspace/{CID}/uploads/a.md" in env.store.objects
    assert f"workspace/{CID}/uploads/big.md" in env.store.objects
    # Nothing was waited for: the frame closed before the answer text.
    events = await env.events()
    types = [e["type"] for e in events]
    frames = _frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert events.index(frames[1]) < types.index("text")


async def test_inline_total_budget_is_respected(make_env):
    files = [{"filepath": f"tmp/{i}.docx", "file_name": f"{i}.docx", "file_id": f"{i}" * 32} for i in range(3)]
    texts = {f"{i}.docx": f"第{i}份" + "字" * 60 for i in range(3)}
    env = make_env([AIMessage(content="好")])
    source = _FakeSource(env, parsed=texts)
    runner = env.make_runner(attachment_source=lambda ctx: source)

    await env.run(await _submit(env, "看看", files), runner=runner)

    first = _first_user_text(env)
    # 63 characters each, total budget 150: two are inlined, the third is only listed.
    assert texts["0.docx"] in first and texts["1.docx"] in first
    assert texts["2.docx"] not in first and "/uploads/2.md" in first


async def test_read_waits_with_progress(make_env):
    env = make_env([_call("read_file", {"file_path": "/uploads/b.md"}, "r1"), AIMessage(content="合同金额是 300 万")])
    source = _FakeSource(env, slow={"b.pdf": BODY})
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "合同金额是多少", [PDF])
    at_release: dict[str, Any] = {}

    async def release_when_read_started() -> None:
        # Parsing finishes only after the agent has asked for the file.
        while not _tool_frames(await env.events(), "read_file"):
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        events = await env.events()
        at_release["attachment"] = [f["data"]["status"] for f in _frames(events)]
        at_release["read"] = [f["data"]["status"] for f in _tool_frames(events, "read_file")]
        source.release("b.pdf")

    releaser = asyncio.create_task(release_when_read_started())
    outcome = await env.run(ctx, runner=runner)
    await releaser

    assert outcome.status == "finished"
    # While the read waited, the "reading attachments" frame was open and the read had not returned.
    assert at_release == {"attachment": ["start"], "read": ["start"]}
    events = await env.events()
    frames = _frames(events)
    read = _tool_frames(events, "read_file")
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert [f["data"]["status"] for f in read] == ["start", "end"]
    # start (run start) < read start < attachments end < read end
    order = [events.index(frames[0]), events.index(read[0]), events.index(frames[1]), events.index(read[1])]
    assert order == sorted(order)
    # The read returned the parsed text.
    tool_message = next(m for m in env.model.inputs[-1] if isinstance(m, ToolMessage))
    assert "合同金额 300 万" in str(tool_message.content)


async def test_failed_attachment_does_not_fail_the_run(make_env):
    env = make_env([AIMessage(content="这个附件读不了")])
    source = _FakeSource(env, parsed={"a.docx": BODY})
    source.fail["a.docx"] = RuntimeError("a.docx: 解析失败")
    runner = env.make_runner(attachment_source=lambda ctx: source)

    outcome = await env.run(await _submit(env, "看看附件", [DOCX]), runner=runner)

    assert outcome.status == "finished"
    first = _first_user_text(env)
    assert "a.docx" in first and "未能" in first
    end = _frames(await env.events())[1]
    assert end["data"]["extra_info"]["failed"] == ["a.docx"]


async def test_refused_run_cancels_pending_parsing(make_env):
    env = make_env([AIMessage(content="不应调用")])
    env.admit_error = RuntimeError("额度不足")
    source = _FakeSource(env, slow={"b.pdf": BODY})
    runner = env.make_runner(attachment_source=lambda ctx: source)

    outcome = await env.run(await _submit(env, "看看附件", [PDF]), runner=runner)

    assert outcome.status == "failed"
    events = await env.events()
    assert [f["data"]["status"] for f in _frames(events)] == ["start", "end"]
    assert events[-1]["type"] == "run_failed"
    assert env.model.calls == 0
    await asyncio.sleep(0.01)
    assert source.ingested == []
    assert not direct_attachments._BACKGROUND


async def test_stop_closes_the_frame_and_parsing_goes_on(make_env):
    """A stopped run closes its frame before ``run_stopped``; the file still reaches the workspace (AC-26)."""

    async def stopped_mid_answer(messages: list) -> AIMessage:
        await env.lease.request_stop(ctx.run_id, CID)
        await asyncio.sleep(30)
        raise AssertionError("the stopped run was not cancelled")

    env = make_env([stopped_mid_answer])
    source = _FakeSource(env, slow={"b.pdf": BODY})
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit(env, "看看附件", [PDF])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "stopped"
    events = await env.events()
    frames = _frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert frames[1]["data"]["extra_info"]["still_parsing"] == ["b.pdf"]
    assert events[-1]["type"] == "run_stopped"
    # Parsing continues after the run and nothing more is written to the stream.
    assert len(direct_attachments._BACKGROUND) == 1
    source.release("b.pdf")
    await asyncio.gather(*direct_attachments._BACKGROUND)
    assert f"workspace/{CID}/uploads/b.md" in env.store.objects
    assert len(await env.events()) == len(events)
    assert not direct_attachments._BACKGROUND


async def test_relay_run_with_files_in_its_head_message_runs(make_env, monkeypatch: pytest.MonkeyPatch):
    """A message sent during a run may carry files; the relay run must not crash on them."""
    from unittest.mock import AsyncMock

    from bisheng.linsight.domain import utils as linsight_utils

    async def interjected(messages: list) -> AIMessage:
        queued = await env.dispatch.submit(CID, {**env.message("再看看这个附件"), "files": [dict(DOCX)]})
        assert queued.disposition == "queued"
        return AIMessage(content="第一轮")

    env = make_env([interjected, AIMessage(content="第二轮")])
    source = _FakeSource(env, parsed={"a.docx": BODY})
    assert (await env.run(await env.submit("第一条"))).status == "finished"
    (item,) = env.relays
    assert item["files"] == [DOCX]
    monkeypatch.setattr(linsight_utils, "build_prior_conversation_summary", AsyncMock(return_value=""))
    runner = env.make_runner(build_input=None, attachment_source=lambda ctx: source)

    outcome = await env.run(dict(item), runner=runner)

    assert outcome.status == "finished"
    events = await env.events()
    assert events[-1]["type"] == "run_finished"
    # The relay run brings in the files of the message it starts from.
    assert [f["data"]["status"] for f in _frames(events)] == ["start", "end"]
    assert any(BODY in str(m.content) for m in env.model.inputs[-1])


def test_guard_waits_only_for_paths_that_may_hold_attachments():
    touches = direct_attachments.touches_uploads
    assert touches("/uploads/a.md") and touches("uploads") and touches("/") and touches("") and touches(None)
    assert not touches("/output/report.md") and not touches("skills/x/SKILL.md")
    assert not touches("/uploads-old/a.md")


# ------------------------------------------------------- names and listing


def test_binary_original_not_exposed_in_planned_names():
    plans = direct_attachments.plan_workspace_names(
        [
            PDF,
            {"file_name": "b.pdf", "file_id": "x"},
            {"file_name": "数据.csv"},
            {"file_name": "表.xlsx"},
            {"file_name": "a.zip"},
        ]
    )
    # A parsed document is read through its markdown view; the original keeps its
    # extension only as the code interpreter's data file.
    assert (plans[0].path, plans[0].raw) == ("/uploads/b.md", "uploads/b.pdf")
    # Same name twice: the suffix deep research would give.
    assert (plans[1].path, plans[1].raw) == ("/uploads/b-2.md", "uploads/b-2.pdf")
    # Text is its own reading view.
    assert (plans[2].path, plans[2].raw) == ("/uploads/数据.csv", "uploads/数据.csv")
    # A workbook has no reading view at all.
    assert (plans[3].path, plans[3].raw) == (None, "uploads/表.xlsx")
    assert (plans[4].path, plans[4].raw) == (None, None)
    for plan in plans:
        assert plan.path is None or not plan.path.endswith((".pdf", ".xlsx"))


# ------------------------------------------------------- production source


class _Store:
    """Object store with the calls deep research's ingestion uses."""

    bucket = "bisheng"
    tmp_bucket = "tmp"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.tmp: dict[str, bytes] = {}
        self.minio_client_sync = self

    def _of(self, bucket: str | None) -> dict[str, bytes]:
        return self.tmp if bucket == self.tmp_bucket else self.objects

    async def put_object_tmp(self, object_name: str, file: bytes, **_: Any) -> None:
        self.tmp[object_name] = file

    async def put_object(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self._of(bucket_name)[object_name] = file

    def put_object_sync(self, bucket_name: str = None, object_name: str = None, file: bytes = b"", **_: Any) -> None:
        self._of(bucket_name)[object_name] = file

    async def get_object(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self._of(bucket_name)[object_name]

    def get_object_sync(self, bucket_name: str = None, object_name: str = None) -> bytes:
        return self._of(bucket_name)[object_name]

    async def object_exists(self, bucket_name: str = None, object_name: str = None) -> bool:
        return object_name in self._of(bucket_name)

    async def copy_object(self, source_object: str, dest_object: str, source_bucket: str, dest_bucket: str) -> None:
        self._of(dest_bucket)[dest_object] = self._of(source_bucket)[source_object]


@pytest.fixture
def parse_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """The Redis parse state (``linsight_file:{file_id}``) as a dict."""
    state: dict[str, dict] = {}

    async def set_state(file_id: str, value: dict) -> None:
        state[file_id] = dict(value)

    async def get_state(file_id: str) -> dict | None:
        return state.get(file_id)

    monkeypatch.setattr(direct_attachments, "_set_state", set_state)
    monkeypatch.setattr(direct_attachments, "_get_state", get_state)
    return state


def _fake_parser(store: _Store, gate: asyncio.Event | None = None, *, original: bytes | None = None):
    """Stands for ``LinsightWorkbenchImpl._parse_file``: markdown (and the original) into the temp bucket."""

    async def parse(invoke_user_id: int, file_id: str, file_path: str, original_filename: str) -> dict:
        if gate is not None:
            await gate.wait()
        store.tmp[f"{file_id}.md"] = BODY.encode()
        result = {
            "file_id": file_id,
            "original_filename": original_filename,
            "parsing_status": "completed",
            "markdown_filename": f"{file_id}.md",
            "markdown_file_path": f"{file_id}.md",
        }
        if original is not None:
            ext = original_filename.rsplit(".", 1)[-1]
            store.tmp[f"{file_id}_original.{ext}"] = original
            result["original_file_path"] = f"{file_id}_original.{ext}"
        return result

    return parse


def _upload_payload(file: dict) -> dict:
    return {"filepath": file["filepath"], "filename": file["file_name"], "file_id": file["file_id"]}


async def test_upload_starts_parsing(monkeypatch: pytest.MonkeyPatch, parse_state):
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    store = _Store()
    gate = asyncio.Event()
    downloads: list[str] = []

    async def download(path: str):
        downloads.append(path)
        return "/nonexistent/a.docx", "a.docx"

    switch = {"on": False}

    async def enabled(tenant_id: int | None) -> bool:
        return switch["on"]

    monkeypatch.setattr(direct_attachments, "_unified_runtime_enabled", enabled)
    monkeypatch.setattr(direct_attachments, "async_file_download", download)
    monkeypatch.setattr(LinsightWorkbenchImpl, "_parse_file", _fake_parser(store, gate))

    # Switch off: the upload does nothing new.
    assert await direct_attachments.start_upload_parsing(_upload_payload(DOCX), user_id=USER, tenant_id=TENANT) is False
    assert parse_state == {} and downloads == [] and not direct_attachments._PARSE_TASKS

    # Switch on: the state says "running" as soon as the upload returns.
    switch["on"] = True
    assert await direct_attachments.start_upload_parsing(_upload_payload(DOCX), user_id=USER, tenant_id=TENANT) is True
    assert parse_state[DOCX["file_id"]]["parsing_status"] == "running"
    source = direct_attachments.WorkspaceAttachmentSource(object_store=lambda: _async(store), **LIMITS)
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, files=[DOCX])
    assert await source.ready(ctx, DOCX) is False

    gate.set()
    await asyncio.gather(*direct_attachments._PARSE_TASKS)
    assert parse_state[DOCX["file_id"]]["parsing_status"] == "completed"
    assert downloads == [DOCX["filepath"]]
    assert await source.ready(ctx, DOCX) is True

    # The run copies the parsed view into the workspace of the conversation; nothing is parsed again.
    entry = await source.ingest(ctx, DOCX, set())
    assert entry["workspace_path"] == "/uploads/a.md" and entry["valid"] is True
    assert store.objects[f"workspace/{CID}/uploads/a.md"] == BODY.encode()
    assert await source.text(ctx, entry) == BODY
    assert downloads == [DOCX["filepath"]]


async def _async(value: Any) -> Any:
    return value


async def test_ingest_waits_for_the_upload_parse(monkeypatch: pytest.MonkeyPatch, parse_state):
    """A run that starts before the upload parse ends waits for it; it does not parse a second time."""
    store = _Store()
    parse_state[DOCX["file_id"]] = {"file_id": DOCX["file_id"], "parsing_status": "running", "started_at": 1000.0}
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            store.tmp["x.md"] = BODY.encode()
            parse_state[DOCX["file_id"]] = {
                "file_id": DOCX["file_id"],
                "original_filename": "a.docx",
                "parsing_status": "completed",
                "markdown_file_path": "x.md",
            }

    source = direct_attachments.WorkspaceAttachmentSource(
        object_store=lambda: _async(store), sleep=sleep, clock=lambda: 1001.0, **LIMITS
    )
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, files=[DOCX])

    entry = await source.ingest(ctx, DOCX, set())

    assert len(sleeps) == 3
    assert entry["workspace_path"] == "/uploads/a.md"
    assert store.objects[f"workspace/{CID}/uploads/a.md"] == BODY.encode()


async def test_file_without_parse_state_is_parsed_by_the_run(monkeypatch: pytest.MonkeyPatch, parse_state):
    """Uploaded before the switch was on (or the state expired): deep research's daily-file ingestion."""
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    store = _Store()
    calls: list[tuple] = []

    async def ingest_daily(submit_file, chat_id, minio_client, user_id, used_names=None):
        calls.append((submit_file.file_url, chat_id, user_id))
        return {"file_id": submit_file.file_id, "original_filename": submit_file.file_name, "valid": True}

    monkeypatch.setattr(LinsightWorkbenchImpl, "_ingest_daily_file", ingest_daily)
    # A parse that started long ago and never reported is treated as dead.
    parse_state[PDF["file_id"]] = {"file_id": PDF["file_id"], "parsing_status": "running", "started_at": 0.0}
    source = direct_attachments.WorkspaceAttachmentSource(
        object_store=lambda: _async(store), clock=lambda: direct_attachments.PARSE_WAIT_SECONDS + 1.0, **LIMITS
    )
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, files=[DOCX, PDF])

    assert await source.ready(ctx, DOCX) is False
    await source.ingest(ctx, DOCX, set())
    await source.ingest(ctx, PDF, set())

    assert calls == [(DOCX["filepath"], CID, USER), (PDF["filepath"], CID, USER)]


async def test_binary_original_not_exposed(monkeypatch: pytest.MonkeyPatch, parse_state, tmp_path):
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    store = _Store()
    pdf_bytes = b"%PDF-1.7\n\x00\x01\x02\xff\xfe binary"
    parse = _fake_parser(store, original=pdf_bytes)
    parse_state[PDF["file_id"]] = await parse(USER, PDF["file_id"], "/nonexistent/b.pdf", "b.pdf")
    monkeypatch.setattr(LinsightWorkbenchImpl, "_should_keep_raw", classmethod(lambda cls, *a, **k: True))
    source = direct_attachments.WorkspaceAttachmentSource(object_store=lambda: _async(store), **LIMITS)
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, files=[PDF])
    plan = direct_attachments.plan_workspace_names([PDF])[0]

    entry = await source.ingest(ctx, PDF, set(plan.seed))

    # The names are the planned ones: reading view as .md, original beside it.
    assert entry["workspace_path"] == plan.path == "/uploads/b.md"
    assert entry["raw_workspace_path"] == "/" + plan.raw == "/uploads/b.pdf"
    listing = await direct_attachments.render_listing([entry], [], has_code_interpreter=False)
    assert "path: /uploads/b.md" in listing
    assert "path: /uploads/b.pdf" not in listing
    # Without a code tool the model is told it cannot open the original.
    assert "bisheng_code_interpreter" not in listing

    backend = WorkspaceBackend(
        minio=store, file_dir=str(tmp_path / "cache"), workspace_prefix=f"workspace/{CID}", create_cache_dir=False
    )
    refused = await backend.aread("/uploads/b.pdf")
    assert refused.error and refused.error.startswith(BINARY_READ_ERROR_PREFIX)
    readable = await backend.aread("/uploads/b.md")
    assert readable.error is None and BODY in readable.file_data["content"]
