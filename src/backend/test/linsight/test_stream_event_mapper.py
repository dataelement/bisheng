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
- subagent: only the main-graph ``task`` tool -> ExecStep(step_type="subagent");
  namespaced (subagent-internal) tools keep their real type + carry ns (B1)
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
# ExecStep.task_id attribution — B2 段流重构 (2026-06): EVERY main-graph step
# lands in the single session bucket (id == svid). The implicit in_progress
# cursor is gone; steps are NEVER attributed to a todo. write_todos is only the
# segment boundary, not an attribution signal.
# --------------------------------------------------------------------------


class TestExecStepAttribution:
    def test_step_lands_in_session_bucket_even_with_in_progress_todo(self, mapper: StreamEventMapper):
        # Core B2 inversion: even while a todo is in_progress, the step's task_id
        # is svid (NOT the todo's id). No more time-cursor.
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
        assert steps and steps[0].task_id == SVID

    def test_step_lands_in_session_bucket_without_todos(self, mapper: StreamEventMapper):
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "search", "args": {"q": "x"}}],
        )
        events = mapper.normalize("messages", (msg, {}))
        steps = [e for e in events if isinstance(e, ExecStep)]
        assert steps and steps[0].task_id == SVID

    def test_thinking_lands_in_session_bucket(self, mapper: StreamEventMapper):
        # thinking rows follow the same rule, even with an in_progress todo.
        mapper.normalize(
            "updates",
            {"tools": {"todos": [{"content": "任务A", "status": "in_progress"}]}},
        )
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "想一下"})
        ev = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)][0]
        assert ev.step_type == "thinking"
        assert ev.task_id == SVID

    def test_subagent_internal_step_lands_in_session_bucket(self, mapper: StreamEventMapper):
        # A subagent-internal tool (namespaced) is identified by extra_info.namespace,
        # NOT by task_id — its task_id is still the session bucket (svid). This is
        # what keeps R3 (subagent flattening) working after B2.
        mapper.normalize(
            "updates",
            {"tools": {"todos": [{"content": "任务A", "status": "in_progress"}]}},
        )
        sub_ns = ("tools:9c3a0a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b",)
        msg = AIMessage(content="", tool_calls=[{"id": "call_sub", "name": "search_kb", "args": {"q": "x"}}])
        ev = [e for e in mapper.normalize("messages", (msg, {}), namespace=sub_ns) if isinstance(e, ExecStep)][0]
        assert ev.task_id == SVID
        assert ev.extra_info.get("namespace") == sub_ns[0]


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

    def test_streaming_thinking_deltas_share_one_call_id(self, mapper: StreamEventMapper):
        # ``messages`` mode streams thinking token-by-token: each chunk carries a
        # *delta*, not the accumulated text. All deltas of one contiguous thinking
        # stream must collapse into a single step (one call_id) so the frontend
        # merges them into one ThinkingRow instead of one row per token.
        deltas = ["让", "我", "想想"]
        call_ids = []
        for d in deltas:
            chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": d})
            steps = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)]
            assert len(steps) == 1
            call_ids.append(steps[0].call_id)
        assert len(set(call_ids)) == 1, f"expected one stable call_id, got {call_ids}"

    def test_thinking_segments_split_by_intervening_step(self, mapper: StreamEventMapper):
        # A new thinking stream that resumes *after* a tool call is a distinct
        # block and must get its own call_id, so it renders as a new row below
        # the tool — not glued onto the earlier thinking row.
        first = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先查资料"})
        id_a = [e for e in mapper.normalize("messages", (first, {})) if isinstance(e, ExecStep)][0].call_id

        tool_msg = AIMessage(content="", tool_calls=[{"id": "call_z", "name": "search", "args": {}}])
        mapper.normalize("messages", (tool_msg, {}))

        second = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "再总结"})
        id_b = [e for e in mapper.normalize("messages", (second, {})) if isinstance(e, ExecStep)][0].call_id

        assert id_a != id_b

    def test_parallel_thinking_streams_do_not_interleave(self, mapper: StreamEventMapper):
        # Parallel subagents (subgraphs=True) interleave their token streams. With a
        # single shared thinking call_id every subagent's reasoning collapsed into one
        # row, so the frontend (merge-by-call_id) concatenated them in ARRIVAL order
        # producing char-level garble ("The user用户 wants要求..."). The segment must
        # be keyed by namespace: each namespace accumulates in its own call_id and a
        # peer's delta never reuses it.
        ns_a = ("tools:aaaaaaaa-0000-0000-0000-000000000000",)
        ns_b = ("tools:bbbbbbbb-1111-1111-1111-111111111111",)
        # Interleave A/B deltas exactly as a burst-parallel stream would arrive.
        script = [
            (ns_a, "The user"),
            (ns_b, "用户"),
            (ns_a, " wants"),
            (ns_b, "要求"),
            (ns_a, " to research"),
            (ns_b, "调研"),
        ]
        by_call_id: dict[str, str] = {}
        ns_to_call_id: dict[str, str] = {}
        for ns, delta in script:
            chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": delta})
            step = [e for e in mapper.normalize("messages", (chunk, {}), namespace=ns) if isinstance(e, ExecStep)][0]
            by_call_id[step.call_id] = by_call_id.get(step.call_id, "") + (step.output or "")
            ns_to_call_id.setdefault(ns[0], step.call_id)

        # Each namespace owns a DISTINCT, STABLE call_id...
        assert ns_to_call_id[ns_a[0]] != ns_to_call_id[ns_b[0]]
        assert len(by_call_id) == 2
        # ...and each row's text is coherent (in-order), with NO cross-contamination.
        assert by_call_id[ns_to_call_id[ns_a[0]]] == "The user wants to research"
        assert by_call_id[ns_to_call_id[ns_b[0]]] == "用户要求调研"

    def test_main_graph_thinking_isolated_from_subagent(self, mapper: StreamEventMapper):
        # Main-graph thinking (ns None) must not share a segment with a subagent's
        # interleaved thinking either — same root cause, the ns=None ("") key.
        sub_ns = ("tools:cccccccc-2222-2222-2222-222222222222",)
        main = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "主图思考"})
        main_id = [e for e in mapper.normalize("messages", (main, {})) if isinstance(e, ExecStep)][0].call_id
        sub = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "子代理思考"})
        sub_id = [e for e in mapper.normalize("messages", (sub, {}), namespace=sub_ns) if isinstance(e, ExecStep)][
            0
        ].call_id
        assert main_id != sub_id


