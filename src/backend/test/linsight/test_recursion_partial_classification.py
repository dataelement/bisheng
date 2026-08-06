"""Regression: a step-ceiling abort must not masquerade as a write-tool failure.

Background — session ``03b0eb4b530d4eefa5cb19d2545b40a4`` (114, 2026-08-06):
the run delivered a .md and a .pptx, closed 5/5 todos, and its last model call
came back ``finish_reason=stop`` with a 151-char closing summary. Five
milliseconds later the run raised ``GraphRecursionError`` and the user was told
"模型未能正确调用写入工具" — a sentence about a tool that never failed once in
that session. Two independent defects produced it:

1. LangGraph's ``PregelLoop.tick()`` tests ``step > stop`` BEFORE it computes
   whether any task remains, so the very step that would have ended the graph
   raises instead. A finished run therefore looks identical to a runaway one.
2. The salvage copy was a single hard-coded string blaming the write tool,
   used for BOTH the tool-loop breaker and the recursion ceiling. Across the
   whole worker log the salvage path had fired only on recursion — so that
   sentence was wrong every time it ever shipped.

Fix: classify the abort by whether the model still had tool calls pending (it
finished ⇒ complete normally), and key the copy off the real exception type.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from bisheng.linsight.domain.services.tool_loop_middleware import LinsightToolLoopError
from bisheng.linsight.domain.task_exec import (
    _PARTIAL_NO_SALVAGE_STEP_LIMIT,
    _PARTIAL_NO_SALVAGE_TOOL_LOOP,
    _PARTIAL_RESULT_PREAMBLE_STEP_LIMIT,
    _PARTIAL_RESULT_PREAMBLE_TOOL_LOOP,
    _RECURSION_LIMIT_MARGIN,
    _STEPS_PER_MODEL_TURN,
    LinsightWorkflowTask,
    _resolve_recursion_limit,
)

pending = LinsightWorkflowTask._last_ai_pending_tool_calls

# The real closing message from the incident (151 chars, no tool calls).
_CLOSING_ANSWER = (
    "已生成摩根大通投资分析 PPT，共 7 页幻灯片，涵盖公司概况、四大业务板块、核心财务数据对比表、"
    "FY2020–FY2024 营收与净利润趋势柱状图、投资亮点与风险分析、以及总结展望。"
)


def _tool_call(name: str = "bisheng_code_interpreter") -> dict:
    return {"name": name, "args": {}, "id": "call_1"}


# --------------------------------------------------------------------------
# The "did the model actually finish?" test
# --------------------------------------------------------------------------


def test_closing_answer_has_no_pending_tool_calls():
    """The incident's own shape: a text-only AIMessage means the run was done."""
    messages = [HumanMessage(content="生成一个介绍摩根大通的 PPT"), AIMessage(content=_CLOSING_ANSWER)]
    assert pending(messages) is False


def test_trailing_tool_message_still_counts_as_mid_loop():
    """Cut off mid-loop: the last AIMessage still carries the call being run."""
    messages = [
        AIMessage(content="", tool_calls=[_tool_call()]),
        ToolMessage(content='{"exitcode": 0}', tool_call_id="call_1", name="bisheng_code_interpreter"),
    ]
    assert pending(messages) is True


def test_tool_call_only_aimessage_is_not_skipped():
    """The trap that rules out reusing ``_extract_last_message_text``.

    That helper walks back to the last AIMessage carrying TEXT. Here the newest
    AIMessage has tool calls and no text, so a text-based walk would land on the
    earlier chatty message and wrongly declare the run finished.
    """
    messages = [
        AIMessage(content="我已经完成数据分析，下面生成报告。"),
        AIMessage(content="", tool_calls=[_tool_call("write_file")]),
    ]
    assert pending(messages) is True
    assert LinsightWorkflowTask._extract_last_message_text(messages) == "我已经完成数据分析，下面生成报告。"


def test_dict_shaped_messages_are_understood():
    assert pending([{"type": "ai", "content": "done"}]) is False
    assert pending([{"type": "ai", "content": "", "tool_calls": [_tool_call()]}]) is True


def test_no_assistant_message_defaults_to_mid_loop():
    """Conservative default: without evidence the model closed out, salvage."""
    assert pending([]) is True
    assert pending(None) is True
    assert pending([HumanMessage(content="hi")]) is True


def test_capture_values_snapshot_records_both_signals():
    task = LinsightWorkflowTask()
    task._capture_values_snapshot({"messages": [AIMessage(content=_CLOSING_ANSWER)]})
    assert task._last_assistant_text == _CLOSING_ANSWER
    assert task._last_ai_has_pending_tool_calls is False


