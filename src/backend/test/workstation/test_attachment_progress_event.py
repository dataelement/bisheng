"""F004 T036: the "reading attachments" progress event of a ``direct`` run (AC-51).

A direct run with attachments emits one ``tool_call`` start frame before the
attachments are parsed (within 2 s of ``run_started``, fake clock) and the
matching end frame after parsing; without attachments it emits neither.

The real graph runs with a scripted model; Redis is fakeredis; the parser is a
fake that moves the fake clock to stand for slow parsing.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from bisheng.workstation.domain.services import direct_run
from bisheng.workstation.domain.services.direct_run import AttachmentReading, DirectRunContext
from test.workstation.test_direct_run import CID, TENANT, USER, _Env

PARSE_SECONDS = 30.0
FILES = [{"filepath": "chat/a.docx", "file_name": "a.docx"}, {"filepath": "chat/b.pdf", "file_name": "b.pdf"}]


@pytest.fixture
def make_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _make(script: list[Any]) -> _Env:
        return _Env(monkeypatch, tmp_path, script)

    return _make


def _progress_frames(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "tool_call" and e["data"]["name"] == direct_run.ATTACHMENT_TOOL_NAME]


class _FakeParser:
    """Stands for ``_process_agent_files``: records what was on the Stream when it began."""

    def __init__(self, env: Any):
        self.env = env
        self.calls: list[DirectRunContext] = []
        self.types_at_start: list[str] = []

    async def __call__(self, ctx: DirectRunContext) -> AttachmentReading:
        self.calls.append(ctx)
        self.types_at_start = await self.env.types()
        # Slow parsing: the watcher's ticks move the fake clock (and renew the lease).
        start = self.env.clock.now
        while self.env.clock.now < start + PARSE_SECONDS:
            await asyncio.sleep(0.001)
        return AttachmentReading(file_context="附件正文：合同金额 300 万", files=list(ctx.files))


async def _submit_with_files(env: Any, text: str, files: list[dict]) -> DirectRunContext:
    ctx = await env.submit(text)
    ctx.files = list(files)
    return ctx


async def test_progress_event_before_parsing(make_env):
    env = make_env([AIMessage(content="合同金额是 300 万")])
    parser = _FakeParser(env)
    runner = env.make_runner(read_attachments=parser)
    ctx = await _submit_with_files(env, "合同金额是多少", FILES)

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert len(parser.calls) == 1
    events = await env.events()
    started = next(e for e in events if e["type"] == "run_started")
    frames = _progress_frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    start, end = frames
    assert start["data"]["call_id"] == end["data"]["call_id"]
    assert start["run_id"] == ctx.run_id
    # The start frame was on the Stream before parsing began.
    assert "tool_call" in parser.types_at_start
    # Visible within 2 s of run_started; the end frame comes after the parsing time.
    assert int(start["ts"]) - int(started["ts"]) <= 2000
    assert int(end["ts"]) - int(start["ts"]) >= PARSE_SECONDS * 1000
    assert start["data"]["params"]["files"] == ["a.docx", "b.pdf"]
    # The answer continues after reading: the model saw the parsed text.
    first_user = next(m for m in env.model.inputs[0] if m.type == "human")
    assert "合同金额 300 万" in str(first_user.content)
    types = [e["type"] for e in events]
    assert types.index("tool_call") < types.index("text")
    assert types[-1] == "run_finished"
    # The projector hook gets both frames too.
    assert len(_progress_frames(env.hook_events)) == 2


async def test_no_event_without_attachment(make_env):
    env = make_env([AIMessage(content="你好")])
    parser = _FakeParser(env)
    runner = env.make_runner(read_attachments=parser)
    ctx = await env.submit("你好")

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "finished"
    assert parser.calls == []
    assert _progress_frames(await env.events()) == []


async def test_parse_failure_closes_frame_and_fails_run(make_env):
    env = make_env([AIMessage(content="不应调用")])

    async def broken(ctx: DirectRunContext) -> AttachmentReading:
        raise RuntimeError("a.docx: 解析失败")

    runner = env.make_runner(read_attachments=broken)
    ctx = await _submit_with_files(env, "看看附件", FILES[:1])

    outcome = await env.run(ctx, runner=runner)

    assert outcome.status == "failed"
    events = await env.events()
    frames = _progress_frames(events)
    assert [f["data"]["status"] for f in frames] == ["start", "end"]
    assert "解析失败" in frames[1]["data"]["output"]
    assert frames[1]["data"]["extra_info"]["error"]
    assert events[-1]["type"] == "run_failed"
    assert env.model.calls == 0


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


async def test_default_reader_calls_legacy_parser(monkeypatch):
    """The default reader is ``_process_agent_files`` itself, with the run's model and user."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.workstation.domain.services import chat_service
    from bisheng.workstation.domain.services.workstation_service import WorkStationService

    ws_config = SimpleNamespace(models=[SimpleNamespace(id="m1", visual=True)], maxTokens=100)
    login_user = SimpleNamespace(user_id=USER, tenant_id=TENANT)
    parse = AsyncMock(return_value=("text", ["data:image/png;base64,xx"], FILES))
    monkeypatch.setattr(WorkStationService, "aget_config", AsyncMock(return_value=ws_config))
    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(return_value=login_user))
    monkeypatch.setattr(chat_service, "_process_agent_files", parse)
    ctx = DirectRunContext(conversation_id=CID, run_id="r1", tenant_id=TENANT, user_id=USER, model_id="m1", files=FILES)

    reading = await direct_run.DirectRunner()._default_read_attachments(ctx)

    assert reading == AttachmentReading("text", ["data:image/png;base64,xx"], FILES)
    data, model_info, user, config = parse.await_args.args
    assert data.files == FILES and model_info.visual is True and user is login_user and config is ws_config
    assert parse.await_args.kwargs == {"conversation_id": CID}


def test_with_attachments_inlines_text_and_images():
    graph_input = {"messages": [{"role": "user", "content": "# 用户问题\n看图"}, {"role": "user", "content": "补充"}]}
    out = direct_run._with_attachments(graph_input, AttachmentReading("正文", ["data:a"], []))
    first = out["messages"][0]["content"]
    assert first[0]["type"] == "text" and "<uploaded_file_content>\n正文" in first[0]["text"]
    assert first[1] == {"type": "image_url", "image_url": {"url": "data:a"}}
    assert out["messages"][1] == graph_input["messages"][1]
    assert direct_run._with_attachments(graph_input, None) is graph_input
