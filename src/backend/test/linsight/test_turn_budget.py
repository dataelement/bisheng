"""Unit tests for the turn budget + soft landing ladder (灵思轮次预算软着陆).

Background — session ``03b0eb4b…`` (task mode, 2026-08-06): the run finished its
work (5/5 todos, a .md and a .pptx on disk) and the model produced its closing
answer, but LangGraph's step counter had just crossed ``recursion_limit`` so the
whole run was rendered as a failure. The step ceiling is a poor business gate:
one model turn costs ~4 super-steps, so ``max_steps: 200`` really meant 50 turns.

The fix moves the gate to a MODEL-TURN budget enforced inside ``wrap_model_call``
(a wrap hook compiles to no graph node, so it costs zero super-steps) and lands
the run in three stages instead of aborting it: nudge → write-only tools → no
tools at all, backed by a refusal at the tool layer so the model's only way
forward is a text answer and the graph reaches END by itself.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bisheng.linsight.domain.services.resilience_middleware import (
    _DELIVERABLE_TOOLS,
    LinsightModelResilienceMiddleware,
    build_resilience_middleware,
)


class FakeTool:
    """Minimal stand-in: the middleware only ever reads ``.name``."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeRequest:
    """ModelRequest stand-in supporting the immutable ``override`` contract."""

    def __init__(self, messages=None, tools=None) -> None:
        self.messages = messages if messages is not None else [HumanMessage(content="做一份 PPT")]
        self.tools = (
            tools
            if tools is not None
            else [
                FakeTool("write_file"),
                FakeTool("edit_file"),
                FakeTool("export_docx"),
                FakeTool("bisheng_code_interpreter"),
                FakeTool("read_file"),
            ]
        )

    def override(self, **kwargs):
        new = FakeRequest(messages=list(self.messages), tools=list(self.tools))
        for key, value in kwargs.items():
            setattr(new, key, value)
        return new


def make_mw(*, turn_limit=115, soft_landing_turns=8, is_subagent=False, sink=None):
    return LinsightModelResilienceMiddleware(
        max_retries=2,
        initial_delay=0.0,  # calculate_delay -> 0, no real sleeping
        is_subagent=is_subagent,
        turn_limit=turn_limit,
        soft_landing_turns=soft_landing_turns,
        budget_sink=sink,
    )


def capturing_handler(fail_times: int = 0):
    """Async handler recording every request it receives; optionally fails first."""
    state = {"requests": [], "calls": 0}

    async def handler(request):
        state["calls"] += 1
        state["requests"].append(request)
        if state["calls"] <= fail_times:
            import openai

            exc = openai.APITimeoutError.__new__(openai.APITimeoutError)
            exc.message = "timeout"
            exc.code = None
            exc.body = None
            raise exc
        return AIMessage(content="ok")

    handler.state = state
    return handler


def tool_names(request) -> set[str]:
    return {t.name for t in request.tools}


def last_text(request) -> str:
    content = request.messages[-1].content
    return content if isinstance(content, str) else str(content)


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------


async def test_each_wrap_call_costs_exactly_one_turn():
    mw = make_mw(turn_limit=10)
    for _ in range(3):
        await mw.awrap_model_call(FakeRequest(), capturing_handler())
    assert mw._turn_count == 3


async def test_internal_retries_do_not_burn_budget():
    """A transient retry re-enters ``handler``, not the budget — one node, one turn."""
    mw = make_mw(turn_limit=10)
    handler = capturing_handler(fail_times=2)
    await mw.awrap_model_call(FakeRequest(), handler)
    assert handler.state["calls"] == 3  # initial + 2 retries
    assert mw._turn_count == 1  # but still a single turn


# --------------------------------------------------------------------------
# Stage 0: plenty of budget left → request untouched
# --------------------------------------------------------------------------


async def test_request_untouched_while_budget_is_healthy():
    mw = make_mw(turn_limit=115, soft_landing_turns=8)
    request = FakeRequest()
    handler = capturing_handler()
    await mw.awrap_model_call(request, handler)
    seen = handler.state["requests"][0]
    assert seen is request  # no copy, no nudge
    assert len(seen.messages) == 1


