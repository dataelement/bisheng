"""Framework contract: how LangGraph namespaces a re-entered subgraph.

``LinsightModelResilienceMiddleware`` gives the researcher subagent a per-``task``-call
turn budget by bucketing its counter on the LangGraph node namespace. That only works
because of three properties of the framework, none of which we control:

1. every ``task`` tool call becomes its own PUSH task, so two parallel delegations get
   distinct namespaces even though deepagents compiled the subagent exactly ONCE
   (``deepagents/middleware/subagents.py:584`` builds ``compiled_subagents`` at
   ``_build_task_tool`` time; ``:640-653`` hands the same runnable to every call);
2. inside one such call the namespace prefix is CONSTANT across turns and across
   model/tools nodes, so the bucket survives the whole delegation;
3. the main graph's namespace has NO separator, which is what lets the middleware
   force it onto a single bucket — bucketing the main graph would reset its budget
   every turn.

This test pins all three WITHOUT calling a model, so a langgraph/langchain upgrade
that changes namespace construction fails here instead of silently handing every
subagent an unlimited budget (property 1/2) or the main graph a broken one (property 3).
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import ExecutionInfo, get_runtime
from langgraph.types import Send

# Mirrors ``langgraph._internal._constants.NS_SEP``. Deliberately re-declared instead
# of imported: the value is part of the checkpoint wire format (far more stable than
# the private module path), and the production code makes the same choice.
NS_SEP = "|"

_SUB_TURNS = 3


class _SubState(TypedDict):
    turns: int
    seen: Annotated[list[str], operator.add]


class _ParentState(TypedDict):
    seen: Annotated[list[str], operator.add]
    sub_runs: Annotated[list[list[str]], operator.add]


def _current_ns() -> str:
    return get_runtime().execution_info.checkpoint_ns


def _sub_model(state: _SubState) -> dict:
    return {"turns": state["turns"] + 1, "seen": [_current_ns()]}


def _sub_tools(state: _SubState) -> dict:
    return {"seen": [_current_ns()]}


def _sub_route(state: _SubState) -> str:
    return "sub_tools" if state["turns"] < _SUB_TURNS else END


def _build_subgraph():
    graph = StateGraph(_SubState)
    graph.add_node("model_request", _sub_model)
    graph.add_node("sub_tools", _sub_tools)
    graph.add_edge(START, "model_request")
    graph.add_conditional_edges("model_request", _sub_route, ["sub_tools", END])
    graph.add_edge("sub_tools", "model_request")
    return graph.compile()


# Compiled ONCE at import, exactly like deepagents compiles the researcher once and
# re-enters it on every ``task`` call. Compiling per test would defeat the point.
_SUBGRAPH = _build_subgraph()


def _parent_agent(state: _ParentState) -> dict:
    return {"seen": [_current_ns()]}


def _parent_fan_out(state: _ParentState) -> list[Send]:
    # Two delegations from ONE model turn — the shape that exposed the shared budget
    # in production (both ``task`` calls arrived in a single tool_calls array).
    return [Send("tools", {"turns": 0, "seen": []}), Send("tools", {"turns": 0, "seen": []})]


def _parent_tools(state: _SubState) -> dict:
    result = _SUBGRAPH.invoke({"turns": 0, "seen": []})
    return {"sub_runs": [result["seen"]]}


def _build_parent():
    graph = StateGraph(_ParentState)
    graph.add_node("agent", _parent_agent)
    graph.add_node("tools", _parent_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _parent_fan_out, ["tools"])
    graph.add_edge("tools", END)
    return graph.compile()


def _prefix(ns: str) -> str:
    """The bucket key the middleware derives — see ``_budget_key``."""
    return ns.rsplit(NS_SEP, 1)[0]


def test_execution_info_still_exposes_checkpoint_ns():
    """The attribute the whole scheme reads. Guards dependency upgrades."""
    assert "checkpoint_ns" in ExecutionInfo.__dataclass_fields__


def test_subagent_namespace_prefix_is_stable_within_one_call():
    result = _build_parent().invoke({"seen": [], "sub_runs": []})

    for run in result["sub_runs"]:
        # model_request x3 + sub_tools x2 — every node of the delegation.
        assert len(run) == _SUB_TURNS * 2 - 1
        prefixes = {_prefix(ns) for ns in run}
        assert len(prefixes) == 1, f"prefix drifted across turns of one task call: {prefixes}"
        assert NS_SEP in run[0], f"nested subgraph namespace lost its separator: {run[0]!r}"


def test_parallel_task_calls_get_distinct_namespace_prefixes():
    result = _build_parent().invoke({"seen": [], "sub_runs": []})

    assert len(result["sub_runs"]) == 2
    first, second = ({_prefix(ns) for ns in run}.pop() for run in result["sub_runs"])
    assert first != second, "two task calls shared a bucket key — budgets would be shared again"


def test_main_graph_namespace_has_no_separator():
    """Why ``_budget_key`` must return the constant bucket for the main graph.

    The main graph's node namespace carries a fresh task id every turn and no
    separator, so bucketing on it would hand the main graph a brand-new budget on
    every single model call.
    """
    result = _build_parent().invoke({"seen": [], "sub_runs": []})

    assert result["seen"], "parent node never recorded its namespace"
    for ns in result["seen"]:
        assert NS_SEP not in ns, f"main-graph namespace unexpectedly nested: {ns!r}"
