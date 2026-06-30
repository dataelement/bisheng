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

import json
from collections.abc import Sequence
from typing import Annotated

from json_repair import json_repair
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState
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

请全程使用与任务描述一致的语言（默认简体中文）——这**包括你的思考与推理过程（thinking）**、调研旁白与最终回传，绝不允许“用英文思考、再用中文回传”。"""

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

# 使用语言

全程（**包括你的思考与推理过程（thinking）、任务规划、工具调用前后的简短旁白、写入文件的中间笔记、向用户的提问、最终回复与交付物正文**。）使用与用户输入一致的语言：用户用中文则全程中文，用户用英文则全程英文。

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
__KB_DELEGATE_LINE__   更新待办时只翻转 status（pending/in_progress/completed），不改写已有文案，以保证任务标识稳定。

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
- 【正确示例】questions 必须是这样的 JSON 数组（照此结构直接填——切勿把问题写进 reason，也切勿把数组序列化成字符串）：
  questions=[
    {"question": "你想构建哪一类 agent？", "options": ["对话/工具调用型（LLM Agent）", "自动化流程/任务编排型", "检索增强问答型（RAG）"], "multiple": false},
    {"question": "主要落地场景或用途是？", "options": ["客服答疑", "数据分析与报告", "内容创作", "研发/代码辅助"], "multiple": false},
    {"question": "希望的交付格式？", "options": ["markdown", "html", "docx", "pdf"], "multiple": true}
  ]

# 默认假设（无需追问，缺失时直接采用）
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
"""

# search_knowledge_base is the ONLY tool whose presence is conditional on the
# user's knowledge selection (init_linsight_tools drops it when the whitelist is
# empty). The prompt advertisement must track it — see _build_*_prompt below.
_KB_TOOL_NAME = "search_knowledge_base"

# Static Chinese language directive, appended to the ABSOLUTE TAIL of the system
# message by _LanguageTailMiddleware (below).
#
# Why a middleware and not a HarnessProfile suffix: deepagents builds the STATIC
# base as USER -> BASE -> (profile SUFFIX), but its framework middleware
# (TodoList / Filesystem / SubAgent, all English) then APPEND ~5000 chars to the
# system message via wrap_model_call AFTER that base. So a profile suffix is NOT
# actually last — it is buried mid-prompt, and the trailing English still drifts
# the model's reasoning to English (observed: 中文输入仍出现英文 thinking). The
# ONLY way to reach the true tail (after every framework prompt) is a middleware
# placed LAST in the stack — it appends after Filesystem/SubAgent, so the
# directive is the final text the model reads. Static content -> the assembled
# system message stays byte-identical across calls -> still prefix-cacheable.
_LINSIGHT_LANGUAGE_DIRECTIVE_ZH = """# 语言要求（仅约束输出语言，不改变上文其它任何要求）

请全程使用与用户输入一致的语言：用户用中文输入，则你的**思考与推理过程（thinking / reasoning）、任务规划、工具调用前后的旁白、写入文件的中间笔记、向用户的提问、最终回复与交付物正文**全部使用简体中文；用户用英文则全程使用英文。**尤其是思考与推理过程必须与回复语言一致**，绝不允许“先用英文思考、再用中文回复”。本要求只关于语言，其优先级高于上文与语言有关的说明（含框架内置的英文说明）；上文关于工作流程、工具使用、委派预算与交付的要求一律照常严格遵守，不受本要求影响。"""


