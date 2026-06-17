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

# Chinese system prompt for the Linsight task-mode agent (design §2.4). Kept
# inline so it stays co-located with the factory. No call_reason schema is
# injected — step titles come from deepagents' native tool output (the frontend
# renders the tool name); only the HITL interrupt reason is model-authored.
LINSIGHT_SYSTEM_PROMPT_ZH = """你是毕昇灵思任务智能体，负责把用户的复杂任务拆解为可执行的待办清单并逐项完成。

工作约定：
- 使用 write_todos 维护任务清单；更新待办时只翻转 status（pending/in_progress/completed），不要改写已有文案，以保证任务标识稳定。
- 同一时刻只有一个待办处于 in_progress。
- 当任务依赖只有用户才知道的信息（个人情况、偏好、目标、约束、口味、预算、时间安排、选择等）且这些信息缺失或不明确时，必须先调用 ask_user 工具向用户收集，再开始 write_todos 规划与执行；不要凭空假设或编造，也不要只用普通文字提问后就结束任务。
- 【关键】ask_user 必须由你本人（主智能体）在主流程中**直接调用**，严禁通过 task 工具/子代理来调用 ask_user。所有需要向用户澄清的问题，必须在创建任何子任务（task）之前，一次性用 ask_user 问完；子代理（task）内部不得调用 ask_user。
- 调用 ask_user 时，reason 用中文说明原因，questions 给出结构化的问题与可选项（单选/多选/开放输入）。
- 交付物请写入工作区 output/ 目录；中间产物写入 scratch/。

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

    # F035: turn OFF subagent delegation (the deepagents `task` tool) at the
    # profile level — the only reliable way (see _disable_subagent_delegation).
    _disable_subagent_delegation(model)

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
    middlewares: list = []

    # F035 HITL fix (2026-06-16): strip the deepagents `task` tool (subagent
    # delegation). The model was over-delegating (100+ subagents per run) and
    # calling ask_user INSIDE subagents, where the HITL interrupt never bubbled up
    # to park the task — so clarification never reached the user and the task ran
    # to a direct-answer fallback. Removing `task` forces all work (incl. ask_user)
    # into the main graph, where interrupt() parks correctly. _ToolExclusionMiddleware
    # is added AFTER SubAgentMiddleware so it strips the injected `task` tool before
    # the model sees it.
    try:
        from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

        middlewares.append(_ToolExclusionMiddleware(excluded=frozenset({"task"})))
    except Exception as e:
        from loguru import logger

        logger.warning(f"could not exclude `task` subagent tool: {e}")

    # No custom history-compression middleware: deepagents already ships a
    # built-in summarization middleware (deepagents.middleware.summarization),
    # so injecting our own duplicated it and tripped langchain's "duplicate
    # middleware instances" assertion. The legacy 2.0 ``tool_buffer`` compression
    # (design §3.8) is therefore retired in favor of the deepagents built-in.
    # ask_user (HITL): a tool that calls langgraph ``interrupt()`` so the agent
    # can park-and-release for user input (F035 §4.6); deepagents ships no
    # built-in ask-human tool, so we inject our own.
    return create_deep_agent(
        model=model,
        tools=[*tools, ask_user],
        system_prompt=LINSIGHT_SYSTEM_PROMPT_ZH,
        middleware=middlewares,
        backend=backend,
        checkpointer=checkpointer,
        store=None,
    )


def _disable_subagent_delegation(model: BaseChatModel) -> None:
    """Disable deepagents' auto-added general-purpose subagent (the ``task``
    tool) for this model via the official harness-profile API.

    Why: the model over-delegated (spawning ``ls`` / ``glob`` "subagents" that
    called 0 tools) and could call ``ask_user`` INSIDE a subagent, where the
    HITL ``interrupt()`` never bubbles up to park the task. The earlier approach
    — a user-supplied ``_ToolExclusionMiddleware({"task"})`` — does not reliably
    strip ``task`` because user middleware is ordered before ``SubAgentMiddleware``
    in the assembled stack, so the injected ``task`` tool reappears before the
    model. Disabling the general-purpose subagent at the profile level stops
    ``task`` from being added at all (graph.py: ``gp_profile.enabled is False``
    → no ``task`` tool). Registration is additive/idempotent and scoped to this
    model's provider; deriving no provider key is a safe no-op.
    """
    try:
        from deepagents._models import get_model_identifier, get_model_provider
        from deepagents.profiles import (
            GeneralPurposeSubagentProfile,
            HarnessProfile,
            register_harness_profile,
        )

        disabled = HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False))
        provider = get_model_provider(model)
        identifier = get_model_identifier(model)
        keys: set[str] = set()
        if provider:
            keys.add(provider)
            if identifier and ":" not in identifier:
                keys.add(f"{provider}:{identifier}")
        if identifier and ":" in identifier:
            keys.add(identifier)
        for key in keys:
            register_harness_profile(key, disabled)
        if not keys:
            from loguru import logger

            logger.warning("disable_subagent_delegation: no harness-profile key derivable; `task` tool may remain")
    except Exception as e:
        from loguru import logger

        logger.warning(f"could not disable subagent delegation via harness profile: {e}")


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
