"""Unit tests for linsight "#1 subagent re-introduction" (design §6.2).

The MVP re-enables the deepagents ``task`` tool plus a single researcher
subagent (named ``general-purpose`` to override deepagents' unsafe auto default
GP). Two root causes must stay defused *by construction*:

- Root cause B (HITL bubbling out of a subgraph): the subagent gets an EXPLICIT
  ``tools`` subset that NEVER contains ``ask_user`` and carries NO
  ``permissions`` / ``interrupt_on`` keys, so it has no interrupt source at all.
- Plan pollution: a subagent's own ``write_todos`` arrives namespaced; the
  stream mapper drops namespaced todos so they cannot mint bogus
  GenerateSubTask/TaskStart/TaskEnd on the main plan. Only namespaced *tool-call*
  steps surface, keeping their REAL step_type (tool/knowledge) while carrying
  ``extra_info.namespace`` so the frontend can group them under their owning
  subagent (B1: namespace drives grouping, not step_type rewriting).

These tests assert against the extracted pure helpers (``_subagent_tools`` /
``_build_researcher_subagent``) and the pure stream mapper, deliberately NOT
building the compiled graph (model resolution needs LLMService/DB).
"""

from __future__ import annotations

from bisheng.linsight.domain.services.agent_factory import (
    _KNOWN_HITL_TOOL_NAMES,
    _SUBAGENT_TOOL_DENY,
    _build_researcher_subagent,
    _subagent_tools,
)
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng_langchain.linsight.event import (
    ExecStep,
    GenerateSubTask,
    TaskEnd,
    TaskStart,
)

SVID = "1f3c9a20-7b4e-4d11-9c3a-0a1b2c3d4e5f"