class _LanguageTailMiddleware(AgentMiddleware):
    """Append a fixed language directive to the ABSOLUTE TAIL of the system message.

    deepagents' framework middleware (TodoList / Filesystem / SubAgent) inject
    their English system prompts via ``wrap_model_call`` ->
    ``append_to_system_message`` in middleware-list order (first = outermost =
    appends first; last = appends last). A HarnessProfile ``system_prompt_suffix``
    lands in the STATIC base (USER+BASE+SUFFIX), which is BEFORE those middleware
    appends — so it is not actually last. Placed as the LAST middleware in the
    stack, this appends AFTER every framework prompt, so the directive is the
    final text the model reads — the strongest position to override the preceding
    English and keep reasoning in the user's language.

    Stateless + static text -> deterministic and cache-safe: ``override`` is
    immutable (langchain rebuilds a fresh ModelRequest from the static base each
    model turn), so there is no cross-call accumulation. ``tools = []`` registers
    no extra tools. Both sync/async hooks are implemented (base raises for the
    unimplemented path; the linsight worker runs async).
    """

    def __init__(self, directive: str) -> None:
        super().__init__()
        self.tools = []
        self._directive = directive

    @property
    def name(self) -> str:
        return "LinsightLanguageTail"

    def _append(self, request):
        from deepagents.middleware._utils import append_to_system_message

        return request.override(system_message=append_to_system_message(request.system_message, self._directive))

    def wrap_model_call(self, request, handler):
        return handler(self._append(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._append(request))


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


def _loads_tolerant(s: str) -> object | None:
    """``json.loads`` first; on failure fall back to ``json_repair`` (which fixes
    unescaped quotes, missing brackets, trailing junk, …). Returns the parsed
    object, or ``None`` when even the repair yields nothing usable."""
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return json_repair.loads(s)
    except Exception:
        return None


def _recover_question_items(s: str) -> list[dict]:
    """Recover one or more question dicts from a single string element.

    A well-behaved model puts each question object (or a plain question string)
    as its own list element. A misbehaving one (observed live, session
    9aef4773…) stringifies the WHOLE remaining ``questions`` array into a single
    element AND drops its opening ``[{"question": "`` while leaving inner quotes
    unescaped — so ``json.loads`` fails and the old code wrapped the entire 500‑char
    blob as one bogus question's text (the user then saw raw JSON). Here we:
      - treat a marker-free string as a legitimate open-ended question (unchanged);
      - otherwise try a few reconstructions (raw / bracket-wrapped / opening-prefix
        restored) through ``_loads_tolerant`` and keep the variant yielding the most
        question-bearing dicts. Recovers nothing usable ⇒ ``[]`` (degrade, never a blob).
    """
    s = s.strip()
    if not s:
        return []
    # No JSON structure at all → a plain prose question.
    if not any(marker in s for marker in ('"question"', '"options"', "{", "[")):
        return [{"question": s}]
    candidates = [s, "[" + s + "]"]
    # Only restore a dropped opening ``[{"question": "`` when the blob actually
    # looks like it lost its head (starts mid-value, not with ``{``/``[``). This
    # targets the observed failure precisely without corrupting a complete dict
    # that merely lacks a ``question`` key into a bogus one.
    if not s.startswith(("{", "[")):
        candidates.append('[{"question": "' + s)
    best: list[dict] = []
    for cand in candidates:
        parsed = _loads_tolerant(cand)
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = [parsed]
        else:
            items = []
        qs = [q for q in items if isinstance(q, dict) and str(q.get("question", "")).strip()]
        if len(qs) > len(best):
            best = qs
    return best


def _normalize_to_dicts(value: object) -> list[dict]:
    """Structural normalization shared by ``_coerce_questions`` and
    ``_salvage_options_only``: parse the (possibly stringified, or per-item
    stringified) ``questions`` payload into a flat list of dict candidates WITHOUT
    the final "must carry question text" filter. The result MAY include options-only
    dicts and debris — each caller applies its own keep-rule. Degrades to ``[]``
    (never raises) on anything unparseable.
    """
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        # A malformed top-level string degrades to [] (park with reason only) — the
        # observed failure mode is a malformed element INSIDE a list, handled below.
        try:
            value = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(value, list):
        return []

    out: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.extend(_recover_question_items(item))
        elif isinstance(item, list):
            # a smuggled nested array of question dicts
            out.extend(q for q in item if isinstance(q, dict))
    return [q for q in out if isinstance(q, dict)]


def _coerce_questions(value: object) -> list[dict]:
    """Normalize the ``questions`` arg into a clean ``list[dict]``, tolerating
    models that stringify nested tool arguments.

    Some non-OpenAI models (observed with qwen3.7-max) serialize the whole
    ``questions`` array — or each question object — as a JSON *string* on the
    OpenAI-compatible function-calling path. Strict ``list[dict]`` validation
    then rejects it ("Input should be a valid list") before ``ask_user`` ever
    runs, so the model retries the same malformed call forever and never parks.

    This coercion recovers the intended structure. Beyond valid-JSON strings it
    also salvages MALFORMED ones via ``_recover_question_items`` (``json_repair``)
    — e.g. a whole array crammed into one list element with unescaped quotes and a
    missing opening bracket. Every step degrades rather than raises: an
    unrecoverable payload becomes ``[]`` (ask_user still parks with reason only),
    and a partially-recovered item that yields no real question is dropped — the
    user never sees a raw JSON blob as a question.

    Keeps only items carrying real question text; options-only dicts are dropped
    here (a bare options list with no question text), but recovered separately by
    ``_salvage_options_only`` when ``ask_user`` would otherwise have nothing to show.
    """
    return [q for q in _normalize_to_dicts(value) if str(q.get("question", "")).strip()]


# ② options-only salvage uses a NEUTRAL question title rather than the model's
# ``reason``: the reason is already shown as the clarify card HEADER (stream_event_
# mapper maps interrupt ``reason`` -> ``call_reason``), so repeating it as the body
# question text would duplicate it on screen. The frontend drops a tool_call whose
# question is empty (parseClarifyRequest), so a non-empty placeholder is required for
# the options to render at all.
_SALVAGE_QUESTION_TITLE = "请从以下选项中选择"


def _salvage_options_only(value: object) -> list[dict]:
    """② options-only salvage. When the model passed option lists but forgot the
    question text, ``_coerce_questions`` drops them (no ``question`` key) and the
    card would degrade to a blank free-text box. Instead keep the options under a
    neutral placeholder title (``_SALVAGE_QUESTION_TITLE``) so the card renders the
    clickable options — a renderable card without a wasted retry round-trip. Only
    fires for dicts that have real options but no question text; pure debris (neither
    question nor options) is still dropped.
    """
    salvaged: list[dict] = []
    for q in _normalize_to_dicts(value):
        if str(q.get("question", "")).strip():
            continue  # has text — already kept by _coerce_questions
        options = [str(o) for o in (q.get("options") or []) if str(o).strip()]
        if options:
            salvaged.append(
                {"question": _SALVAGE_QUESTION_TITLE, "options": options, "multiple": bool(q.get("multiple", False))}
            )
    return salvaged


# ① empty-questions self-heal. The model usually HAS the questions in its reasoning
# (observed live: thinking lists 4 questions) but failed to fill the param, so the
# coerced result is empty and the card degrades to a blank free-text box. Return
# this actionable correction as a NORMAL tool result (ToolMessage) so the agent loop
# continues and the model re-calls WITH structure — instead of immediately parking
# on an empty card. Capped at ONE nudge per turn via ``_empty_retry_count`` so a
# model that still cannot structure parks free-text rather than looping: this keeps
# the 2026-06-22 no-infinite-retry guarantee (we never hard-reject + spin forever).
# The marker is a substring of the hint so a later call can detect "already nudged".
_EMPTY_QUESTIONS_RETRY_MARKER = "questions 为空，无法生成结构化澄清卡片"
_EMPTY_QUESTIONS_RETRY_HINT = (
    "你刚才调用 ask_user 时 "
    + _EMPTY_QUESTIONS_RETRY_MARKER
    + "。请立刻只重新调用一次 ask_user，把你要确认的问题作为 JSON 数组传入 questions —— "
    + '每项形如 {"question": "完整问题文本", "options": ["选项1", "选项2", "选项3"], "multiple": false}：'
    "给 1-3 个问题、每个尽量带 2-4 个预设选项供用户点选；只有确实无法预设选项的问题才把该问的 options 留空。"
    "不要把问题写进 reason 文字里，也不要再次提交空 questions。"
)


def _empty_retry_count(state: object) -> int:
    """How many times THIS turn ``ask_user`` already returned the empty-questions
    corrective hint. Caps the self-heal nudge at one (then degrade to a free-text
    park) so a model that cannot produce structured questions never loops. Reads the
    message history injected via ``InjectedState``; tolerant of a missing / None
    state (returns 0 → one nudge allowed) and of both message-object and dict shapes.
    A new user turn (``human`` message) re-arms the nudge.
    """
    messages = None
    if isinstance(state, dict):
        messages = state.get("messages")
    elif state is not None:
        messages = getattr(state, "messages", None)
    if not messages:
        return 0
    count = 0
    for m in messages:
        if isinstance(m, dict):
            role = m.get("type") or m.get("role")
            content = m.get("content")
        else:
            role = getattr(m, "type", None)
            content = getattr(m, "content", None)
        if role in ("human", "user"):
            count = 0  # current-turn boundary: a fresh user turn re-arms the nudge
        elif role == "tool" and isinstance(content, str) and _EMPTY_QUESTIONS_RETRY_MARKER in content:
            count += 1
    return count


@tool
async def ask_user(
    reason: str,
    questions: list[dict] | str | None = None,
    state: Annotated[dict | None, InjectedState] = None,
) -> str:
    """需要用户补充信息、做选择或确认时调用本工具暂停任务并向用户提问；用户回答后任务自动继续。

    只有调用本工具才会真正暂停等待用户输入——不要直接用普通文字提问后就结束任务。

    Args:
        reason: 总体说明，使用与用户输入一致的语言（例如“为了制定计划，请先确认以下问题”）。
        questions: 结构化问题数组（务必作为 JSON 数组传入，不要序列化成字符串），每项形如
            {"question": "问题标题", "options": ["选项1", "选项2"], "multiple": false}。
            options 为空表示开放式自由输入；multiple=true 表示多选。仅当确实没有任何
            结构化问题、只需给一句总体说明时，才省略 questions。

    Returns:
        用户的回答文本。
    """
    coerced = _coerce_questions(questions)
    if not coerced:
        # ② options provided but the question text was dropped → keep the options.
        coerced = _salvage_options_only(questions)
    if not coerced:
        # ① nudge the model once to resubmit structured questions; on the second
        # empty call this turn, fall through and park free-text (reason-only card).
        if _empty_retry_count(state) == 0:
            return _EMPTY_QUESTIONS_RETRY_HINT
    tool_calls = [
        {
            "id": f"q_{i}",
            "name": "clarify",
            "args": {
                # Both coerced and salvaged items already carry non-empty text; the
                # placeholder is a last-resort guard so a tool_call is never dropped
                # by the frontend for an empty question (it would NOT duplicate the
                # reason header — that is exactly why _SALVAGE_QUESTION_TITLE is used).
                "question": str(q.get("question", "")).strip() or _SALVAGE_QUESTION_TITLE,
                "options": [str(o) for o in (q.get("options") or [])],
                "multiple": bool(q.get("multiple", False)),
            },
        }
        for i, q in enumerate(coerced)
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
    skills_present: bool = False,
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

    # F035 Track D — skills (RE-ENABLED 2026-06-24, Fork X). The run's allowed skill
    # bundles were copied into the workspace /skills/ subtree before this call (see
    # task_exec._create_agent → materialize_session_skills); ``skills_present`` says
    # at least one landed. Attach deepagents' SkillsMiddleware for progressive
    # disclosure. It ENUMERATES /skills/ via its OWN FilesystemBackend over the local
    # write-through cache — FilesystemBackend.ls is non-recursive + dir-aware, whereas
    # the MinIO-backed WorkspaceBackend.ls returns only file entries, so the native
    # ``skills=`` param (which would reuse the workspace backend) discovers nothing.
    # SkillsMiddleware registers NO file tools, so this second backend does NOT shadow
    # the workspace read_file/write_file (the 2026-06-16 disable concern does not hold
    # in deepagents 0.6.8); the model reads the same /skills/<name>/SKILL.md paths back
    # through the WorkspaceBackend. The copy is the whitelist gate — no per-run
    # active_skills config is threaded.
    if skills_present and file_dir:
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.middleware.skills import SkillsMiddleware

        from bisheng.linsight.domain.services.skill_provisioning import WORKSPACE_SKILLS_DIR

        middlewares.append(
            SkillsMiddleware(
                backend=FilesystemBackend(root_dir=file_dir, virtual_mode=True),
                sources=[(f"/{WORKSPACE_SKILLS_DIR}/", "Skills")],
            )
        )

    # Language directive LAST in the stack so it appends AFTER every framework
    # middleware prompt (write_todos / filesystem / task / skills) — the absolute
    # tail of the system message, the strongest position to keep the model
    # reasoning (thinking) in the user's language. See _LanguageTailMiddleware.
    middlewares.append(_LanguageTailMiddleware(_LINSIGHT_LANGUAGE_DIRECTIVE_ZH))

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
    researcher["middleware"] = [
        build_resilience_middleware(linsight_conf, is_subagent=True),
        # Same tail language directive on the subagent's own stack (last -> after
        # its TodoList/Filesystem framework prompts), so the researcher also
        # reasons in the user's language.
        _LanguageTailMiddleware(_LINSIGHT_LANGUAGE_DIRECTIVE_ZH),
    ]
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
