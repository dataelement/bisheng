"""F035 Track A · TA-3: deepagents agent factory.

``create_linsight_agent`` is the single装配点 that replaces the legacy
``LinsightAgent`` construction (``task_exec.py::_create_agent``). It calls
``deepagents.create_deep_agent`` and returns a ``CompiledStateGraph`` driven by
``agent.astream(...)`` in the executor.

Design references (features/v2.6.0/035-linsight-task-mode/design.md):
- §2.1 装配点改造 (_create_agent -> create_deep_agent)
- §2.2 / §2.2.1 model 注入 (LLMService, per-task model_id)
- §2.3 / C5 checkpointer (Wave1: InMemorySaver; real: PlainRedisCheckpointer)
- §2.4 system_prompt 中文化
- §3.8 历史消息压缩中间件 (SummarizationMiddleware if available)
- §5.1 工具注入: BaseTool 直传

Wave 1 scope: backend = FakeWorkspaceBackend stub (C2), checkpointer =
InMemorySaver. Integration (Wave 2) swaps in the real WorkspaceBackend (Track C)
and PlainRedisCheckpointer (Track B) — those owners change task_exec wiring, not
this factory's signature.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from bisheng.common.services.config_service import settings
from bisheng.llm.domain.services import LLMService

# --- Subagent (researcher) tool blacklist (design #1 §4.3 / §5.1, decision 4) ---
# The researcher subagent gets a BLACKLIST-filtered subset of the main graph's
# `tools` arg (user-configured MCP/business tools + SearchKnowledgeBase). Default
# allow keeps research powerful; only HITL/interrupt and write-side-effect tools
# are denied. The subagent NEVER receives ask_user (it is injected separately into
# the MAIN graph as [*tools, ask_user], so it is not even in `tools`; listed here
# as belt-and-suspenders), so its only interrupt source is removed by construction.
#
# ⚠️ MAINTENANCE CONTRACT: ANY newly added HITL/interrupt tool OR write-side-effect
#    tool MUST be registered in _SUBAGENT_TOOL_DENY below. Otherwise the blacklist
#    (default-allow) leaks it to the subagent — re-arming root cause B (a subagent
#    that can interrupt) or letting it clobber deliverables in output/.
_SUBAGENT_TOOL_DENY = frozenset(
    {
        "ask_user",  # HITL interrupt source — must stay pinned to the main graph
        "add_text_to_file",  # write side-effect — deliverable assembly stays in main graph
        "replace_file_lines",  # write side-effect
    }
)
# Runtime double safety: even if someone forgets to register a HITL tool in
# _SUBAGENT_TOOL_DENY, every known HITL tool name is also force-stripped here.
_KNOWN_HITL_TOOL_NAMES = frozenset({"ask_user"})

# Chinese system prompt for the researcher subagent (design #1 §4.1 / §4.4),
# adapted from the deepagents demo RESEARCH_SUBAGENT_PROMPT. The subagent runs in
# an isolated context window and returns only a distilled, sourced summary.
LINSIGHT_RESEARCHER_PROMPT_ZH = """你是调研子代理（researcher）。你的职责是深入调研主智能体派发给你的**单一**子任务，并返回结构化、有出处的摘要。

工作约定：
- 优先使用 search_knowledge_base 进行检索（若该工具可用），并用 read_file / ls 阅读工作区中已有的资料。
- 多轮逐步细化查询：先广后窄，根据已检索到的内容不断调整下一轮查询，直到信息足够支撑结论。
- 中间产物（草稿、笔记、原始检索摘录）只写入工作区 scratch/ 目录，绝不写 output/。最终交付物的撰写与拼装由主智能体负责，不归你管。
- 你**没有** ask_user 工具，也不得以任何方式向用户提问；遇到信息不足时基于已掌握的资料给出最佳结论并说明不确定性，而不是停下来等待澄清。
- 调用方（主智能体）只能看到你的**最后一条消息**。因此请把蒸馏后的结论（含关键事实、出处/来源标识、必要的不确定性说明）作为最后一条消息完整回传，不要把结论只留在中间步骤里。

