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

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from bisheng.linsight.domain.services.resilience_middleware import (
    _BUDGET_BUCKETS_MAX,
    _DELIVERABLE_TOOLS,
    _MAX_STATE_ONLY_REFUNDS,
    LinsightModelResilienceMiddleware,
    build_resilience_middleware,
)


class FakeTool:
    """Minimal stand-in: the middleware only ever reads ``.name``."""

    def __init__(self, name: str) -> None:
        self.name = name


class FakeRequest:
    """ModelRequest stand-in supporting the immutable ``override`` contract."""

    def __init__(self, messages=None, tools=None, runtime=None) -> None:
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
        # Defaults to None so every pre-existing case keeps exercising the
        # no-runtime path, which must behave exactly as it did before bucketing.
        self.runtime = runtime

    def override(self, **kwargs):
        new = FakeRequest(messages=list(self.messages), tools=list(self.tools), runtime=self.runtime)
        for key, value in kwargs.items():
            setattr(new, key, value)
        return new


# Real namespaces captured from ``test_subagent_ns_contract.py``: two parallel ``task``
# calls, each re-entering the SAME compiled researcher subgraph.
NS_A = "tools:a6dc6726-df24-8a53-049a-fbf4c35a1e9c|model_request:0d1c6618-5d9a-1111-2222-333344445555"
NS_A_TOOLS = "tools:a6dc6726-df24-8a53-049a-fbf4c35a1e9c|sub_tools:4c3b921e-1111-2222-3333-444455556666"
NS_B = "tools:5923fee9-ce67-f1a7-a07f-265bbf188878|model_request:f71b1032-5e6b-1111-2222-333344445555"


def _runtime(ns: str):
    return SimpleNamespace(execution_info=SimpleNamespace(checkpoint_ns=ns))


def ns_request(ns: str, **kwargs):
    """A request that looks like it came from inside a namespaced subgraph node."""
    return FakeRequest(runtime=_runtime(ns), **kwargs)


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
    def __init__(self, name: str, call_id: str = "call_1", ns: str | None = None) -> None:
        self.tool_call = {"name": name, "args": {}, "id": call_id}
        self.runtime = _runtime(ns) if ns is not None else None


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


# --------------------------------------------------------------------------
# Per-``task``-call budget buckets
#
# deepagents compiles the researcher subagent ONCE and re-enters that same
# runnable on every ``task`` call, so one middleware instance serves every
# delegation. Before bucketing, two parallel researchers split ONE 30-turn
# allowance: measured on v2.6.0-fix2, `graph=sub turn 29/30` was the two of them
# added together and the second one started already inside the soft-landing zone.
# --------------------------------------------------------------------------


def test_key_is_the_namespace_prefix_for_a_subagent():
    mw = make_mw(is_subagent=True)
    key = mw._budget_key(ns_request(NS_A))
    assert key == "tools:a6dc6726-df24-8a53-049a-fbf4c35a1e9c"
    # Different node inside the SAME task call → same bucket.
    assert mw._budget_key(ns_request(NS_A_TOOLS)) == key
    # A different task call → different bucket.
    assert mw._budget_key(ns_request(NS_B)) != key


async def test_two_task_calls_get_independent_budgets():
    mw = make_mw(turn_limit=3, soft_landing_turns=8, is_subagent=True)
    handler = capturing_handler()
    for _ in range(3):
        await mw.awrap_model_call(ns_request(NS_A), handler)
    assert handler.state["requests"][-1].tools == []  # A is exhausted

    # B starts fresh: 3 left, still above the soft-landing window used here.
    request_b = ns_request(NS_B)
    await mw.awrap_model_call(request_b, handler)
    assert mw._turns_used(mw._budget_key(request_b)) == 1
    assert handler.state["requests"][-1].tools != []


