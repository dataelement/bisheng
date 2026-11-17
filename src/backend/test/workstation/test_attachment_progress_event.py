"""F004 T036 / T057: the "reading attachments" progress event of a ``direct`` run (AC-51).

A direct run with attachments emits one ``tool_call`` start frame before anything
is parsed (within 2 s of ``run_started``, fake clock) and the matching end frame
when the attachments are in the workspace; without attachments it emits neither.

Since T057 (design 决策 12) the model request no longer waits for parsing: the
frame stays open while the answer runs, and a read of the attachment waits for it.

The real graph runs with a scripted model; Redis is fakeredis; the attachment
source is a fake that moves with the fake clock to stand for slow parsing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services.direct_attachments import AttachmentView
from bisheng.workstation.domain.services.direct_run import DirectRunContext
from test.workstation.test_direct_run import CID, TENANT, USER, _call, _Env

PARSE_SECONDS = 30.0
FILES = [{"filepath": "chat/a.docx", "file_name": "a.docx"}, {"filepath": "chat/b.pdf", "file_name": "b.pdf"}]
TEXT = "附件正文：合同金额 300 万"


@pytest.fixture
def make_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _make(script: list[Any]) -> _Env:
        return _Env(monkeypatch, tmp_path, script)

    return _make


def _progress_frames(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == direct_run.ATTACHMENT_TOOL_NAME]


class _SlowSource:
    """Attachments whose parsing has not finished when the run starts."""

    inline_chars = 4000
    inline_total_chars = 15000

    def __init__(self, env: Any, error: BaseException | None = None):
        self.env = env
        self.error = error
        self.calls: list[str] = []
        self.types_at_start: list[str] = []

    async def ready(self, ctx: DirectRunContext, file: dict) -> bool:
        return False

    async def visual(self, ctx: DirectRunContext) -> bool:
        return False

    async def ingest(self, ctx: DirectRunContext, file: dict, used_names: set[str]) -> dict:
        self.calls.append(file["file_name"])
        self.types_at_start = await self.env.types()
        if self.error is not None:
            raise self.error
        # Slow parsing: the watcher's ticks move the fake clock (and renew the lease).
        start = self.env.clock.now
        while self.env.clock.now < start + PARSE_SECONDS:
            await asyncio.sleep(0.001)
        stem = file["file_name"].rsplit(".", 1)[0]
        self.env.store.objects[f"workspace/{ctx.conversation_id}/uploads/{stem}.md"] = TEXT.encode()
        return {
            "file_id": stem,
            "original_filename": file["file_name"],
            "parsing_status": "completed",
            "valid": True,
            "workspace_path": f"/uploads/{stem}.md",
            "line_count": 1,
        }

    async def text(self, ctx: DirectRunContext, entry: dict) -> str | None:
        return TEXT


async def _submit_with_files(env: Any, text: str, files: list[dict]) -> DirectRunContext:
    ctx = await env.submit(text)
    ctx.files = list(files)
    return ctx


async def test_progress_event_before_parsing(make_env):
    # T057: the model asks for the attachment; the read waits for the parse.
    env = make_env([_call("read_file", {"file_path": "/uploads/a.md"}, "r1"), AIMessage(content="合同金额是 300 万")])
    source = _SlowSource(env)
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit_with_files(env, "合同金额是多少", FILES)

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert sorted(source.calls) == ["a.docx", "b.pdf"]
    events = await env.events()
    started = next(e for e in events if e["type"] == "run_started")
    frames = _progress_frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    start, end = frames
    assert start["data"]["call_id"] == end["data"]["call_id"]
    assert start["run_id"] == ctx.run_id
    # The start frame was on the Stream before parsing began.
    assert "tool_call" in source.types_at_start
    # Visible within 2 s of run_started; the end frame comes after the parsing time.
    assert int(start["ts"]) - int(started["ts"]) <= 2000
    assert int(end["ts"]) - int(start["ts"]) >= PARSE_SECONDS * 1000
    assert start["data"]["params"]["files"] == ["a.docx", "b.pdf"]
    # T057: the first request did not wait; it names the files and where they will be.
    first_user = next(m for m in env.model.inputs[0] if m.type == "human")
    assert "a.docx" in str(first_user.content) and "/uploads/a.md" in str(first_user.content)
    assert "合同金额 300 万" not in str(first_user.content)
    # The answer continues after reading: the read returned the parsed text.
    assert any(isinstance(m, ToolMessage) and "合同金额 300 万" in str(m.content) for m in env.model.inputs[-1])
    types = [e["type"] for e in events]
    assert types.index("tool_call") < types.index("text")
    assert types[-1] == "run_finished"
    # The projector hook gets both frames too.
    assert len(_progress_frames(env.hook_events)) == 2


async def test_no_event_without_attachment(make_env):
    env = make_env([AIMessage(content="你好")])
    source = _SlowSource(env)
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await env.submit("你好")

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert source.calls == []
    assert _progress_frames(await env.events()) == []


async def test_parse_failure_closes_frame_and_run_continues(make_env):
    # T057: an attachment that cannot be read no longer fails the run (deep
    # research's rule); the frame says which file failed and the model is told.
    env = make_env([AIMessage(content="这个附件读不了")])
    source = _SlowSource(env, error=RuntimeError("a.docx: 解析失败"))
    runner = env.make_runner(attachment_source=lambda ctx: source)
    ctx = await _submit_with_files(env, "看看附件", FILES[:1])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    events = await env.events()
    frames = _progress_frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert "a.docx" in frames[1]["data"]["output"]
    assert frames[1]["data"]["extra_info"]["error"]
    assert frames[1]["data"]["extra_info"]["failed"] == ["a.docx"]
    assert events[-1]["type"] == "run_finished"


def test_resume_does_not_read_attachments():
    ctx = DirectRunContext(
        conversation_id=CID, run_id="r-resume", tenant_id=TENANT, user_id=USER, files=FILES, is_resume=True
    )
    # A resume never re-reads attachments: the first execution already did.
    assert direct_run.attachments_to_read(ctx) == []
    fresh = DirectRunContext(conversation_id=CID, run_id="r-new", tenant_id=TENANT, user_id=USER, files=FILES)
    assert direct_run.attachments_to_read(fresh) == FILES
    # Entries without a filepath (upload in flight) are not read, like the legacy path.
    assert (
        direct_run.attachments_to_read(
            DirectRunContext(
                conversation_id=CID, run_id="r-x", tenant_id=TENANT, user_id=USER, files=[{"file_name": "x"}]
            )
        )
        == []
    )


def test_with_attachments_inlines_text_and_images():
    graph_input = {"messages": [{"role": "user", "content": "# 用户问题\n看图"}, {"role": "user", "content": "补充"}]}
    out = direct_run._with_attachments(
        graph_input, AttachmentView("<uploaded_files>索引</uploaded_files>", "正文", ["data:a"])
    )
    first = out["messages"][0]["content"]
    assert first[0]["type"] == "text" and "<uploaded_file_content>\n正文" in first[0]["text"]
    assert first[0]["text"].index("<uploaded_files>索引") < first[0]["text"].index("<uploaded_file_content>")
    assert first[1] == {"type": "image_url", "image_url": {"url": "data:a"}}
    assert out["messages"][1] == graph_input["messages"][1]
    assert direct_run._with_attachments(graph_input, None) is graph_input