请使用简体中文进行调研与回传。"""

# Chinese system prompt for the Linsight task-mode agent (design §2.4). Kept
# inline so it stays co-located with the factory. No call_reason schema is
# injected — step titles come from deepagents' native tool output (the frontend
# renders the tool name); only the HITL interrupt reason is model-authored.
LINSIGHT_SYSTEM_PROMPT_ZH = """你是深度研究任务智能体，负责把用户的复杂任务拆解为可执行的待办清单并逐项完成。

工作约定：
- 使用 write_todos 维护任务清单；更新待办时只翻转 status（pending/in_progress/completed），不要改写已有文案，以保证任务标识稳定。
- 同一时刻只有一个待办处于 in_progress。
- 当任务依赖只有用户才知道的信息（个人情况、偏好、目标、约束、口味、预算、时间安排、选择等）且这些信息缺失或不明确时，必须先调用 ask_user 工具向用户收集，再开始 write_todos 规划与执行；不要凭空假设或编造，也不要只用普通文字提问后就结束任务。
- 【关键】ask_user 必须由你本人（主智能体）在主流程中**直接调用**，严禁通过 task 工具/子代理来调用 ask_user。所有需要向用户澄清的问题，必须在创建任何子任务（task）之前，一次性用 ask_user 问完；子代理（task）内部不得调用 ask_user。
- 调用 ask_user 时，reason 用中文说明原因，questions 给出结构化的问题与可选项（单选/多选/开放输入）。
- 交付物请写入工作区 output/ 目录；中间产物写入 scratch/。

派发预算（task 委派给子代理 "general-purpose" 的纪律）：
- 何时派发：仅当某个子任务“独立、需多轮检索/阅读、产出可蒸馏为一段摘要”时，才用 task 工具委派给 "general-purpose" 子代理去做隔离调研；它会在独立上下文中检索/阅读并只把蒸馏后的有出处摘要回传给你。
- 不得派发：最终交付物的撰写与拼装必须由你（主智能体）亲自完成，不得委派；也不得把“问用户/澄清”这类工作委派给子代理（子代理没有 ask_user，无法向用户提问）。
- 并发上限：同一时刻并行委派的子代理不超过 2~3 个，避免发散与 token 浪费。

