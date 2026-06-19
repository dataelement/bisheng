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
from bisheng.linsight.domain.services.resilience_middleware import build_resilience_middleware
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
        "export_docx",  # write side-effect — deliverable export stays in the main graph
        "export_pdf",  # write side-effect — deliverable export stays in the main graph
    }
)
# Runtime double safety: even if someone forgets to register a HITL tool in
# _SUBAGENT_TOOL_DENY, every known HITL tool name is also force-stripped here.
_KNOWN_HITL_TOOL_NAMES = frozenset({"ask_user"})

# Chinese system prompt for the researcher subagent (design #1 §4.1 / §4.4),
# adapted from the deepagents demo RESEARCH_SUBAGENT_PROMPT. The subagent runs in
# an isolated context window and returns only a distilled, sourced summary.
# Template: __KB_RESEARCH_LINE__ is resolved by _build_researcher_prompt() so the
# search_knowledge_base mention stays in lockstep with whether that tool is
# actually injected into the subagent (no KB selected -> tool absent -> no mention).
_LINSIGHT_RESEARCHER_PROMPT_TEMPLATE_ZH = """你是调研子代理（researcher）。你的职责是深入调研主智能体派发给你的**单一**子任务，并返回结构化、有出处的摘要。

工作约定：
__KB_RESEARCH_LINE__
- 多轮逐步细化查询：先广后窄，根据已检索到的内容不断调整下一轮查询，直到信息足够支撑结论。
- 中间产物（草稿、笔记、原始检索摘录）只写入工作区 scratch/ 目录，绝不写 output/。最终交付物的撰写与拼装由主智能体负责，不归你管。
- 你**没有** ask_user 工具，也不得以任何方式向用户提问；遇到信息不足时基于已掌握的资料给出最佳结论并说明不确定性，而不是停下来等待澄清。
- 调用方（主智能体）只能看到你的**最后一条消息**。因此请把蒸馏后的结论（含关键事实、出处/来源标识、必要的不确定性说明）作为最后一条消息完整回传，不要把结论只留在中间步骤里。

请使用简体中文进行调研与回传。"""