# --------------------------------------------------------------------------
# Completion routing (A)
# --------------------------------------------------------------------------


def _completion_task(*, exc: BaseException, has_pending: bool) -> LinsightWorkflowTask:
    task = LinsightWorkflowTask()
    task._check_user_termination = AsyncMock(return_value=False)
    task._handle_task_partial = AsyncMock()
    task._handle_direct_answer_completion = AsyncMock()
    task._handle_task_success = AsyncMock()
    task._stash_partial_abort(exc)
    task._last_ai_has_pending_tool_calls = has_pending
    task._last_assistant_text = _CLOSING_ANSWER
    return task


async def test_finished_run_completes_normally_despite_the_ceiling():
    """The incident: recursion raised after the model closed out ⇒ no apology."""
    task = _completion_task(exc=GraphRecursionError("Recursion limit of 200 reached"), has_pending=False)
    await task._handle_task_completion(object())
    task._handle_task_partial.assert_not_awaited()
    task._handle_direct_answer_completion.assert_awaited_once()


async def test_genuine_runaway_still_salvages():
    task = _completion_task(exc=GraphRecursionError("Recursion limit of 500 reached"), has_pending=True)
    await task._handle_task_completion(object())
    task._handle_task_partial.assert_awaited_once()
    task._handle_direct_answer_completion.assert_not_awaited()


async def test_tool_loop_abort_still_salvages():
    """The breaker only fires while a tool call is pending, so it never trips the
    new fast path — the classification is self-consistent, no type check needed."""
    task = _completion_task(exc=LinsightToolLoopError(tool_name="write_file", count=8), has_pending=True)
    await task._handle_task_completion(object())
    task._handle_task_partial.assert_awaited_once()


# --------------------------------------------------------------------------
# Copy classification (B)
# --------------------------------------------------------------------------


def _salvage_task(exc: BaseException) -> LinsightWorkflowTask:
    task = LinsightWorkflowTask()
    task._handle_task_failure = AsyncMock()
    task._stash_partial_abort(exc)
    # No salvage body and no captured answer → the no-salvage branch, which is
    # the one path through _handle_task_partial that touches no storage.
    task._partial_salvage = None
    task._last_assistant_text = None
    return task


async def test_recursion_no_salvage_copy_does_not_blame_the_write_tool():
    task = _salvage_task(GraphRecursionError("Recursion limit of 500 reached"))
    await task._handle_task_partial(object())
    message = task._handle_task_failure.await_args.args[1]
    assert message == _PARTIAL_NO_SALVAGE_STEP_LIMIT
    assert "写入工具" not in message
    assert "步骤数已达上限" in message


async def test_tool_loop_no_salvage_copy_keeps_the_tool_wording():
    task = _salvage_task(LinsightToolLoopError(tool_name="write_file", count=8))
    await task._handle_task_partial(object())
    assert task._handle_task_failure.await_args.args[1] == _PARTIAL_NO_SALVAGE_TOOL_LOOP


def test_the_two_preambles_describe_different_causes():
    assert "写入工具" in _PARTIAL_RESULT_PREAMBLE_TOOL_LOOP
    assert "写入工具" not in _PARTIAL_RESULT_PREAMBLE_STEP_LIMIT
    assert "步骤数已达上限" in _PARTIAL_RESULT_PREAMBLE_STEP_LIMIT


# --------------------------------------------------------------------------
# Recursion ceiling floor (C1)
# --------------------------------------------------------------------------


class _Conf:
    def __init__(self, max_steps: int, max_model_turns: int = 115) -> None:
        self.max_steps = max_steps
        self.max_model_turns = max_model_turns


def test_legacy_db_value_is_raised_above_the_turn_budget():
    """Existing installs keep ``max_steps: 200`` in the DB config, which would trip
    at ~50 turns and make the 115-turn budget unreachable."""
    resolved = _resolve_recursion_limit(_Conf(max_steps=200))
    assert resolved == 115 * _STEPS_PER_MODEL_TURN + _RECURSION_LIMIT_MARGIN
    assert resolved > 200


def test_new_default_is_already_above_the_floor():
    assert _resolve_recursion_limit(_Conf(max_steps=500)) == 500


def test_operator_raised_ceiling_is_respected():
    assert _resolve_recursion_limit(_Conf(max_steps=2000)) == 2000


def test_floor_tracks_a_raised_turn_budget():
    resolved = _resolve_recursion_limit(_Conf(max_steps=500, max_model_turns=300))
    assert resolved == 300 * _STEPS_PER_MODEL_TURN + _RECURSION_LIMIT_MARGIN
