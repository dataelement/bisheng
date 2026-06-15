"""TA-1: StreamEventMapper unit tests (F035 Track A, contract C1).

These tests are the *source of truth* for the LangGraph chunk -> BaseEvent
normalization layer. They program against the frozen C1 fixtures
(``test/linsight/fixtures/ws_events/*.json``) and the ExecStep schema in
``依赖与契约约定.md`` §2.

The mapper under test is a **pure translator**: it accepts
``(mode, chunk)`` tuples produced by
``agent.astream(stream_mode=["updates","messages","values"], subgraphs=True)``
and yields 0..N ``BaseEvent`` instances. It touches neither Redis nor MySQL.

Covered (per task brief TA-1):
- todo (write_todos) -> GenerateSubTask / TaskStart / TaskEnd
- tool call start/end -> ExecStep (call_id idempotent merge)
- thinking -> ExecStep(step_type="thinking")
- subagent (subgraphs=True namespace) -> ExecStep(step_type="subagent")
- knowledge -> ExecStep(step_type="knowledge")
- __interrupt__ -> NeedUserInput
- terminal chunks (error / recursion limit)
- task_id stability: md5(svid+":"+content)[:8] + 3-level diff alignment
- call_id idempotent merge of start/end
- namespace subgraph归并
- ctx.terminated: duplicate terminal only first frame
- orphan end frame buffering + later merge
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from bisheng.linsight.domain.services.stream_event_mapper import (
    StreamContext,
    StreamEventMapper,
)
from bisheng_langchain.linsight.event import (
    ExecStep,
    GenerateSubTask,
    NeedUserInput,
    TaskEnd,
    TaskStart,
)

SVID = "1f3c9a20-7b4e-4d11-9c3a-0a1b2c3d4e5f"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ws_events"


def _task_id(content: str) -> str:
    return hashlib.md5(f"{SVID}:{content}".encode()).hexdigest()[:8]


@pytest.fixture
def mapper() -> StreamEventMapper:
    return StreamEventMapper(svid=SVID)


# --------------------------------------------------------------------------
# task_id stability (design §3.3.1)
# --------------------------------------------------------------------------


class TestTaskIdStability:
    def test_first_write_todos_generates_md5_ids(self, mapper: StreamEventMapper):
        chunk = {
            "tools": {
                "todos": [
                    {"content": "收集季度财报数据", "status": "pending"},
                    {"content": "生成分析报告", "status": "pending"},
                ]
            }
        }
        events = mapper.normalize("updates", chunk)
        gen = [e for e in events if isinstance(e, GenerateSubTask)]
        assert len(gen) == 1
        subtasks = gen[0].subtask
        assert subtasks[0]["id"] == _task_id("收集季度财报数据")
        assert subtasks[1]["id"] == _task_id("生成分析报告")

    def test_update_by_exact_content_match_keeps_id(self, mapper: StreamEventMapper):
        first = {"tools": {"todos": [{"content": "任务A", "status": "pending"}]}}
        mapper.normalize("updates", first)
        tid = _task_id("任务A")

        # status flip, same content -> same id, becomes TaskStart
        second = {"tools": {"todos": [{"content": "任务A", "status": "in_progress"}]}}
        events = mapper.normalize("updates", second)
        starts = [e for e in events if isinstance(e, TaskStart)]
        assert starts and starts[0].task_id == tid

    def test_update_by_positional_alignment_when_content_rewritten(self, mapper: StreamEventMapper):
        first = {"tools": {"todos": [{"content": "原始文案", "status": "pending"}]}}
        mapper.normalize("updates", first)
        tid = _task_id("原始文案")

        # content rewritten but same position + same status -> inherit id (level 2)
        second = {"tools": {"todos": [{"content": "被改写的文案", "status": "in_progress"}]}}
        events = mapper.normalize("updates", second)
        starts = [e for e in events if isinstance(e, TaskStart)]
        assert starts and starts[0].task_id == tid

    def test_brand_new_todo_gets_new_id(self, mapper: StreamEventMapper):
        first = {"tools": {"todos": [{"content": "任务A", "status": "pending"}]}}
        mapper.normalize("updates", first)
        second = {
            "tools": {
                "todos": [
                    {"content": "任务A", "status": "pending"},
                    {"content": "全新任务B", "status": "pending"},
                ]
            }
        }
        events = mapper.normalize("updates", second)
        gen = [e for e in events if isinstance(e, GenerateSubTask)]
        assert gen
        new_ids = [t["id"] for t in gen[0].subtask]
        assert _task_id("全新任务B") in new_ids

    def test_completed_todo_emits_task_end(self, mapper: StreamEventMapper):
        first = {"tools": {"todos": [{"content": "任务A", "status": "in_progress"}]}}
        mapper.normalize("updates", first)
        second = {"tools": {"todos": [{"content": "任务A", "status": "completed"}]}}
        events = mapper.normalize("updates", second)
        ends = [e for e in events if isinstance(e, TaskEnd)]
        assert ends and ends[0].task_id == _task_id("任务A")


# --------------------------------------------------------------------------
# ExecStep.task_id attribution (design §3.3.1 rule 4)
# --------------------------------------------------------------------------


class TestExecStepAttribution:
    def test_step_attributed_to_in_progress_todo(self, mapper: StreamEventMapper):
        mapper.normalize(
            "updates",
            {"tools": {"todos": [{"content": "任务A", "status": "in_progress"}]}},
        )
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "x"}}],
        )
        events = mapper.normalize("messages", (msg, {}))
        steps = [e for e in events if isinstance(e, ExecStep)]
        assert steps and steps[0].task_id == _task_id("任务A")

    def test_step_falls_back_to_svid_without_in_progress(self, mapper: StreamEventMapper):
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "x"}}],
        )
        events = mapper.normalize("messages", (msg, {}))
        steps = [e for e in events if isinstance(e, ExecStep)]
        assert steps and steps[0].task_id == SVID


# --------------------------------------------------------------------------
# call_id idempotent merge of tool start/end (design §3.4)
# --------------------------------------------------------------------------


class TestCallIdMerge:
    def test_tool_start_then_end_two_frames_same_call_id(self, mapper: StreamEventMapper):
        start_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_x", "name": "search", "args": {"q": "abc"}}],
        )
        start_events = [e for e in mapper.normalize("messages", (start_msg, {})) if isinstance(e, ExecStep)]
        assert len(start_events) == 1
        assert start_events[0].status == "start"
        assert start_events[0].call_id == "call_x"

        end_msg = ToolMessage(content="结果数据", tool_call_id="call_x", name="search")
        end_events = [e for e in mapper.normalize("messages", (end_msg, {})) if isinstance(e, ExecStep)]
        assert len(end_events) == 1
        assert end_events[0].status == "end"
        assert end_events[0].call_id == "call_x"
        assert end_events[0].output == "结果数据"
        # merged: name/params carried from the start frame
        assert end_events[0].name == "search"
        assert end_events[0].params == {"q": "abc"}

    def test_orphan_end_frame_buffered_then_merged(self, mapper: StreamEventMapper):
        # end frame arrives BEFORE start (event reordering, design §3.7)
        end_msg = ToolMessage(content="先到的结果", tool_call_id="call_y", name="search")
        early = [e for e in mapper.normalize("messages", (end_msg, {})) if isinstance(e, ExecStep)]
        # orphan end is buffered, no event emitted yet
        assert early == []

        start_msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_y", "name": "search", "args": {"q": "z"}}],
        )
        events = [e for e in mapper.normalize("messages", (start_msg, {})) if isinstance(e, ExecStep)]
        # both the start frame and the merged end frame are flushed
        statuses = sorted(e.status for e in events)
        assert statuses == ["end", "start"]
        end_ev = next(e for e in events if e.status == "end")
        assert end_ev.output == "先到的结果"


# --------------------------------------------------------------------------
# thinking step (design §3.3 step_type variants)
# --------------------------------------------------------------------------


class TestThinking:
    def test_reasoning_content_becomes_thinking_step(self, mapper: StreamEventMapper):
        chunk = AIMessageChunk(
            content="",
            additional_kwargs={"reasoning_content": "需要先对齐口径……"},
        )
        events = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)]
        assert events
        ev = events[0]
        assert ev.step_type == "thinking"
        assert ev.extra_info.get("is_thinking") is True
        assert "对齐口径" in (ev.output or "")


# --------------------------------------------------------------------------
# subagent namespace归并 (design §3.7, subgraphs=True)
# --------------------------------------------------------------------------


class TestSubagentNamespace:
    def test_namespace_propagates_to_exec_step(self, mapper: StreamEventMapper):
        # subgraphs=True -> chunk is (namespace, mode, chunk); mapper.normalize
        # receives the namespace via a tuple-aware path.
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_sub", "name": "search_kb", "args": {"q": "竞品"}}],
        )
        events = [
            e
            for e in mapper.normalize("messages", (msg, {}), namespace=("research_subagent:0",))
            if isinstance(e, ExecStep)
        ]
        assert events
        assert events[0].extra_info.get("namespace") == "research_subagent:0"


# --------------------------------------------------------------------------
# knowledge step type inference
# --------------------------------------------------------------------------


class TestKnowledge:
    def test_search_knowledge_tool_marked_knowledge(self, mapper: StreamEventMapper):
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "search_knowledge_base", "args": {"query": "x"}}],
        )
        events = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)]
        assert events
        assert events[0].step_type == "knowledge"


# --------------------------------------------------------------------------
# interrupt -> NeedUserInput (design §4.3)
# --------------------------------------------------------------------------


class TestInterrupt:
    def test_interrupt_chunk_becomes_need_user_input(self, mapper: StreamEventMapper):
        # set an in_progress task so NeedUserInput routes to it
        mapper.normalize(
            "updates",
            {"tools": {"todos": [{"content": "生成分析报告", "status": "in_progress"}]}},
        )
        tid = _task_id("生成分析报告")

        class _Interrupt:
            def __init__(self, value):
                self.value = value

        chunk = {
            "__interrupt__": (
                _Interrupt(
                    {
                        "reason": "请确认报告输出语言",
                        "params": {"options": ["中文", "English"]},
                    }
                ),
            )
        }
        events = mapper.normalize("updates", chunk)
        nui = [e for e in events if isinstance(e, NeedUserInput)]
        assert len(nui) == 1
        assert nui[0].task_id == tid
        assert nui[0].call_reason == "请确认报告输出语言"
        assert nui[0].step_type == "call_user_input"


# --------------------------------------------------------------------------
# terminal收口 + ctx.terminated dedup (design §3.5 / §3.7)
# --------------------------------------------------------------------------


class TestTermination:
    def test_recursion_limit_error_emits_terminal_only_once(self, mapper: StreamEventMapper):
        first = mapper.terminate(error="递归超限")
        assert first
        assert mapper.ctx.terminated is True

        # a second terminate call is suppressed (only first frame counts)
        second = mapper.terminate(error="二次终止")
        assert second == []

    def test_terminate_returns_error_and_terminated_pair(self, mapper: StreamEventMapper):
        out = mapper.terminate(error="boom")
        types = [t for t, _ in out]
        assert "error_message" in types
        assert "task_terminated" in types
        # task_terminated must be last
        assert types[-1] == "task_terminated"


# --------------------------------------------------------------------------
# fixtures alignment: ExecStep fields match the frozen C1 schema
# --------------------------------------------------------------------------


class TestFixturesAlignment:
    def test_exec_step_fixture_fields_are_supported(self):
        data = json.loads((FIXTURE_DIR / "step_types.json").read_text())
        required = {
            "call_id",
            "task_id",
            "name",
            "step_type",
            "status",
            "call_reason",
            "params",
            "output",
        }
        for step in data["steps"]:
            assert required.issubset(set(step["data"].keys()))

    def test_event_samples_cover_ten_types(self):
        data = json.loads((FIXTURE_DIR / "event_samples.json").read_text())
        types = {s["event_type"] for s in data["samples"]}
        assert len(types) == 10


# --------------------------------------------------------------------------
# StreamContext basic invariants
# --------------------------------------------------------------------------


class TestStreamContext:
    def test_context_starts_clean(self):
        ctx = StreamContext(svid=SVID)
        assert ctx.terminated is False
        assert ctx.current_in_progress_task_id is None
        assert ctx.open_calls == {}
        assert ctx.orphan_ends == {}