# Chinese system prompt for the Linsight task-mode agent (design §2.4). Kept
# inline so it stays co-located with the factory. No call_reason schema is
# injected — step titles come from deepagents' native tool output (the frontend
# renders the tool name); only the HITL interrupt reason is model-authored.
# Template: __KB_EXEC_LINE__ / __KB_TOOL_LINE__ are resolved by
# _build_linsight_system_prompt() so search_knowledge_base is advertised IFF the
# tool is actually injected. When no KB / knowledge space is selected the tool is
# not bound (init_linsight_tools returns [] for an empty whitelist); advertising
# it anyway pushes the model to call a tool that isn't there -> the
# "knowledge_id: Field required" failure. Keeping prompt and tool list in lockstep
# removes the contradiction at the source.
_LINSIGHT_SYSTEM_PROMPT_TEMPLATE_ZH = """你是深度研究任务智能体，负责把用户的复杂任务拆解为可执行的待办清单并逐项完成，最终产出结构化、有依据的交付物。

# 工作流程（必须严格按顺序执行）

0. 【先澄清，再动手】先判断请求是否“明确”。一个请求是明确的，当且仅当同时满足：
   (a) 有清晰的目标产出——你清楚要做出/交付什么；
   (b) 完成它所需、且只有用户本人才知道的关键信息都已给出（个人情况、偏好、目标、约束、预算、时间安排、具体数据，或在多个合理方案间的选择等）。
   只要 (a) 或 (b) 缺失或不明确，就【只调用一次 ask_user，然后立即结束本轮】：
   - 不要输出任何普通文字回复——澄清卡本身就是你的回应；
   - 【questions 必须结构化、不能为空】把每个缺失项写成一个带 2-4 个预设选项（options）的问题，让用户点选；只给 reason 而把 questions 留空、或把问题塞进 reason 文字里，都是错误的；
   - 同一轮内不要调用任何其它工具（连 write_todos 也不行）；
   - 待 ask_user 返回用户答案后，再进入第 1 步，并据此设定任务范围与做法。
   能用下方“默认假设”合理补齐的不要问——只问“只有用户知道、且不问就会做错”的关键缺口。
   【整个会话最多澄清一轮】：用户回答后若仍有个别字段不明确，直接采用“默认假设”推进，绝不第二次调用 ask_user。
   ask_user 必须由你本人（主智能体）在主流程中直接调用；所有澄清必须在创建任何子任务（task）之前一次性问完，严禁通过 task 工具/子代理调用 ask_user（子代理没有 ask_user，无法向用户提问）。

1. 【规划】调用 write_todos 写出有编号的待办清单（通常 3-6 项，含一个“产出交付物”收尾项）。

2. 【执行】按清单逐项推进，选用合适工具：
__KB_EXEC_LINE__
   - 对“独立、需多轮检索/阅读、产出可蒸馏为一段摘要”的子任务，可用 task 委派给 "general-purpose" 子代理做隔离调研（它在独立上下文检索/阅读，只把蒸馏后的有出处摘要回传给你）；同一时刻并行委派不超过 2~3 个。
__KB_DELEGATE_LINE__   更新待办时只翻转 status（pending/in_progress/completed），不改写已有文案，以保证任务标识稳定；同一时刻只允许一个待办处于 in_progress。

3. 【产出交付物】按用户在澄清时选择的输出格式产出，markdown 是唯一规范源：
   - 3a（始终）：write_file 写 output/<name>.md（结构化 markdown，其它格式由它派生）。
   - 3b（仅当选了 html）：write_file 写 output/<name>.html（完整自包含 HTML，内联样式，无外部脚本/CDN）。
   - 3c（仅当选了 docx）：export_docx(source_path="output/<name>.md")，必须在 3a 之后。
   - 3d（仅当选了 pdf）：export_pdf(source_path="output/<name>.md")，必须在 3a 之后。
   最终交付物的撰写与拼装必须由你（主智能体）亲自完成，不得委派给子代理；中间产物写 scratch/。

4. 【收尾】用 2-3 句话告知用户产出了哪些文件（例如“已完成。见 output/report.md 与 output/report.docx”）。

# 如何填写 ask_user（仅第 0 步触发时）

- reason：一句话说明为何需要先确认，使用与用户输入一致的语言。
- questions：1-3 个（**不能为空数组**），按“对结果影响最大”优先排序（任务范围/目标 > 输出格式/形态 > 其它细节）。每个形如：{"question": "完整问题文本", "options": [...], "multiple": false}
  - 每个问题**必须给 2-4 个具体预设选项**（options），每项是一个简短的选项文案（纯字符串），优先让用户点选；只有该信息天然无法预设选项（如“请输入你的身高”）时，才把该问题的 options 留空走开放输入——但问题本身仍要写出来，不能整个 questions 留空。
  - 多选问题（multiple=true，如输出格式）：用户可勾选多项。
  - 收集“输出格式”用一个多选问题，选项含 markdown / html / docx / pdf。
- 一次性把所有要问的问完。不要罗列工具或能力限制，也不要预先解释工作流。

# 默认假设（无需追问，缺失时直接采用）

- 输出语言：始终与用户输入语言一致（中文输入则中文交付，英文则英文，不写死中文）。
- 输出格式：默认仅 markdown；仅当用户明确选择才追加 html / docx / pdf，不要擅自猜测。
- 深度：3-5 个子任务 + 1 个“产出交付物”待办。
- 受众：具备一定背景的通用读者；时间范围：近 12 个月，除非主题本身具有历史性。
- 凡能从常识或上下文合理推断的偏好/参数：直接推断，不要问。
- 仅当信息“只有用户本人才知道、且影响结果正确性”时才值得澄清。

# 你可用的工具

- ask_user(reason, questions)：第 0 步澄清；整个会话最多调用一次。
- write_todos(todos)：维护有编号的待办清单；只翻转 status，不改写已有文案。
__KB_TOOL_LINE__- write_file / read_file / edit_file / ls：工作区文件工具；交付物写 output/，中间产物写 scratch/。
- export_docx(source_path, dest_path)：把 output/ 下的 markdown 转 Word(.docx)，必须在对应 .md 写好之后。
- export_pdf(source_path, dest_path)：把 output/ 下的 markdown 转 PDF，必须在对应 .md 写好之后。
- task(description, subagent_type="general-purpose")：把独立、可隔离、较重的调研子任务委派给子代理。description 必须自包含——子代理看不到你的对话历史与上下文，只能读到 description，因此完成该子任务所需的全部背景、目标、约束与必要标识都要写进去；不得委派最终交付物撰写，也不得委派“问用户/澄清”。

# 风格

- 简洁，工具调用之间不加多余解释性文字。
- 不要凭空编造事实；交付内容应基于检索到的资料/依据。
- 面向用户的所有文字（ask_user 的 reason、最终回复、交付物正文）一律与用户输入语言保持一致。"""