async def test_parallel_task_calls_do_not_share_the_ladder():
    """The regression: interleaved delegations must each get their own stage."""
    mw = make_mw(turn_limit=3, soft_landing_turns=8, is_subagent=True)
    handler = capturing_handler()
    for _ in range(3):
        await mw.awrap_model_call(ns_request(NS_A), handler)
        await mw.awrap_model_call(ns_request(NS_B), handler)

    a_turns = mw._turns_used("tools:a6dc6726-df24-8a53-049a-fbf4c35a1e9c")
    b_turns = mw._turns_used("tools:5923fee9-ce67-f1a7-a07f-265bbf188878")
    assert a_turns == b_turns == 3  # not 6 shared between them


async def test_main_graph_ignores_the_namespace():
    """Gate-keeper: the main graph's namespace changes every turn and carries no
    separator, so bucketing it would hand it a brand-new budget on every call."""
    mw = make_mw(turn_limit=10, is_subagent=False)
    handler = capturing_handler()
    await mw.awrap_model_call(ns_request(NS_A), handler)
    await mw.awrap_model_call(ns_request(NS_B), handler)
    assert mw._turn_count == 2
    assert list(mw._turns) == [""]


async def test_missing_runtime_falls_back_to_the_shared_bucket():
    mw = make_mw(turn_limit=10, is_subagent=True)
    handler = capturing_handler()
    for _ in range(2):
        await mw.awrap_model_call(FakeRequest(), handler)
    assert mw._turn_count == 2


async def test_flat_namespace_falls_back_to_the_shared_bucket():
    """A subagent graph that ran un-nested has no separator — degrade, never crash."""
    mw = make_mw(turn_limit=10, is_subagent=True)
    handler = capturing_handler()
    await mw.awrap_model_call(ns_request("model:abc"), handler)
    assert mw._turn_count == 1


async def test_tool_refusal_uses_the_calling_task_bucket():
    mw = make_mw(turn_limit=1, is_subagent=True)
    await mw.awrap_model_call(ns_request(NS_A), capturing_handler())  # spend A only

    refused_handler = tool_handler()
    refused = await mw.awrap_tool_call(FakeToolRequest("read_file", ns=NS_A_TOOLS), refused_handler)
    assert refused_handler.state["calls"] == 0
    assert "预算已用尽" in refused.content

    allowed_handler = tool_handler()
    allowed = await mw.awrap_tool_call(FakeToolRequest("read_file", ns=NS_B), allowed_handler)
    assert allowed_handler.state["calls"] == 1
    assert allowed.content == "executed"


async def test_bucket_table_is_bounded():
    mw = make_mw(turn_limit=100, is_subagent=True)
    handler = capturing_handler()
    for i in range(_BUDGET_BUCKETS_MAX + 40):
        await mw.awrap_model_call(ns_request(f"tools:{i}|model_request:x"), handler)
    assert len(mw._turns) <= _BUDGET_BUCKETS_MAX
    assert len(mw._refunds) <= _BUDGET_BUCKETS_MAX


# --------------------------------------------------------------------------
# State-only turns are refunded
#
# ``TodoListMiddleware`` is injected into every subagent by deepagents, and a
# model call that only re-publishes the todo list buys nothing. Measured: 10 of a
# researcher's 29 calls were exactly that.
# --------------------------------------------------------------------------


def todo_handler(tool_names_seq=("write_todos",), *, invalid=False, fail_times=0, truncate_first=False):
    """Handler returning an AIMessage whose tool calls are under our control."""
    state = {"calls": 0, "requests": []}

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
        truncated = truncate_first and state["calls"] == fail_times + 1
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": {}, "id": f"c{i}"} for i, name in enumerate(tool_names_seq)],
            invalid_tool_calls=([{"name": "write_file", "args": "{bad", "id": "bad", "error": "x"}] if invalid else []),
            response_metadata={"finish_reason": "length"} if truncated else {},
        )

    handler.state = state
    return handler


async def test_write_todos_only_turn_is_refunded():
    mw = make_mw(turn_limit=10)
    for _ in range(3):
        await mw.awrap_model_call(FakeRequest(), todo_handler())
    assert mw._turn_count == 0


