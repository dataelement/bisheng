"""``[Sn]`` handles in the streamed answer of a planned (deep research) run.

Before this, only the direct profile converted the handles in its ``text``
events (``DirectTurn.rewrite``); the planned profile wrote the model's raw
``[S3]`` into the event stream, so the answer streamed with literal handles
until the persisted answer replaced it.
"""

from __future__ import annotations

from types import SimpleNamespace

from bisheng.citation.domain.services.citation_handle_service import convert_handles_to_markers
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services.text_handle_rewriter import TextHandleRewriter
from bisheng.linsight.domain.task_exec import _UnifiedRun

HANDLES = {"S3": "websearch_aa11bb22:0", "S7": "knowledgesearch_18f5868b:1"}


def _text(text: str, **data) -> dict:
    return {"type": run_events.TEXT, "run_id": "r1", "data": {"text": text, **data}}


def _tool_call() -> dict:
    return {"type": run_events.TOOL_CALL, "data": {"name": "web_search", "call_id": "c1"}}


def _joined_text(events: list[dict]) -> str:
    return "".join(e["data"]["text"] for e in events if e["type"] == run_events.TEXT)


class TestTextHandleRewriter:
    def test_split_handle_is_converted_and_tail_flushed_before_the_next_event(self):
        rw = TextHandleRewriter(dict(HANDLES))
        out = []
        for piece in ["宁德时代发布新电池[S", "3]，产能扩张[S7", "]"]:
            out += rw.rewrite(_text(piece))
        out += rw.rewrite(_tool_call())
        assert _joined_text(out) == convert_handles_to_markers("宁德时代发布新电池[S3]，产能扩张[S7]", HANDLES).text
        assert "[S" not in _joined_text(out)
        assert out[-1]["type"] == run_events.TOOL_CALL

    def test_subagent_text_passes_through(self):
        rw = TextHandleRewriter(dict(HANDLES))
        event = _text("[S3]", namespace="researcher")
        assert rw.rewrite(event) == [event]

    def test_flush_without_pending_text_is_empty(self):
        assert TextHandleRewriter(dict(HANDLES)).flush() == []


def _planned_run(scope) -> tuple[_UnifiedRun, list[dict]]:
    run = object.__new__(_UnifiedRun)
    written: list[dict] = []

    async def emit(event: dict) -> None:
        written.append(event)

    run.writer = SimpleNamespace(emit=emit)
    run.lease_lost = False
    run.conversation_id = "conv-1"
    run.redis = None
    run.text = None
    run.bind_citation_scope(scope)
    return run, written


class TestPlannedRunEmit:
    async def test_planned_text_events_carry_citation_markers(self):
        run, written = _planned_run(SimpleNamespace(enabled=True, handles=dict(HANDLES)))
        for piece in ["结论[S", "3]。"]:
            await run.emit(_text(piece))
        await run.emit({"type": run_events.RUN_FINISHED, "data": {}})
        assert _joined_text(written) == convert_handles_to_markers("结论[S3]。", HANDLES).text
        assert written[-1]["type"] == run_events.RUN_FINISHED

    async def test_handles_registered_during_the_run_are_seen(self):
        scope = SimpleNamespace(enabled=True, handles={})
        run, written = _planned_run(scope)
        scope.handles.update(HANDLES)  # a search tool allocated the handle after binding
        await run.emit(_text("见[S7]"))
        await run.emit(_tool_call())
        assert _joined_text(written) == convert_handles_to_markers("见[S7]", HANDLES).text

    async def test_verbatim_contract_passes_text_through(self):
        run, written = _planned_run(SimpleNamespace(enabled=False, handles=dict(HANDLES)))
        event = _text("原样[S3]")
        await run.emit(event)
        assert written == [event]