# search_knowledge_base is the ONLY tool whose presence is conditional on the
# user's knowledge selection (init_linsight_tools drops it when the whitelist is
# empty). The prompt advertisement must track it — see _build_*_prompt below.
_KB_TOOL_NAME = "search_knowledge_base"


def _build_linsight_system_prompt(has_knowledge_base: bool) -> str:
    """Resolve the main system prompt, toggling search_knowledge_base mentions.

    When no KB / knowledge space is selected the tool is NOT injected (the empty
    whitelist makes init_linsight_tools return []), so advertising it would push
    the model to call a tool that isn't bound — exactly the
    ``knowledge_id: Field required`` failure. Keep the prompt and the tool list in
    lockstep: the search_knowledge_base lines appear IFF the tool is present.
    """
    if has_knowledge_base:
        exec_line = (
            "   - 需要资料时用 search_knowledge_base 检索知识库/知识空间；"
            "读写文件用 write_file / read_file / edit_file / ls。"
        )
        tool_line = "- search_knowledge_base：在授权的知识库/知识空间语义检索。\n"
        # Delegation must restate the KB ids: a subagent's messages are replaced
        # with ONLY the task `description` (deepagents subagents.py
        # _validate_and_prepare_state), so it never sees the "可用知识库" block in
        # the main graph's first user message. search_knowledge_base requires a
        # knowledge_id, so without the ids in `description` the subagent cannot
        # search and silently degrades. Advertise this rule IFF a KB exists.
        delegate_line = (
            "   - 用 task 委派需要检索知识库/知识空间的子任务时，必须在 description 中"
            "明确列出本次可检索的知识库及其 knowledge_id（子代理看不到上面的“可用知识库”"
            "清单，只能读到 description；不写明 id 它就无法检索知识库，只能空跑或退化为"
            "仅凭自身知识作答）。\n"
        )
    else:
        exec_line = (
            "   - 读写文件用 write_file / read_file / edit_file / ls；若用户上传了文件，"
            "用 ls / read_file 在工作区中查阅。本次任务没有可检索的知识库/知识空间，"
            "请基于已有资料与自身知识完成，不要调用任何知识库检索工具。"
        )
        tool_line = ""
        delegate_line = ""
    return (
        _LINSIGHT_SYSTEM_PROMPT_TEMPLATE_ZH.replace("__KB_EXEC_LINE__", exec_line)
        .replace("__KB_TOOL_LINE__", tool_line)
        .replace("__KB_DELEGATE_LINE__", delegate_line)
    )