# --------------------------------------------------------------------------
# subagent namespace归并 (design §3.7, subgraphs=True)
# --------------------------------------------------------------------------


class TestSubagentNamespace:
    def test_namespace_propagates_to_exec_step(self, mapper: StreamEventMapper):
        # subgraphs=True -> chunk is (namespace, mode, chunk); mapper.normalize
        # receives the namespace via a tuple-aware path. ``tools:<uuid>`` is the
        # real flat subgraph namespace form deepagents emits.
        sub_ns = ("tools:9c3a0a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b",)
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_sub", "name": "search_kb", "args": {"q": "竞品"}}],
        )
        events = [e for e in mapper.normalize("messages", (msg, {}), namespace=sub_ns) if isinstance(e, ExecStep)]
        assert events
        # B1: namespace only rides in extra_info for grouping; it does NOT rewrite
        # step_type to "subagent" — an internal tool keeps its real (tool) type.
        assert events[0].step_type == "tool"
        assert events[0].extra_info.get("namespace") == sub_ns[0]

    def test_namespaced_knowledge_keeps_knowledge_type(self, mapper: StreamEventMapper):
        # A subagent-internal knowledge search keeps step_type="knowledge" (B1).
        sub_ns = ("tools:9c3a0a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b",)
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "call_sub_kb", "name": "search_knowledge_base", "args": {"query": "竞品"}}],
        )
        ev = next(e for e in mapper.normalize("messages", (msg, {}), namespace=sub_ns) if isinstance(e, ExecStep))
        assert ev.step_type == "knowledge"
        assert ev.extra_info.get("namespace") == sub_ns[0]


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
        # B2: even with an in_progress todo, the interrupt routes to the session
        # bucket (svid), not the todo — the in_progress cursor is gone.
        mapper.normalize(
            "updates",
            {"tools": {"todos": [{"content": "生成分析报告", "status": "in_progress"}]}},
        )

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
        assert nui[0].task_id == SVID
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
        assert ctx.open_calls == {}
        assert ctx.orphan_ends == {}


# --------------------------------------------------------------------------
# pseudo tool-call written into reasoning text (偶现) is filtered from thinking
# --------------------------------------------------------------------------


