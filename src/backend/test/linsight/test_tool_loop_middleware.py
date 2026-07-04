"""Unit tests for LinsightToolLoopBreakerMiddleware (L3) + salvage + L4 label.

Covers the same-tool consecutive-failure breaker:
- soft nudge appended to the error ToolMessage at ``soft_limit``,
- hard stop raising ``LinsightToolLoopError`` (with salvage) at ``hard_limit``,
- the two false-abort guards (model recovered / switched tools),
- streak reset on a success, non-error / interrupt pass-through,
- salvage assembly, and the L4 ``TASK_ABORTED`` classifier label.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from bisheng.common.services.llm_error_classifier import ErrorType, label_error
from bisheng.linsight.domain.services.tool_loop_middleware import (
    LinsightToolLoopBreakerMiddleware,
    LinsightToolLoopError,
    assemble_partial_result,
    build_tool_loop_breaker_middleware,
)

WRITE_FILE = "write_file"
KB_TOOL = "search_knowledge_base"


# --------------------------------------------------------------------------- helpers


class _Req:
    """Minimal ToolCallRequest stand-in (middleware only reads tool_call + state)."""

    def __init__(self, tool_call, messages):
        self.tool_call = tool_call
        self.state = {"messages": messages}


def _ai_call(tool=WRITE_FILE, args=None, content=""):
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": tool, "args": args or {"file_path": "/output/report.md"}, "id": "tc", "type": "tool_call"}
        ],
    )


def _err_tm(tool=WRITE_FILE, content="content: Field required"):
    return ToolMessage(content=content, tool_call_id="tc", name=tool, status="error")


def _ok_tm(tool=WRITE_FILE, content="written"):
    return ToolMessage(content=content, tool_call_id="tc", name=tool)


def _failure_turns(n, tool=WRITE_FILE):
    """n interleaved (AIMessage tool_call -> error ToolMessage) turns."""
    msgs = []
    for _ in range(n):
        msgs.append(_ai_call(tool))
        msgs.append(_err_tm(tool))
    return msgs


def _mw(*, soft=3, hard=8, is_subagent=False):
    return LinsightToolLoopBreakerMiddleware(soft_limit=soft, hard_limit=hard, is_subagent=is_subagent)


def _error_handler(tool=WRITE_FILE, content="content: Field required"):
    async def handler(_request):
        return _err_tm(tool, content)

    return handler


# --------------------------------------------------------------------------- soft nudge


async def test_soft_nudge_appended_at_threshold():
    mw = _mw(soft=3, hard=8)
    # 2 prior failures + the current pending call => current streak becomes 3 == soft.
    state = _failure_turns(2) + [_ai_call()]
    req = _Req({"name": WRITE_FILE, "args": {}}, state)
    resp = await mw.awrap_tool_call(req, _error_handler())
    assert "content: Field required" in resp.content
    assert "分段写入" in resp.content  # write_file-specific corrective hint present


async def test_soft_nudge_not_appended_below_threshold():
    mw = _mw(soft=3, hard=8)
    # 1 prior failure + pending => current streak 2 < soft(3): unchanged.
    state = _failure_turns(1) + [_ai_call()]
    req = _Req({"name": WRITE_FILE, "args": {}}, state)
    resp = await mw.awrap_tool_call(req, _error_handler())
    assert resp.content == "content: Field required"


async def test_streak_resets_after_a_success():
    mw = _mw(soft=3, hard=8)
    # A success breaks the run; a fresh failure is streak 1, no nudge.
    state = _failure_turns(2) + [_ai_call(), _ok_tm(), _ai_call()]
    req = _Req({"name": WRITE_FILE, "args": {}}, state)
    resp = await mw.awrap_tool_call(req, _error_handler())
    assert resp.content == "content: Field required"


async def test_success_response_passes_through_untouched():
    mw = _mw()
    state = _failure_turns(5) + [_ai_call()]
    req = _Req({"name": WRITE_FILE, "args": {}}, state)

    async def ok_handler(_request):
        return _ok_tm()

    resp = await mw.awrap_tool_call(req, ok_handler)
    assert resp.status != "error"
    assert resp.content == "written"


async def test_interrupt_like_exception_propagates():
    """ask_user's interrupt() raises out of the handler — must not be swallowed."""
    mw = _mw()
    req = _Req({"name": "ask_user", "args": {}}, [])

    async def raising(_request):
        raise RuntimeError("interrupt-like control flow")

    with pytest.raises(RuntimeError):
        await mw.awrap_tool_call(req, raising)


# --------------------------------------------------------------------------- hard stop