def _build_researcher_prompt(has_knowledge_base: bool) -> str:
    """Resolve the researcher subagent prompt (same lockstep rule as the main one).

    The subagent receives search_knowledge_base only when it is in the filtered
    tool subset (_subagent_tools), which mirrors the main graph; advertise it only
    when it is actually available.
    """
    if has_knowledge_base:
        research_line = (
            "- 优先使用 search_knowledge_base 检索知识库/知识空间，并用 read_file / ls 阅读工作区中已有的资料。"
        )
    else:
        research_line = (
            "- 用 read_file / ls 阅读工作区中已有的资料；本次没有可检索的知识库/知识空间，"
            "不要调用任何知识库检索工具，基于已有资料与自身知识给出结论。"
        )
    return _LINSIGHT_RESEARCHER_PROMPT_TEMPLATE_ZH.replace("__KB_RESEARCH_LINE__", research_line)


@tool
async def ask_user(reason: str, questions: list[dict] | None = None) -> str:
    """需要用户补充信息、做选择或确认时调用本工具暂停任务并向用户提问；用户回答后任务自动继续。

    只有调用本工具才会真正暂停等待用户输入——不要直接用普通文字提问后就结束任务。

    Args:
        reason: 总体说明，使用与用户输入一致的语言（例如“为了制定计划，请先确认以下问题”）。
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
    sub_tools = _subagent_tools(tools)
    has_kb = any(t.name == _KB_TOOL_NAME for t in sub_tools)
    return {
        "name": "general-purpose",
        "description": (
            "用于隔离的调研/分析子任务：在独立上下文中多轮检索与阅读资料，"
            "返回蒸馏后的、有出处的结构化摘要。它不能向用户提问，也不负责最终交付物的撰写与拼装。"
        ),
        "system_prompt": _build_researcher_prompt(has_kb),
        "tools": sub_tools,
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
    #
    # LLM resilience (灵思LLM容错): wrap the (bind_tools'd) model handler so a
    # transient model failure retries with backoff and a content-filter / other
    # non-retryable hit fails cleanly here on the MAIN graph (a no-tool-call
    # synthetic message would only end the loop mid-reasoning). The subagent gets
    # its OWN instance (is_subagent=True) that DEGRADES instead — see below.
    linsight_conf = settings.get_linsight_conf()
    middlewares: list = [build_resilience_middleware(linsight_conf, is_subagent=False)]

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
    #
    # Export tools (export_docx / export_pdf): closure-injected with the session
    # WorkspaceBackend, appended to the MAIN graph only. They are NOT in `tools`
    # (so the researcher never inherits them) and are also listed in
    # _SUBAGENT_TOOL_DENY as belt-and-suspenders — deliverable export stays in the
    # main graph. init_linsight_export_tools returns [] for a non-writable backend
    # (e.g. the test FakeWorkspaceBackend), so the tools never surface when unusable.
    from bisheng.tool.domain.langchain.linsight_export import init_linsight_export_tools

    export_tools = init_linsight_export_tools(backend)
    # The researcher subagent is a separate subgraph: the main-graph middleware
    # above does NOT wrap its internal model calls, so it carries its OWN
    # resilience instance (is_subagent=True) which DEGRADES a content-filter /
    # exhausted-transient step to a synthetic reply — letting the parent task
    # continue with the remaining steps (Layer B partial-result win).
    researcher = _build_researcher_subagent(tools)
    researcher["middleware"] = [build_resilience_middleware(linsight_conf, is_subagent=True)]
    # Advertise search_knowledge_base in the system prompt IFF it is actually in
    # `tools` (init_linsight_tools injects it only when the user selected a KB /
    # knowledge space). Keeps the prompt and the bound tool list in lockstep so the
    # model is never told to call a tool that isn't there (root cause of the
    # "knowledge_id: Field required" error when no KB is selected).
    has_kb = any(t.name == _KB_TOOL_NAME for t in tools)
    return create_deep_agent(
        model=model,
        tools=[*tools, ask_user, *export_tools],
        system_prompt=_build_linsight_system_prompt(has_kb),
        middleware=middlewares,
        subagents=[researcher],
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