class _FakeTool:
    """Minimal BaseTool-like stub: the helpers only read ``.name``."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:  # nicer assertion failure output
        return f"_FakeTool({self.name!r})"


# --------------------------------------------------------------------------
# 1. subagent spec excludes every HITL / interrupt source (design §3.1 / §4.3)
# --------------------------------------------------------------------------


def test_agent_factory_subagent_excludes_hitl():
    """_build_researcher_subagent must produce a spec whose tools carry no HITL
    tool and which has no model/permissions/interrupt_on key.

    This is the §3.1 safety basis: with no ask_user in ``tools`` and no
    permissions/interrupt_on, the subagent stack carries no
    HumanInTheLoopMiddleware and no filesystem interrupt -> NO interrupt source,
    so root cause B cannot recur.
    """
    tools = [
        _FakeTool("search_knowledge_base"),
        _FakeTool("my_mcp_tool"),
        _FakeTool("ask_user"),
        _FakeTool("add_text_to_file"),
        _FakeTool("replace_file_lines"),
    ]

    spec = _build_researcher_subagent(tools)

    # same-name override of deepagents' auto default general-purpose (decision 1)
    assert spec["name"] == "general-purpose"

    # required SubAgent keys present; the safety-critical optional keys absent
    assert set(spec.keys()) == {"name", "description", "system_prompt", "tools"}
    assert "model" not in spec, "omitting model => subagent inherits parent tenant model (graph.py:608)"
    assert "permissions" not in spec, "permissions would derive a filesystem interrupt source (§3.1)"
    assert "interrupt_on" not in spec, "interrupt_on would add HumanInTheLoopMiddleware (§3.1)"

    # NO HITL tool reaches the subagent's explicit tools list
    sub_tool_names = {t.name for t in spec["tools"]}
    assert "ask_user" not in sub_tool_names
    assert sub_tool_names.isdisjoint(_KNOWN_HITL_TOOL_NAMES)
    assert sub_tool_names.isdisjoint(_SUBAGENT_TOOL_DENY)


# --------------------------------------------------------------------------
# 2. blacklist default-allows config / KB tools, strips HITL + write tools
# --------------------------------------------------------------------------


def test_agent_factory_subagent_blacklist_passes_config_tools():
    """_subagent_tools is a default-allow BLACKLIST (decision 4): user-configured
    MCP/business tools + SearchKnowledgeBase pass through; only HITL +
    write-side-effect tools are stripped.
    """
    mcp = _FakeTool("my_mcp_tool")
    kb = _FakeTool("search_knowledge_base")
    hitl = _FakeTool("ask_user")
    writer = _FakeTool("add_text_to_file")

    tools = [mcp, kb, hitl, writer]
    result = _subagent_tools(tools)
    result_names = {t.name for t in result}

    # default-allow: config + KB tools pass through (identity preserved)
    assert mcp in result
    assert kb in result
    assert result_names.issuperset({"my_mcp_tool", "search_knowledge_base"})

    # blacklist: HITL + write side-effect tools stripped
    assert "ask_user" not in result_names
    assert "add_text_to_file" not in result_names


# --------------------------------------------------------------------------
# 2b. system / researcher prompt advertise search_knowledge_base IFF available
# --------------------------------------------------------------------------


def test_system_prompt_drops_kb_tool_when_unavailable():
    """When no KB / knowledge space is selected, search_knowledge_base is NOT
    injected (init_linsight_tools returns [] for an empty whitelist). The prompt
    must NOT advertise it then — otherwise the model calls a tool that isn't
    bound and trips ``knowledge_id: Field required``.
    """
    from bisheng.linsight.domain.services.agent_factory import (
        _build_linsight_system_prompt,
        _build_researcher_prompt,
    )

    for builder in (_build_linsight_system_prompt, _build_researcher_prompt):
        with_kb = builder(True)
        without_kb = builder(False)
        # no leftover template markers in either variant
        assert "__KB_" not in with_kb
        assert "__KB_" not in without_kb
        # lockstep: mentioned IFF the tool is available
        assert "search_knowledge_base" in with_kb
        assert "search_knowledge_base" not in without_kb


def test_delegation_restates_kb_ids_only_when_kb_present():
    """Lockstep for the task-delegation KB rule (方案 A).

    A subagent only ever sees the task ``description`` — deepagents replaces its
    messages with ``[HumanMessage(description)]`` (subagents.py
    ``_validate_and_prepare_state``), so it never sees the "可用知识库" block in
    the main graph's first user message. Because ``search_knowledge_base``
    requires a ``knowledge_id``, the main prompt must tell the model to restate
    the ids in ``description`` — but ONLY when a KB exists, else it would coax a
    ``knowledge_id`` for a tool that isn't bound (the same prompt/tool mismatch
    the rest of this file guards).
    """
    from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt

    with_kb = _build_linsight_system_prompt(True)
    without_kb = _build_linsight_system_prompt(False)
    # With a KB: the delegation rule names knowledge_id so the subagent can search.
    assert "knowledge_id" in with_kb
    # Without a KB: nothing to search -> no knowledge_id delegation rule (lockstep).
    assert "knowledge_id" not in without_kb
    # The self-contained-description contract is unconditional (a subagent never
    # sees the parent context regardless of whether a KB is selected).
    assert "自包含" in with_kb
    assert "自包含" in without_kb


def test_researcher_subagent_prompt_tracks_kb_tool_presence():
    """_build_researcher_subagent must mention search_knowledge_base only when the
    filtered subagent tool subset actually contains it (lockstep with the graph)."""
    # KB tool present -> advertised
    spec_with = _build_researcher_subagent([_FakeTool("search_knowledge_base"), _FakeTool("my_mcp_tool")])
    assert "search_knowledge_base" in spec_with["system_prompt"]

    # KB tool absent -> not advertised
    spec_without = _build_researcher_subagent([_FakeTool("my_mcp_tool")])
    assert "search_knowledge_base" not in spec_without["system_prompt"]


# --------------------------------------------------------------------------
# 3. stream mapper drops a subagent's namespaced write_todos (design §5.2a)
# --------------------------------------------------------------------------


def _todos_chunk() -> dict:
    return {
        "tools": {
            "todos": [
                {"content": "子代理内部的待办A", "status": "in_progress"},
                {"content": "子代理内部的待办B", "status": "pending"},
            ]
        }
    }


def test_stream_mapper_ignores_subagent_todos():
    """A namespaced (subagent) write_todos update must produce NO plan events;
    the SAME chunk with ns=None (main graph) must produce them.

    Otherwise the subagent's own TodoListMiddleware todos would pollute the main
    graph's single plan with bogus GenerateSubTask/TaskStart/TaskEnd.
    """
    # --- namespaced (subagent) update: dropped, no plan events ---
    sub_mapper = StreamEventMapper(svid=SVID)
    sub_events = sub_mapper.normalize("updates", _todos_chunk(), namespace=("research_subagent:0",))
    assert not any(isinstance(e, GenerateSubTask) for e in sub_events)
    assert not any(isinstance(e, TaskStart) for e in sub_events)
    assert not any(isinstance(e, TaskEnd) for e in sub_events)
    assert sub_events == []
    # the main plan stays empty — subagent todos never merged into ctx.todos
    assert sub_mapper.ctx.todos == []

    # --- main-graph update (ns is None): SAME chunk DOES drive the plan ---
    main_mapper = StreamEventMapper(svid=SVID)
    main_events = main_mapper.normalize("updates", _todos_chunk(), namespace=None)
    assert any(isinstance(e, GenerateSubTask) for e in main_events), (
        "main-graph todos must still emit GenerateSubTask (byte-identical behavior)"
    )
    assert any(isinstance(e, TaskStart) for e in main_events), (
        "the in_progress todo must still emit TaskStart on the main graph"
    )
    # main plan was populated
    assert len(main_mapper.ctx.todos) == 2


# --------------------------------------------------------------------------
# 4. namespaced internal tool keeps its REAL step_type + carries ns (B1)
# --------------------------------------------------------------------------


def test_stream_mapper_namespaced_tool_keeps_real_step_type():
    """B1: a namespaced (subagent-internal) tool-call must surface as its REAL
    step_type (knowledge here), NOT step_type='subagent'.

    Tagging every namespaced internal call as 'subagent' made the UI render a
    bogus "委派 N 个 search_knowledge_base 子智能体" row per tool. The fix: the
    namespace only rides in extra_info for grouping; step_type stays the
    name-inferred real type. The SAME tool with ns=None is identical (knowledge).
    """
    from langchain_core.messages import AIMessage

    mapper = StreamEventMapper(svid=SVID)
    # tools:<uuid> is the real flat subgraph namespace form deepagents emits
    sub_ns = ("tools:9c3a0a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b",)
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_sub_1", "name": "search_knowledge_base", "args": {"q": "竞品"}}],
    )

    events = [e for e in mapper.normalize("messages", (msg, {}), namespace=sub_ns) if isinstance(e, ExecStep)]

    assert events, "a namespaced tool-call must still surface as an ExecStep"
    step = events[0]
    # B1: namespace no longer rewrites step_type — knowledge inference wins
    assert step.step_type == "knowledge"
    assert step.extra_info.get("namespace") == sub_ns[0]
    assert step.call_id == "call_sub_1"

    # sanity contrast: the SAME tool with ns=None is the same (knowledge) step
    main_mapper = StreamEventMapper(svid=SVID)
    main_events = [e for e in main_mapper.normalize("messages", (msg, {}), namespace=None) if isinstance(e, ExecStep)]
    assert main_events and main_events[0].step_type == "knowledge"
    assert "namespace" not in main_events[0].extra_info


# --------------------------------------------------------------------------
# 5. main-graph `task` tool IS the single delegation point (B2)
# --------------------------------------------------------------------------


def test_stream_mapper_main_task_is_subagent_delegation():
    """B2: the main-graph (ns=None) ``task`` tool call is the ONLY delegation
    boundary. It must surface as step_type='subagent', with name reshaped to the
    delegated subagent_type (default 'general-purpose') and the delegation goal
    (description) carried into both call_reason and extra_info['delegate_goal'].

    A plain main-graph tool row keeps an empty call_reason (no delegate_goal).
    """
    from langchain_core.messages import AIMessage

    mapper = StreamEventMapper(svid=SVID)
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_task_1",
                "name": "task",
                "args": {"description": "对标三家同行 2024Q3 毛利率"},
            }
        ],
    )

    events = [e for e in mapper.normalize("messages", (msg, {}), namespace=None) if isinstance(e, ExecStep)]
    assert events
    step = events[0]
    assert step.step_type == "subagent"
    # subagent_type omitted -> default general-purpose; literal "task" is replaced
    assert step.name == "general-purpose"
    assert step.call_reason == "对标三家同行 2024Q3 毛利率"
    assert step.extra_info.get("delegate_goal") == "对标三家同行 2024Q3 毛利率"
    # delegation point is the MAIN graph -> no namespace on the row itself
    assert "namespace" not in step.extra_info


def test_stream_mapper_task_uses_explicit_subagent_type():
    """When the model passes an explicit subagent_type, the row name uses it."""
    from langchain_core.messages import AIMessage

    mapper = StreamEventMapper(svid=SVID)
    msg = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_task_2",
                "name": "task",
                "args": {"subagent_type": "research-agent", "description": "调研框架 A"},
            }
        ],
    )
    step = next(e for e in mapper.normalize("messages", (msg, {}), namespace=None) if isinstance(e, ExecStep))
    assert step.step_type == "subagent"
    assert step.name == "research-agent"
    assert step.call_reason == "调研框架 A"


def test_stream_mapper_plain_main_tool_has_no_delegate_goal():
    """A non-task main-graph tool keeps call_reason empty and no delegate_goal."""
    from langchain_core.messages import AIMessage

    mapper = StreamEventMapper(svid=SVID)
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call_tool_1", "name": "write_file", "args": {"path": "output/x.md"}}],
    )
    step = next(e for e in mapper.normalize("messages", (msg, {}), namespace=None) if isinstance(e, ExecStep))
    assert step.step_type == "tool"
    assert step.call_reason == ""
    assert "delegate_goal" not in step.extra_info