async def test_hard_stop_raises_with_salvage_at_limit():
    mw = _mw(soft=3, hard=8)
    analysis = "核心结论：二级市场存在结构性机会，建议关注高景气板块。"
    kb = ToolMessage(content="券商研报：某行业景气度持续上行", tool_call_id="k", name=KB_TOOL)
    messages = [AIMessage(content=analysis), kb] + _failure_turns(8) + [_ai_call()]
    with pytest.raises(LinsightToolLoopError) as ei:
        await mw.aafter_model({"messages": messages}, None)
    assert ei.value.tool_name == WRITE_FILE
    assert ei.value.count >= 8
    assert "核心结论" in ei.value.partial_result  # analysis salvaged
    assert "券商研报" in ei.value.partial_result  # retrieved knowledge salvaged


async def test_no_raise_below_hard_limit():
    mw = _mw(soft=3, hard=8)
    messages = _failure_turns(7) + [_ai_call()]
    assert await mw.aafter_model({"messages": messages}, None) is None


async def test_no_raise_when_model_recovered_with_text_answer():
    """After the streak the model gave a plain answer (no tool call) — must NOT abort."""
    mw = _mw(soft=3, hard=8)
    messages = _failure_turns(8) + [AIMessage(content="这是最终答复", tool_calls=[])]
    assert await mw.aafter_model({"messages": messages}, None) is None


async def test_no_raise_when_model_switched_tools():
    mw = _mw(soft=3, hard=8)
    messages = _failure_turns(8) + [_ai_call(tool="edit_file")]
    assert await mw.aafter_model({"messages": messages}, None) is None


# --------------------------------------------------------------------------- salvage assembly


def test_assemble_partial_result_prioritizes_analysis_and_digests_kb():
    messages = [
        AIMessage(content="分析：A 股估值处于历史低位"),
        ToolMessage(content="研报正文：行业A 需求回暖", tool_call_id="k1", name=KB_TOOL),
        _ai_call(),  # empty-content tool-call producer — must be ignored
        _err_tm(),
    ]
    out = assemble_partial_result(messages)
    assert "## 已完成的分析" in out
    assert "A 股估值处于历史低位" in out
    assert "## 检索到的关键资料（摘要）" in out
    assert "行业A 需求回暖" in out


def test_assemble_partial_result_empty_when_nothing_salvageable():
    # Only failed tool calls, no analysis text and no KB results.
    assert assemble_partial_result(_failure_turns(3)) == ""


# --------------------------------------------------------------------------- factory + L4 label


def test_build_from_conf_reads_thresholds():
    conf = SimpleNamespace(tool_failure_soft_limit=2, tool_failure_hard_limit=5)
    mw = build_tool_loop_breaker_middleware(conf, is_subagent=True)
    assert mw.soft_limit == 2
    assert mw.hard_limit == 5
    assert mw.is_subagent is True
    assert mw.name == "LinsightToolLoopBreakerSub"


def test_hard_limit_kept_above_soft():
    # Guard: hard must stay strictly above soft even if misconfigured equal.
    mw = LinsightToolLoopBreakerMiddleware(soft_limit=5, hard_limit=3)
    assert mw.hard_limit > mw.soft_limit


def test_label_error_graph_recursion_is_task_aborted():
    assert label_error(GraphRecursionError("Recursion limit of 200 reached")) == ErrorType.TASK_ABORTED


def test_label_error_tool_loop_is_task_aborted():
    assert label_error(LinsightToolLoopError(tool_name=WRITE_FILE, count=8)) == ErrorType.TASK_ABORTED


# --------------------------------------------------------------------------- integration
# Verifies the composition that unit tests can't: a real langchain agent graph
# where the model loops on a failing tool must RAISE LinsightToolLoopError out of
# ``ainvoke`` (i.e. the aafter_model raise actually propagates through the graph,
# beating the recursion limit) — the load-bearing assumption of the whole design.


async def test_hard_stop_propagates_through_real_agent_graph():
    from langchain.agents import create_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import HumanMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool
    from pydantic import BaseModel

    class _FailSchema(BaseModel):
        required_field: str

    @tool(args_schema=_FailSchema)
    def failing_tool(required_field: str) -> str:
        """A tool with a required field the fake model always omits."""
        return "ok"

    class _AlwaysCallsFailingTool(BaseChatModel):
        """Fake model that every turn calls failing_tool WITHOUT the required arg,
        reproducing the real ``content: Field required`` retry loop."""

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            ai = AIMessage(
                content="",
                # unique id per turn (messages grow each round) so tool_call ids never collide
                tool_calls=[{"name": "failing_tool", "args": {}, "id": f"call_{len(messages)}", "type": "tool_call"}],
            )
            return ChatResult(generations=[ChatGeneration(message=ai)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop, run_manager, **kwargs)

        @property
        def _llm_type(self):
            return "fake-always-fails"

    agent = create_agent(
        _AlwaysCallsFailingTool(),
        tools=[failing_tool],
        middleware=[LinsightToolLoopBreakerMiddleware(soft_limit=2, hard_limit=3)],
    )

    with pytest.raises(LinsightToolLoopError) as ei:
        await agent.ainvoke({"messages": [HumanMessage(content="go")]})
    assert ei.value.tool_name == "failing_tool"
    assert ei.value.count >= 3