async def test_write_todos_plus_another_tool_burns_a_turn():
    mw = make_mw(turn_limit=10)
    await mw.awrap_model_call(FakeRequest(), todo_handler(("write_todos", "write_file")))
    assert mw._turn_count == 1


async def test_text_only_close_out_burns_a_turn():
    """Refunding the closing turn would keep the ladder from ever reaching stage 3."""
    mw = make_mw(turn_limit=10)
    await mw.awrap_model_call(FakeRequest(), todo_handler(()))
    assert mw._turn_count == 1


async def test_invalid_tool_calls_burn_a_turn():
    mw = make_mw(turn_limit=10)
    await mw.awrap_model_call(FakeRequest(), todo_handler(("write_todos",), invalid=True))
    assert mw._turn_count == 1


async def test_response_without_an_ai_message_burns_a_turn():
    mw = make_mw(turn_limit=10)

    async def handler(_request):
        return SimpleNamespace(result=[])

    await mw.awrap_model_call(FakeRequest(), handler)
    assert mw._turn_count == 1


async def test_refund_happens_once_across_transient_retries():
    """The refund sits at the loop's single success exit, so two retries cannot
    turn one state-only turn into a -2 credit."""
    mw = make_mw(turn_limit=10)
    handler = todo_handler(fail_times=2)
    await mw.awrap_model_call(FakeRequest(), handler)
    assert handler.state["calls"] == 3
    assert mw._turn_count == 0


async def test_refund_happens_once_across_truncation_retries():
    mw = make_mw(turn_limit=10)
    handler = todo_handler(truncate_first=True)
    await mw.awrap_model_call(FakeRequest(), handler)
    assert handler.state["calls"] == 2  # truncation nudge retried once
    assert mw._turn_count == 0


async def test_degraded_turn_is_not_refunded():
    """A degraded call really did burn model calls — it never reaches the refund."""
    mw = make_mw(turn_limit=10, is_subagent=True)

    async def handler(_request):
        import openai

        exc = openai.BadRequestError.__new__(openai.BadRequestError)
        exc.message = "content filter"
        exc.code = "content_filter"
        exc.body = None
        raise exc

    await mw.awrap_model_call(FakeRequest(), handler)
    assert mw._turn_count == 1


async def test_refunds_are_capped():
    mw = make_mw(turn_limit=100)
    for _ in range(_MAX_STATE_ONLY_REFUNDS + 5):
        await mw.awrap_model_call(FakeRequest(), todo_handler())
    assert mw._turn_count == 5


async def test_soft_landing_stage_is_chosen_before_the_refund():
    """Two-phase accounting: the stage is picked from the pre-call count (it has to
    shape the request), and only afterwards is the turn given back."""
    mw = make_mw(turn_limit=3, soft_landing_turns=8)
    handler = todo_handler()
    await mw.awrap_model_call(FakeRequest(), handler)
    assert tool_names(handler.state["requests"][0]) <= _DELIVERABLE_TOOLS
    assert mw._turn_count == 0


async def test_refunds_never_make_the_hard_stop_unreachable():
    """The cap is what keeps a write_todos loop from bypassing the ladder entirely
    and dying on GraphRecursionError instead."""
    mw = make_mw(turn_limit=3, soft_landing_turns=8)
    handler = todo_handler()
    for _ in range(3 + _MAX_STATE_ONLY_REFUNDS + 1):
        await mw.awrap_model_call(FakeRequest(), handler)
    assert handler.state["requests"][-1].tools == []


async def test_refunds_are_per_bucket():
    mw = make_mw(turn_limit=10, is_subagent=True)
    handler = todo_handler()
    for _ in range(2):
        await mw.awrap_model_call(ns_request(NS_A), handler)
        await mw.awrap_model_call(ns_request(NS_B), handler)
    assert mw._turns_used("tools:a6dc6726-df24-8a53-049a-fbf4c35a1e9c") == 0
    assert mw._turns_used("tools:5923fee9-ce67-f1a7-a07f-265bbf188878") == 0