class TestPseudoToolCallFilter:
    def test_pseudo_tool_call_stripped_from_reasoning(self, mapper: StreamEventMapper):
        msg = AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": '让我调用工具检索一下。\nplay_search\n{"search_query": "黄河历史 改道次数", "num_results": 5}'
            },
        )
        ev = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)][0]
        assert ev.step_type == "thinking"
        assert "让我调用工具检索一下。" in ev.output
        assert "play_search" not in ev.output
        assert "search_query" not in ev.output

    def test_normal_reasoning_is_untouched(self, mapper: StreamEventMapper):
        text = "先分析用户意图，再给出结论。"
        msg = AIMessage(content="", additional_kwargs={"reasoning_content": text})
        ev = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)][0]
        assert ev.output == text

    def test_pseudo_like_tail_with_invalid_json_is_kept(self, mapper: StreamEventMapper):
        # identifier + braces at the tail, but the body is not valid JSON -> keep it
        text = "思考过程\nfoo\n{bar baz}"
        msg = AIMessage(content="", additional_kwargs={"reasoning_content": text})
        ev = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)][0]
        assert ev.output == text


# --------------------------------------------------------------------------
# reasoning-model <think>/</think> boundary markers leaking into the narration
# (qwen3.5 & co.). The markers must be stripped, the reasoning kept, and a
# marker-only chunk must NOT emit an (empty) thinking row.
# --------------------------------------------------------------------------


class TestThinkTagStripping:
    def test_think_markers_stripped_keeping_reasoning(self, mapper: StreamEventMapper):
        msg = AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "<think>\n先梳理两个知识库\n</think>"},
        )
        ev = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)][0]
        assert ev.step_type == "thinking"
        assert "先梳理两个知识库" in ev.output
        assert "<think" not in ev.output
        assert "</think" not in ev.output

    def test_marker_only_chunk_emits_no_thinking_step(self, mapper: StreamEventMapper):
        # A lone opening marker (its own streamed delta) reduces to whitespace and
        # must not surface as a bare "<think>" narration row (the reported bug).
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "<think>"})
        steps = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)]
        assert steps == []

    def test_stream_truncated_open_marker_emits_no_step(self, mapper: StreamEventMapper):
        # The screenshot showed a half tag "<think" (closing ">" split off across
        # chunks). It too must be swallowed, not shown.
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "<think"})
        steps = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)]
        assert steps == []

    def test_reasoning_delta_carrying_trailing_close_marker_is_cleaned(self, mapper: StreamEventMapper):
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "得出结论</think>"})
        ev = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)][0]
        assert ev.output == "得出结论"

    def test_marker_only_chunk_does_not_break_segment_continuity(self, mapper: StreamEventMapper):
        # <think> arrives as its own delta (no step), then the reasoning streams:
        # the reasoning still gets a single thinking row (the swallowed marker must
        # not have reset/closed the not-yet-open segment in a harmful way).
        open_marker = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "<think>"})
        assert [e for e in mapper.normalize("messages", (open_marker, {})) if isinstance(e, ExecStep)] == []

        body = ["分析", "问题"]
        call_ids = []
        for d in body:
            chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": d})
            step = [e for e in mapper.normalize("messages", (chunk, {})) if isinstance(e, ExecStep)][0]
            call_ids.append(step.call_id)
        assert len(set(call_ids)) == 1, f"reasoning after a swallowed marker must share one row, got {call_ids}"


# --------------------------------------------------------------------------
# subagent delegation: only the `task` tool is a delegation; namespaced
# internal tools keep their real type (regression: ls/glob shown as 子智能体)
# --------------------------------------------------------------------------


class TestSubagentDelegation:
    def test_task_tool_is_subagent(self, mapper: StreamEventMapper):
        msg = AIMessage(content="", tool_calls=[{"id": "c1", "name": "task", "args": {"description": "调研"}}])
        ev = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)][0]
        assert ev.step_type == "subagent"
        # B2: literal "task" is reshaped to the delegated subagent name and the
        # delegation goal is carried into call_reason + extra_info["delegate_goal"].
        assert ev.name == "general-purpose"
        assert ev.call_reason == "调研"
        assert ev.extra_info.get("delegate_goal") == "调研"

    def test_namespaced_internal_tool_is_not_subagent(self, mapper: StreamEventMapper):
        msg = AIMessage(content="", tool_calls=[{"id": "c2", "name": "glob", "args": {"pattern": "*.md"}}])
        events = [
            e
            for e in mapper.normalize("messages", (msg, {}), namespace=("general-purpose:0",))
            if isinstance(e, ExecStep)
        ]
        assert events[0].step_type == "tool"
        # namespace still rides along so the UI can attribute it to its owner
        assert events[0].extra_info.get("namespace") == "general-purpose:0"