# --------------------------------------------------------------------------
# Stage 1: nudge
# --------------------------------------------------------------------------


async def test_nudge_appended_at_the_tail_within_soft_landing_window():
    # turn_limit 10, soft window 8 → turn 2 leaves 8 remaining → nudge.
    mw = make_mw(turn_limit=10, soft_landing_turns=8)
    handler = capturing_handler()
    await mw.awrap_model_call(FakeRequest(), handler)  # turn 1, 9 left → quiet
    assert len(handler.state["requests"][0].messages) == 1
    await mw.awrap_model_call(FakeRequest(), handler)  # turn 2, 8 left → nudge
    nudged = handler.state["requests"][1]
    assert len(nudged.messages) == 2
    assert isinstance(nudged.messages[-1], HumanMessage)
    assert "预算即将耗尽" in last_text(nudged)
    # Every tool is still available at this stage.
    assert "bisheng_code_interpreter" in tool_names(nudged)


async def test_nudge_is_ephemeral_and_never_mutates_the_original_request():
    """The nudge must not leak into graph state — same contract as the L2 nudge."""
    mw = make_mw(turn_limit=2, soft_landing_turns=8)
    request = FakeRequest()
    handler = capturing_handler()
    await mw.awrap_model_call(request, handler)
    assert len(request.messages) == 1  # untouched
    assert len(handler.state["requests"][0].messages) == 2  # only the copy carries it


# --------------------------------------------------------------------------
# Stage 2: write-only tools
# --------------------------------------------------------------------------


async def test_last_two_turns_narrow_to_deliverable_tools():
    mw = make_mw(turn_limit=3, soft_landing_turns=8)
    handler = capturing_handler()
    await mw.awrap_model_call(FakeRequest(), handler)  # turn 1, 2 left
    narrowed = handler.state["requests"][0]
    assert tool_names(narrowed) <= _DELIVERABLE_TOOLS
    assert tool_names(narrowed) == {"write_file", "edit_file", "export_docx"}
    assert "最后的收尾机会" in last_text(narrowed)


# --------------------------------------------------------------------------
# Stage 3: no tools → the graph ends by itself
# --------------------------------------------------------------------------


async def test_exhausted_budget_offers_no_tools_at_all():
    """Nothing is offered to the model. This alone does not STOP a determined model
    (see the hard-stop tests below) but it removes the temptation, which is enough
    in practice for the graph to reach END instead of hitting the recursion ceiling."""
    mw = make_mw(turn_limit=1, soft_landing_turns=8)
    handler = capturing_handler()
    await mw.awrap_model_call(FakeRequest(), handler)  # turn 1 → 0 remaining
    forced = handler.state["requests"][0]
    assert forced.tools == []
    await mw.awrap_model_call(FakeRequest(), handler)  # over budget stays tool-less
    assert handler.state["requests"][1].tools == []


# --------------------------------------------------------------------------
# Sink + budget isolation
# --------------------------------------------------------------------------


async def test_sink_flags_only_once_the_ladder_engages():
    sink: dict = {}
    mw = make_mw(turn_limit=10, soft_landing_turns=2, sink=sink)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())
    assert sink == {}  # 9 left, nothing to tell the user
    for _ in range(7):
        await mw.awrap_model_call(FakeRequest(), capturing_handler())
    assert sink["soft_landing"] is True


async def test_absent_sink_is_harmless():
    mw = make_mw(turn_limit=1, sink=None)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())  # must not raise


def test_main_and_subagent_budgets_come_from_different_config_keys():
    class Conf:
        max_model_turns = 115
        max_model_turns_subagent = 30
        soft_landing_turns = 8

    sink: dict = {}
    main = build_resilience_middleware(Conf(), is_subagent=False, budget_sink=sink)
    sub = build_resilience_middleware(Conf(), is_subagent=True)
    assert main.turn_limit == 115
    assert sub.turn_limit == 30
    # The subagent must not annotate the user's result when IT lands early.
    assert main._budget_sink is sink
    assert sub._budget_sink is None