请使用简体中文与用户和工具交互。"""


@tool
async def ask_user(reason: str, questions: list[dict] | None = None) -> str:
    """需要用户补充信息、做选择或确认时调用本工具暂停任务并向用户提问；用户回答后任务自动继续。

    只有调用本工具才会真正暂停等待用户输入——不要直接用普通文字提问后就结束任务。

    Args:
        reason: 总体说明（中文），例如“为了制定计划，请先确认以下问题”。
        questions: 结构化问题列表，每项形如
            {"question": "问题标题", "options": ["选项1", "选项2"], "multiple": false}。
            options 为空表示开放式自由输入；multiple=true 表示多选。没有具体选项时
            questions 可留空，只给 reason。

    Returns:
        用户的回答文本。
    """
    tool_calls = [
        {
            "id": f"q_{i}",
            "name": "clarify",
            "args": {
                "question": str(q.get("question", "")),
                "options": [str(o) for o in (q.get("options") or [])],
                "multiple": bool(q.get("multiple", False)),
            },
        }
        for i, q in enumerate(questions or [])
    ]
    return interrupt({"reason": reason, "params": {"tool_calls": tool_calls}})


def _subagent_tools(tools: Sequence[BaseTool]) -> list[BaseTool]:
    """Filter the main-graph tool list down to the researcher subagent's subset.

    Decision 4 (design #1 §4.3): a BLACKLIST — every tool is allowed for the
    subagent unless it appears in _SUBAGENT_TOOL_DENY (HITL / write side-effects)
    or _KNOWN_HITL_TOOL_NAMES (runtime double safety). ``tools`` here is the
    factory's ``tools`` arg (user-configured MCP/business tools +
    init_linsight_tools' SearchKnowledgeBase); it does NOT contain ask_user, which
    the factory injects separately into the MAIN graph only.

    The returned list MUST be passed as the subagent spec's explicit ``tools`` key
    so deepagents does NOT fall back to inheriting ``[*tools, ask_user]``
    (graph.py:670 — an explicit ``tools`` means the subagent gets ONLY those). The
    subagent still receives ls/read_file/write_file/edit_file + write_todos from
    its own middleware stack (graph.py:618-627), sharing the main WorkspaceBackend.
    """
    return [t for t in tools if t.name not in _SUBAGENT_TOOL_DENY and t.name not in _KNOWN_HITL_TOOL_NAMES]


def _build_researcher_subagent(tools: Sequence[BaseTool]) -> dict:
    """Build the single MVP researcher subagent spec (deepagents ``SubAgent``).

    Design #1 §4.1 (MVP = one researcher) / §4.2 (decision 1: same-name override).

    - ``name="general-purpose"``: providing our own spec with this name SUPPRESSES
      deepagents' auto-injected default general-purpose subagent (graph.py:693), so
      the unsafe default GP — which would inherit ``[*tools, ask_user]`` — never
      gets built. The model decides whether to delegate from ``description``, not
      ``name``, so the honest description below is what actually steers it.
    - ``tools=_subagent_tools(tools)``: explicit subset (blacklist). Explicit
      ``tools`` is REQUIRED so the subagent does not inherit ask_user (§4.3).
    - NO ``model`` key: the subagent inherits the parent's per-task tenant model
      (graph.py:608 ``spec.get("model", model)``).
    - NO ``permissions`` / ``interrupt_on`` keys: this is the SAFETY BASIS
      (design §3.1). Without them the subagent stack carries no
      HumanInTheLoopMiddleware and no filesystem interrupts, so the subagent has
      NO interrupt source at all — root cause B (HITL not bubbling out of a
      subgraph) cannot recur because the subagent simply cannot interrupt.
    """
    return {
        "name": "general-purpose",
        "description": (
            "用于隔离的调研/分析子任务：在独立上下文中多轮检索与阅读资料，"
            "返回蒸馏后的、有出处的结构化摘要。它不能向用户提问，也不负责最终交付物的撰写与拼装。"
        ),
        "system_prompt": LINSIGHT_RESEARCHER_PROMPT_ZH,
        "tools": _subagent_tools(tools),
    }


async def create_linsight_agent(
    session_model,
    tools: Sequence[BaseTool],
    model_id: str | None = None,
    file_dir: str | None = None,
    svid: str | None = None,
    backend=None,
    checkpointer=None,
):
    """Build the deepagents-backed Linsight agent (design §2.1).

    Args:
        session_model: ``LinsightSessionVersion`` (owns tenant_id / user_id).
        tools: LangChain ``BaseTool`` list, passed straight through (§5.1).
        model_id: per-task runtime model id (§2.2.1). When omitted, falls back
            to the tenant's Linsight default model.
        file_dir: local write-through cache dir for the workspace backend.
        svid: session_version_id; defaults to ``session_model.id``.
        backend: workspace backend (Wave1: FakeWorkspaceBackend). When None a
            FakeWorkspaceBackend is constructed (stub default).
        checkpointer: LangGraph checkpointer. When None an InMemorySaver is used
            (Wave1; real run injects PlainRedisCheckpointer, C5).

    Returns:
        ``CompiledStateGraph`` to be driven by ``agent.astream(...)``.
    """
    from deepagents import create_deep_agent

    svid = svid or session_model.id
    model = await _resolve_model(session_model, model_id)

    if backend is None:
        backend = _default_backend(svid, file_dir)
    if checkpointer is None:
        from langgraph.checkpoint.memory import InMemorySaver

        checkpointer = InMemorySaver()

    # F035 Track D — skills middleware DISABLED (2026-06-16): TenantSkillsMiddleware
    # carries its OWN FilesystemBackend (SKILLS_ROOT, virtual_mode). Added after the
    # workspace FilesystemMiddleware it SHADOWS the agent's write_file/read_file, so
    # deliverables written by the agent landed in the skills store instead of the
    # workspace — the workspace ended up empty and no result document was produced.
    # Re-enable only once skills compose without hijacking the workspace filesystem
    # (separate file-tool namespaces). Skills are coarse/optional; the deliverable
    # pipeline is core, so it wins.
    #
    # The `task` tool (subagent delegation) is now RE-ENABLED (design #1). The
    # earlier _ToolExclusionMiddleware({"task"}) that stripped it has been removed;
    # the over-delegation + HITL-bubbling root causes are now defused by
    # construction, not by removing the tool — see _build_researcher_subagent
    # (subagent has no interrupt source) and the delegation-budget prompt section.
    middlewares: list = []

    # No custom history-compression middleware: deepagents already ships a
    # built-in summarization middleware (deepagents.middleware.summarization),
    # so injecting our own duplicated it and tripped langchain's "duplicate
    # middleware instances" assertion. The legacy 2.0 ``tool_buffer`` compression
    # (design §3.8) is therefore retired in favor of the deepagents built-in.
    # ask_user (HITL): a tool that calls langgraph ``interrupt()`` so the agent
    # can park-and-release for user input (F035 §4.6); deepagents ships no
    # built-in ask-human tool, so we inject our own.
    # design #1 §4.1/§4.2: a single MVP researcher subagent, named
    # "general-purpose" to suppress deepagents' auto default GP (graph.py:693).
    # ask_user is appended ONLY to the MAIN graph tools below; the subagent
    # receives _subagent_tools(tools), which never includes ask_user.
    return create_deep_agent(
        model=model,
        tools=[*tools, ask_user],
        system_prompt=LINSIGHT_SYSTEM_PROMPT_ZH,
        middleware=middlewares,
        subagents=[_build_researcher_subagent(tools)],
        backend=backend,
        checkpointer=checkpointer,
        store=None,
    )


async def _resolve_model(session_model, model_id: str | None) -> BaseChatModel:
    """Resolve the per-task model via LLMService (design §2.2 / §2.2.1).

    Priority: per-task ``model_id`` -> tenant Linsight default model. Tenant
    resolution + share fallback live inside ``get_bisheng_linsight_llm``
    (INV-T18: tenant_id is threaded explicitly in the Worker subprocess).
    """
    workbench_conf = await LLMService.get_workbench_llm(tenant_id=session_model.tenant_id)
    linsight_conf = settings.get_linsight_conf()

    resolved_id = model_id
    if resolved_id is None:
        # F035 (Track E): per-task model omitted -> fall back to the tenant
        # Linsight default model id. task_model has been removed.
        resolved_id = workbench_conf.linsight_default_model_id
        if resolved_id is None:
            raise ValueError(
                "No model resolved: per-task model_id is empty and the tenant "
                "linsight_default_model_id is not configured"
            )

    return await LLMService.get_bisheng_linsight_llm(
        invoke_user_id=session_model.user_id,
        model_id=resolved_id,
        temperature=linsight_conf.default_temperature,
    )


def _default_backend(svid: str, file_dir: str | None):
    """Wave-1 default backend: in-memory FakeWorkspaceBackend (C2 stub).

    The real ``WorkspaceBackend`` (MinIO truth + write-through cache) is Track
    C's deliverable and is injected at integration; this keeps the factory
    runnable in isolation.
    """
    try:
        from test.linsight.fixtures.fake_workspace_backend import FakeWorkspaceBackend
    except Exception:
        # TODO(F035 C2): the FakeWorkspaceBackend stub lives under test/; in a
        # production path the real WorkspaceBackend must be passed explicitly.
        raise NotImplementedError(
            "No workspace backend supplied and FakeWorkspaceBackend stub is "
            "unavailable. Pass backend=WorkspaceBackend(...) explicitly (C2)."
        )
    return FakeWorkspaceBackend(svid=svid, file_dir=file_dir)
