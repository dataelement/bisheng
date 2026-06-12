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
from langchain_core.tools import BaseTool

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
- 需要用户补充信息时，触发 HITL 中断，并在 reason 中用中文清晰说明需要用户确认或提供什么。
- 交付物请写入工作区 output/ 目录；中间产物写入 scratch/。

请使用简体中文与用户和工具交互。"""


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

    # No custom history-compression middleware: deepagents already ships a
    # built-in summarization middleware (deepagents.middleware.summarization),
    # so injecting our own duplicated it and tripped langchain's "duplicate
    # middleware instances" assertion. The legacy 2.0 ``tool_buffer`` compression
    # (design §3.8) is therefore retired in favor of the deepagents built-in.
    return create_deep_agent(
        model=model,
        tools=list(tools),
        system_prompt=LINSIGHT_SYSTEM_PROMPT_ZH,
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
        # C4 (Track E) introduces ``linsight_default_model_id``; until it lands
        # we fall back to the existing task_model.id. TODO(F035 C4): switch to
        # workbench_conf.linsight_default_model_id once Track E merges.
        resolved_id = getattr(workbench_conf, "linsight_default_model_id", None)
        if resolved_id is None:
            resolved_id = workbench_conf.task_model.id

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
