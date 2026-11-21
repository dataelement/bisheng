"""F004 (leftovers of T053): what a ``direct`` run must do around the model call.

* the local cache directory is removed when an execution ends (object storage
  is the source of truth, C8);
* the department concurrency slot is held only while the run executes (AC-22);
* the output-side content-safety scanner replaces a blocked answer.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from bisheng.common.errcode.workstation import DepartmentDailyChatConcurrentLimitError
from bisheng.workstation.domain.services import run_lease as rl
from bisheng.workstation.domain.services.direct_run import DirectRunContext
from test.workstation.test_direct_run import ASK, CID, _call, make_env  # noqa: F401

WRITE = _call("write_file", {"file_path": "/output/note.md", "content": "内容"}, "w1")


# --------------------------------------------------------------------------- #
# Local cache directory
# --------------------------------------------------------------------------- #


async def test_cache_dir_removed_at_run_end(make_env):  # noqa: F811
    seen: dict[str, bool] = {}

    async def after_write(messages):
        seen["dir_during_run"] = os.path.exists(env.file_dir)
        return AIMessage(content="写好了")

    env = make_env([WRITE, after_write])

    assert (await env.run(await env.submit("写一个文件"))).status == "finished"

    assert seen["dir_during_run"] is True
    assert not os.path.exists(env.file_dir)
    # Object storage keeps the file.
    assert f"workspace/{CID}/output/note.md" in env.store.objects


async def test_cache_dir_removed_when_run_parks(make_env):  # noqa: F811
    env = make_env([WRITE, ASK])

    assert (await env.run(await env.submit("写完再问我"))).status == "waiting"

    assert not os.path.exists(env.file_dir)
    assert f"workspace/{CID}/output/note.md" in env.store.objects


async def test_cache_dir_removed_before_conversation_is_handed_on(make_env):  # noqa: F811
    env = make_env([WRITE, AIMessage(content="写好了")])
    seen: dict[str, bool] = {}
    real_finish = env.dispatch.on_run_finished

    async def on_run_finished(conversation_id, run_id=None):
        # A relay run may start on this node right after this call.
        seen["dir_at_handover"] = os.path.exists(env.file_dir)
        return await real_finish(conversation_id, run_id)

    env.dispatch.on_run_finished = on_run_finished

    assert (await env.run(await env.submit("写一个文件"))).status == "finished"

    assert seen == {"dir_at_handover": False}


# --------------------------------------------------------------------------- #
# Department concurrency slot (AC-22)
# --------------------------------------------------------------------------- #


class _Slots:
    def __init__(self) -> None:
        self.held = 0
        self.log: list[str] = []
        self.reject = False

    @asynccontextmanager
    async def slot(self, ctx: DirectRunContext):
        if self.reject:
            raise DepartmentDailyChatConcurrentLimitError()
        self.held += 1
        self.log.append("acquire")
        try:
            yield
        finally:
            self.held -= 1
            self.log.append("release")


async def test_department_slot_held_only_while_running(make_env):  # noqa: F811
    slots = _Slots()
    seen: dict[str, int] = {}

    async def reply(messages):
        seen["held_at_model_call"] = slots.held
        return AIMessage(content="你好")

    env = make_env([reply])
    runner = env.make_runner(department_slot=slots.slot)

    assert (await env.run(await env.submit("你好"), runner)).status == "finished"

    assert seen == {"held_at_model_call": 1}
    assert slots.held == 0 and slots.log == ["acquire", "release"]


async def test_department_slot_released_while_waiting_for_answer(make_env):  # noqa: F811
    slots = _Slots()
    env = make_env([ASK, AIMessage(content="好的，蓝色")])
    runner = env.make_runner(department_slot=slots.slot)

    assert (await env.run(await env.submit("帮我选颜色"), runner)).status == "waiting"
    assert (await env.state()).status == rl.STATUS_WAITING
    # AC-22: a run that waits for the user holds no department slot.
    assert slots.held == 0 and slots.log == ["acquire", "release"]

    assert (await env.run(await env.submit("蓝色"), runner)).status == "finished"
    assert slots.held == 0 and slots.log == ["acquire", "release", "acquire", "release"]


async def test_department_slot_released_on_failure_and_stop(make_env):  # noqa: F811
    slots = _Slots()
    env = make_env([RuntimeError("model down")])
    runner = env.make_runner(department_slot=slots.slot)

    assert (await env.run(await env.submit("你好"), runner)).status == "failed"
    assert slots.held == 0

    async def stopped(messages):
        await env.lease.request_stop(ctx.run_id, CID)
        await asyncio.sleep(30)

    env.model.script = [stopped]
    env.model.calls = 0
    ctx = await env.submit("再来一次")
    assert (await env.run(ctx, runner)).status == "stopped"
    assert slots.held == 0


async def test_department_refusal_fails_before_the_model(make_env):  # noqa: F811
    slots = _Slots()
    slots.reject = True
    env = make_env([AIMessage(content="不应该被调用")])
    runner = env.make_runner(department_slot=slots.slot)

    assert (await env.run(await env.submit("你好"), runner)).status == "failed"

    assert env.model.calls == 0
    failed = [e for e in await env.events() if e["type"] == "run_failed"]
    assert len(failed) == 1
    # Today's error of the legacy daily chat.
    assert failed[0]["data"]["code"] == DepartmentDailyChatConcurrentLimitError.Code
    assert (await env.state()).status == rl.STATUS_IDLE


# --------------------------------------------------------------------------- #
# Output-side content safety
# --------------------------------------------------------------------------- #


class _Scanner:
    """The interface of ``StreamContentSafetyScanner``: a hit once the word was fed."""

    def __init__(self, word: str, auto_reply: str = "该内容无法展示"):
        self.word = word
        self.auto_reply = auto_reply
        self.buffer = ""

    def _check(self):
        if self.word in self.buffer:
            return SimpleNamespace(auto_reply=self.auto_reply, enabled=True, hits=[self.word])
        return None

    def feed(self, delta: str):
        self.buffer += delta
        return self._check()

    def finish(self):
        return self._check()


async def test_output_safety_hit_ends_the_run_with_the_replacement(make_env):  # noqa: F811
    env = make_env([AIMessage(content="这是一段包含违禁词的回答"), AIMessage(content="不应该有第二次调用")])
    marked: list[DirectRunContext] = []

    async def mark(ctx: DirectRunContext) -> None:
        marked.append(ctx)

    runner = env.make_runner(safety_scanner=lambda ctx: _Scanner("违禁词"), mark_violation=mark)
    ctx = await env.submit("说点什么")

    outcome = await env.run(ctx, runner)

    assert outcome.status == "finished" and outcome.content_safety is True
    events = await env.events()
    terminal = events[-1]
    assert terminal["type"] == "run_finished"
    assert terminal["data"] == {"content_safety": True, "auto_reply": "该内容无法展示"}
    assert [e["type"] for e in events].count("run_finished") == 1
    # The question row and the session are marked before the terminal event.
    assert [c.run_id for c in marked] == [ctx.run_id]
    # The hooks (persistence projector) see the same terminal event.
    assert env.hook_events[-1]["type"] == "run_finished"
    assert env.hook_events[-1]["data"]["content_safety"] is True
    assert env.finished == [(CID, ctx.run_id)]
    assert (await env.state()).status == rl.STATUS_IDLE


async def test_output_safety_stops_the_run_before_the_next_step(make_env):  # noqa: F811
    env = make_env(
        [
            _call("write_file", {"file_path": "/output/a.md", "content": "x"}, "w1", content="先说违禁词再写文件"),
            AIMessage(content="不应该有第二次调用"),
        ]
    )
    runner = env.make_runner(safety_scanner=lambda ctx: _Scanner("违禁词"), mark_violation=_noop)

    outcome = await env.run(await env.submit("说点什么"), runner)

    assert outcome.content_safety is True
    assert env.model.calls == 1


async def test_clean_answer_passes_the_scanner(make_env):  # noqa: F811
    env = make_env([AIMessage(content="正常的回答")])
    marked: list = []

    async def mark(ctx: DirectRunContext) -> None:
        marked.append(ctx)

    runner = env.make_runner(safety_scanner=lambda ctx: _Scanner("违禁词"), mark_violation=mark)

    outcome = await env.run(await env.submit("你好"), runner)

    assert outcome.status == "finished" and outcome.content_safety is False
    terminal = (await env.events())[-1]
    assert terminal["type"] == "run_finished"
    assert "content_safety" not in (terminal.get("data") or {})
    assert marked == []


async def _noop(ctx: DirectRunContext) -> None:
    return None


async def test_no_scanner_when_content_safety_is_off(make_env):  # noqa: F811
    env = make_env([AIMessage(content="这是一段包含违禁词的回答")])
    runner = env.make_runner(safety_scanner=lambda ctx: None)

    outcome = await env.run(await env.submit("说点什么"), runner)

    assert outcome.status == "finished" and outcome.content_safety is False


async def test_projector_stores_the_replacement_as_the_legacy_row(monkeypatch: pytest.MonkeyPatch):
    import json

    from bisheng.linsight.domain.schemas import run_events
    from bisheng.workstation.domain.services import chat_service
    from bisheng.workstation.domain.services.content_safety import blocked_answer_payload
    from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

    rows: list = []

    async def ainsert_one(row):
        row.id = 100 + len(rows)
        rows.append(row)
        return row

    async def save_message_citations(**kwargs):
        return None

    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", ainsert_one)
    monkeypatch.setattr(chat_service, "save_message_citations", save_message_citations)
    projector = DirectRunProjector(run_id="run-1", conversation_id=CID, user_id=7, sender="DeepSeek")

    for event in (
        run_events.make_event(run_events.THINKING, run_events.TextData(text="想一想", call_id="c1")),
        run_events.make_event(run_events.TEXT, run_events.TextData(text="这是一段包含违禁词的回答")),
        run_events.make_event(run_events.RUN_FINISHED, {"content_safety": True, "auto_reply": "该内容无法展示"}),
    ):
        await projector.on_event(event)

    assert len(rows) == 1
    row = rows[0]
    # Same stored answer as ``persist_safety_replacement``: only the auto reply.
    assert json.loads(row.message) == blocked_answer_payload("该内容无法展示")
    assert json.loads(row.extra) == {"content_safety": True, "run_id": "run-1"}
    assert row.category == "agent_answer" and row.type == "end"