class TestStreamedDelegationArgs:
    """A `task` delegation whose args stream across token-delta tool_call_chunks
    (DeepSeek et al.) must still recover its goal. Before the reassembly fix the
    start frame was built from the first, argless chunk, so delegate_goal was '',
    making the subagent indistinguishable from a plain deep-thinking segment.
    """

    @staticmethod
    def _arg_delta(name: str, args: str, cid: str, index: int = 0) -> AIMessageChunk:
        """An AIMessageChunk carrying ONE tool_call_chunks arg-string delta.

        Mirrors the real stream: only the first delta of a call carries name+id
        (with args still empty); later deltas carry id='' arg-string fragments.
        """
        return AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": name, "args": args, "id": cid, "index": index, "type": "tool_call_chunk"}],
        )

    def test_streamed_task_args_recover_goal(self, mapper: StreamEventMapper):
        # chunk 1: name+id, args still empty -> argless start frame (goal '')
        c1 = self._arg_delta("task", "", "call_s1")
        s1 = [e for e in mapper.normalize("messages", (c1, {})) if isinstance(e, ExecStep)]
        assert s1 and s1[0].step_type == "subagent" and s1[0].call_id == "call_s1"
        assert s1[0].extra_info.get("delegate_goal") == ""  # goal not known yet

        # chunk 2: partial args JSON — buffer still incomplete, nothing emitted
        c2 = self._arg_delta("", '{"description": "调研数据中心光模块', "")
        assert [e for e in mapper.normalize("messages", (c2, {})) if isinstance(e, ExecStep)] == []

        # chunk 3: args JSON closes -> refreshed start frame carries the goal
        c3 = self._arg_delta("", '", "subagent_type": "general-purpose"}', "")
        s3 = [e for e in mapper.normalize("messages", (c3, {})) if isinstance(e, ExecStep)]
        assert len(s3) == 1
        ev = s3[0]
        # same call_id -> persistence upserts it over the argless start frame
        assert ev.call_id == "call_s1"
        assert ev.step_type == "subagent"
        assert ev.status == "start"
        assert ev.name == "general-purpose"  # subagent_type recovered from args
        assert ev.extra_info.get("delegate_goal") == "调研数据中心光模块"
        assert ev.call_reason == "调研数据中心光模块"

    def test_streamed_task_end_frame_carries_goal(self, mapper: StreamEventMapper):
        for delta in (
            self._arg_delta("task", "", "call_s2"),
            self._arg_delta("", '{"description": "调研竞争格局"}', ""),
        ):
            mapper.normalize("messages", (delta, {}))
        tool_msg = ToolMessage(content="子代理返回的调研摘要", tool_call_id="call_s2")
        end = [e for e in mapper.normalize("messages", (tool_msg, {})) if isinstance(e, ExecStep)]
        assert len(end) == 1
        assert end[0].status == "end"
        assert end[0].extra_info.get("delegate_goal") == "调研竞争格局"
        assert end[0].output == "子代理返回的调研摘要"

    def test_parallel_streamed_delegations_stay_separated(self, mapper: StreamEventMapper):
        # Two parallel task calls (indices 0 and 1) interleave their arg deltas;
        # each must reassemble against its own call_id.
        mapper.normalize("messages", (self._arg_delta("task", "", "call_a", index=0), {}))
        mapper.normalize("messages", (self._arg_delta("task", "", "call_b", index=1), {}))
        mapper.normalize("messages", (self._arg_delta("", '{"description": "任务A"}', "", index=0), {}))
        ev_b = [
            e
            for e in mapper.normalize("messages", (self._arg_delta("", '{"description": "任务B"}', "", index=1), {}))
            if isinstance(e, ExecStep)
        ]
        assert len(ev_b) == 1
        assert ev_b[0].call_id == "call_b"
        assert ev_b[0].extra_info.get("delegate_goal") == "任务B"

    def test_complete_args_in_one_chunk_still_works(self, mapper: StreamEventMapper):
        # Backward-compat: a provider that ships full args in one AIMessage (no
        # streaming) gets the goal at the start frame and triggers no refresh.
        msg = AIMessage(content="", tool_calls=[{"id": "c1", "name": "task", "args": {"description": "调研"}}])
        events = [e for e in mapper.normalize("messages", (msg, {})) if isinstance(e, ExecStep)]
        assert len(events) == 1  # exactly one start frame, no duplicate refresh
        assert events[0].extra_info.get("delegate_goal") == "调研"