# --------------------------------------------------------------------------
# Hard stop at the tool layer
#
# Narrowing ``request.tools`` is only a hint: with an empty list langchain skips
# bind_tools entirely, and ToolNode still holds every tool from compile time, so a
# model that keeps emitting calls keeps getting them executed (measured on 114: a
# 6-turn budget ran 8 turns). wrap_tool_call runs inside ToolNode, so it is the
# layer that can actually refuse.
# --------------------------------------------------------------------------


class FakeToolRequest:
    def __init__(self, name: str, call_id: str = "call_1") -> None:
        self.tool_call = {"name": name, "args": {}, "id": call_id}


def tool_handler():
    state = {"calls": 0}

    async def handler(request):
        state["calls"] += 1
        return ToolMessage(content="executed", tool_call_id=request.tool_call["id"], name=request.tool_call["name"])

    handler.state = state
    return handler


async def test_exploratory_tools_are_refused_once_the_budget_is_spent():
    mw = make_mw(turn_limit=1)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())  # spend the budget
    handler = tool_handler()
    result = await mw.awrap_tool_call(FakeToolRequest("bisheng_code_interpreter"), handler)
    assert handler.state["calls"] == 0  # never reached the tool
    assert "预算已用尽" in result.content
    assert result.tool_call_id == "call_1"


async def test_refusal_is_not_an_error_message():
    """An error ToolMessage would feed the L3 tool-loop breaker's failure streak and
    eventually abort the run into the apology path — the opposite of the goal."""
    mw = make_mw(turn_limit=1)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())
    result = await mw.awrap_tool_call(FakeToolRequest("search_knowledge_base"), tool_handler())
    assert result.status != "error"


async def test_write_todos_survives_the_hard_stop():
    """It is the only channel that syncs progress to the UI: blocking it would leave
    a finished run displaying 3/5."""
    mw = make_mw(turn_limit=1)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())
    handler = tool_handler()
    result = await mw.awrap_tool_call(FakeToolRequest("write_todos"), handler)
    assert handler.state["calls"] == 1
    assert result.content == "executed"


async def test_deliverable_writers_survive_the_hard_stop():
    mw = make_mw(turn_limit=1)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())
    for name in ("write_file", "edit_file", "export_docx", "export_pdf"):
        handler = tool_handler()
        result = await mw.awrap_tool_call(FakeToolRequest(name), handler)
        assert handler.state["calls"] == 1, name
        assert result.content == "executed", name


async def test_nothing_is_refused_while_budget_remains():
    mw = make_mw(turn_limit=10)
    await mw.awrap_model_call(FakeRequest(), capturing_handler())
    handler = tool_handler()
    result = await mw.awrap_tool_call(FakeToolRequest("bisheng_code_interpreter"), handler)
    assert handler.state["calls"] == 1
    assert result.content == "executed"


async def test_the_114_overrun_scenario_is_now_bounded():
    """Replays the measured overrun: after the budget is spent the model kept
    calling tools. Writers/todos still land the deliverable; exploration stops."""
    mw = make_mw(turn_limit=2, soft_landing_turns=8)
    for _ in range(2):
        await mw.awrap_model_call(FakeRequest(), capturing_handler())

    executed, refused = [], []
    for name in ("bisheng_code_interpreter", "write_file", "read_file", "write_todos", "task"):
        handler = tool_handler()
        result = await mw.awrap_tool_call(FakeToolRequest(name), handler)
        (executed if handler.state["calls"] else refused).append(name)
    assert executed == ["write_file", "write_todos"]
    assert refused == ["bisheng_code_interpreter", "read_file", "task"]


def test_build_falls_back_to_defaults_on_a_legacy_conf():
    """Existing installs have no such keys in the DB config — defaults must hold."""

    class LegacyConf:
        max_steps = 200

    mw = build_resilience_middleware(LegacyConf(), is_subagent=False)
    assert mw.turn_limit == 115
    assert mw.soft_landing_turns == 8
