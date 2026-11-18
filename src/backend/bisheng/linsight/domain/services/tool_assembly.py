"""One place that turns a request's tool selection into LangChain tools (F004 T022).

Three entry points share the helpers in this module:

- ``assemble_daily_tools`` is the body of ``chat_service._prepare_tools``.
- ``assemble_planned_tools`` is the body of
  ``LinsightWorkbenchImpl.init_linsight_config_tools``.
- ``assemble_tools`` is the unified function both runtime profiles (``direct``,
  ``planned``) call. It binds every tool either legacy entry point can bind.

The two legacy entry points keep their return values and their error behaviour,
so the legacy path is unchanged while the unified runtime flag is off.

The builders that live in ``chat_service`` and ``workbench_impl`` are resolved
through those modules at call time. Both modules are imported lazily: they are
large, and ``chat_service`` imports this package.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.image_view.loop import IMAGE_VIEW_TOOL_KEY
from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor

CODE_INTERPRETER_TOOL_KEY = "bisheng_code_interpreter"
WEB_SEARCH_TOOL_KEY = "web_search"
KNOWLEDGE_SEARCH_TOOL_NAME = "search_knowledge_bases"
_DEFAULT_KB_MAX_TOKEN = 15000


def _chat_service():
    from bisheng.workstation.domain.services import chat_service

    return chat_service


def _workbench():
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    return LinsightWorkbenchImpl


@dataclass
class ToolAssemblyRequest:
    """What one run asks for. The same request serves both profiles.

    ``tool_payloads`` is the daily selection shape (``{id, tool_key, type}``);
    ``tool_tree`` is the deep-research shape (``{children: [{id}]}``). Either or
    both may be given; a tool id selected twice is bound once.

    ``file_dir`` set means the run has a workspace: the code interpreter is then
    bound to it (the deep-research behaviour) whether or not the user selected it.

    ``citation_collector`` set means selected web tools get the daily citation
    wrapper. A caller whose agent factory wraps web tools itself leaves it None.
    """

    user_id: int
    login_user: Any = None
    tool_payloads: list = field(default_factory=list)
    tool_tree: list = field(default_factory=list)
    knowledge_bases_info: list[dict] | None = None
    kb_max_token: int = _DEFAULT_KB_MAX_TOKEN
    citation_collector: Any = None
    image_registry: Any = None
    citation_scope: Any = None
    kb_image_stage: Any = None
    file_dir: str | None = None
    session_version_id: str | None = None
    app_type: ApplicationTypeEnum = ApplicationTypeEnum.DAILY_CHAT


@dataclass
class ToolAssembly:
    """Bound tools plus the tools that could not be initialised."""

    tools: list[BaseTool] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    def failure_events(self) -> list[dict]:
        """One finished ``tool_call`` event per failure, so the user sees it (design §4.3)."""
        events = []
        for failure in self.failures:
            now_ms = int(time.time() * 1000)
            events.append(
                {
                    "type": "tool_call",
                    "data": {
                        "tool_call_id": f"init_fail_{uuid4().hex[:10]}",
                        "tool_name": failure["tool_key"],
                        "display_name": failure["display_name"],
                        "tool_type": failure["tool_type"],
                        "args": {},
                        "results": [],
                        "error": failure["error"],
                        **({"failure_info": failure["failure_info"]} if failure.get("failure_info") else {}),
                        "started_at": now_ms,
                        "ended_at": now_ms,
                        "duration_ms": 0,
                    },
                }
            )
        return events


@dataclass
class _Selected:
    tool_id: Any
    tool_key: str | None


def _payload_field(payload: Any, name: str) -> Any:
    return payload.get(name) if isinstance(payload, dict) else getattr(payload, name, None)


def _selected_from_payloads(tool_payloads: list | None) -> list[_Selected]:
    """Flat daily payloads -> selections. Knowledge rows and the retired image_view row are dropped."""
    selected = []
    for payload in tool_payloads or []:
        if (_payload_field(payload, "type") or "tool") != "tool":
            continue
        tool_key = _payload_field(payload, "tool_key")
        # Retired builtin row. Saved selections may still name it; loading it
        # as a LangChain tool fails.
        if tool_key == IMAGE_VIEW_TOOL_KEY:
            continue
        selected.append(_Selected(tool_id=_payload_field(payload, "id"), tool_key=tool_key))
    return selected


def _failure_entry(tool_key: str | None, tool_id: Any, err: str, tool_type: str | None = None) -> dict:
    """The failure shape the daily SSE loop already renders as a failed tool call."""
    cs = _chat_service()
    info = FailureContextAdapter.from_payload(err)
    return {
        "tool_key": tool_key or str(tool_id or ""),
        "tool_type": tool_type or ("web" if tool_key in cs._WEB_SEARCH_TOOL_NAMES else "tool"),
        # display_name is resolved on the frontend via i18n — just
        # advertise the raw tool_key so the client can map it.
        "display_name": tool_key or "",
        "error": "Tool initialization failed." if info else err,
        **({"failure_info": info} if info else {}),
    }


async def _init_selected(
    selected: _Selected, user_id: int, app_type: ApplicationTypeEnum
) -> tuple[BaseTool | None, str | None]:
    """Initialise one selected tool. Returns (tool, error); never raises."""
    cs = _chat_service()
    tool_id, tool_key = selected.tool_id, selected.tool_key
    # The daily web-search builder reports usage as daily chat and resolves the
    # tool row when the payload carries no id.
    if tool_key == WEB_SEARCH_TOOL_KEY and (app_type == ApplicationTypeEnum.DAILY_CHAT or not tool_id):
        return await cs._build_web_search_tool(user_id, int(tool_id) if tool_id else None)
    if not tool_id:
        return None, None
    try:
        tool = await ToolExecutor.init_by_tool_id(
            tool_id=int(tool_id),
            app_id=app_type.value,
            app_name=app_type.value,
            app_type=app_type,
            user_id=user_id,
        )
    except Exception as exc:
        err = cs._handle_agent_tool_error(exc)
        logger.warning("Failed to initialise tool id={} key={}: {}", tool_id, tool_key, err)
        return None, err
    return tool, None


def _finish_selected(
    tool: BaseTool,
    tool_key: str | None,
    *,
    citation_collector: Any,
    image_registry: Any,
    citation_scope: Any,
    kb_image_stage: Any,
    collect_deliverables: bool = True,
) -> BaseTool:
    """Attach the request-scoped pieces: knowledge-image stage, deliverables, citation and image wrapper."""
    cs = _chat_service()
    if kb_image_stage is not None:
        cs._attach_kb_image_stage(tool, kb_image_stage)
    if collect_deliverables and tool_key == CODE_INTERPRETER_TOOL_KEY:
        cs._enable_deliverable_collection(tool)
    if citation_collector is None:
        return tool
    return cs._wrap_daily_chat_citation_tool(
        tool,
        citation_collector,
        image_registry=image_registry,
        citation_scope=citation_scope,
        kb_image_stage=kb_image_stage,
    )


async def assemble_daily_tools(
    tool_payloads: list | None,
    login_user: Any,
    ws_config: Any,
    citation_collector: Any,
    knowledge_bases_info: list[dict] | None = None,
    image_registry: Any = None,
    citation_scope: Any = None,
    kb_image_stage: Any = None,
) -> tuple[list[BaseTool], list[dict]]:
    """Daily chat: selected tools in the order selected, then the knowledge tool.

    The selected tools and the knowledge tool do not depend on each other, so
    they initialise concurrently. A selected tool that fails becomes a failure
    entry. A knowledge tool that fails to build raises, as it always has.
    """
    cs = _chat_service()
    selected = _selected_from_payloads(tool_payloads)

    async def _knowledge_tool():
        if not knowledge_bases_info:
            return None
        return await cs._build_knowledge_search_tool(
            knowledge_bases_info=knowledge_bases_info,
            login_user=login_user,
            max_token=getattr(ws_config, "maxTokens", _DEFAULT_KB_MAX_TOKEN) or _DEFAULT_KB_MAX_TOKEN,
            citation_collector=citation_collector,
            image_registry=image_registry,
            citation_scope=citation_scope,
            kb_image_stage=kb_image_stage,
        )

    # No return_exceptions: _init_selected reports its own errors, and a
    # knowledge-tool error is meant to reach the caller.
    *initialised, kb_tool = await asyncio.gather(
        *(_init_selected(s, login_user.user_id, ApplicationTypeEnum.DAILY_CHAT) for s in selected),
        _knowledge_tool(),
    )

    tools: list[BaseTool] = []
    # Failures surfaced to caller so the agent can emit synthetic tool_call
    # events and let the user see why a tool they selected didn't run.
    failures: list[dict] = []
    for item, (tool, err) in zip(selected, initialised, strict=True):
        if tool is not None:
            tools.append(
                _finish_selected(
                    tool,
                    item.tool_key,
                    citation_collector=citation_collector,
                    image_registry=image_registry,
                    citation_scope=citation_scope,
                    kb_image_stage=kb_image_stage,
                )
            )
        elif err:
            failures.append(_failure_entry(item.tool_key, item.tool_id, err))
    if kb_tool is not None:
        tools.append(kb_tool)
    return tools, failures


async def assemble_planned_tools(session_version: Any, need_upload: bool = False, file_dir: str | None = None) -> list:
    """Deep research: the workspace-bound code interpreter, then every selected tool.

    The steps run one after another on purpose. ``_init_bisheng_code_tool``
    removes the interpreter id from the selection, and the batch initialisation
    reads the selection after that. Every failure raises: the legacy task must
    not start with a capability missing.
    """
    workbench = _workbench()
    tools = []

    tool_ids = list(dict.fromkeys(workbench._extract_tool_ids(session_version.tools or [])))

    # Task infrastructure is resolved on each execution/resume, independently
    # of the optional tools selected in the composer. Initialization failures
    # propagate before the model starts so capability loss is actionable.
    if need_upload and file_dir:
        tools.extend(
            await workbench._init_bisheng_code_tool(
                tool_ids, file_dir, user_id=session_version.user_id, session_version_id=session_version.id
            )
        )

    # Retired builtin row. Saved task selections may still name it.
    # Passing the row to load_tools raises "Got unknown tool image_view"
    # and aborts the task before skills or any other tool run.
    image_view_tool = await GptsToolsDao.aget_tool_by_tool_key(tool_key=IMAGE_VIEW_TOOL_KEY)
    if image_view_tool and image_view_tool.id in tool_ids:
        tool_ids.remove(image_view_tool.id)
        logger.info("skip image_view tool id={}: config row is not a callable tool", image_view_tool.id)

    # Unified-resource direction (2026-06-16): task mode reuses the daily
    # tool selection directly. Every selected tool id (a real GptsTools id
    # the user already has access to) binds. The code interpreter is already
    # consumed above when selected, so it is never built twice.
    if tool_ids:
        tools.extend(
            await ToolExecutor.init_by_tool_ids(
                tool_ids,
                app_id=ApplicationTypeEnum.LINSIGHT.value,
                app_name=ApplicationTypeEnum.LINSIGHT.value,
                app_type=ApplicationTypeEnum.LINSIGHT,
                user_id=session_version.user_id,
            )
        )

    return tools


async def _row_id_by_key(tool_key: str) -> int | None:
    row = await GptsToolsDao.aget_tool_by_tool_key(tool_key=tool_key)
    return row.id if row else None


async def _unified_selection(request: ToolAssemblyRequest) -> tuple[list[_Selected], list[int]]:
    """Merge both selection shapes. Returns (tools to initialise one by one, interpreter ids selected).

    With a workspace the code interpreter is taken out of the list: it is bound
    to the workspace separately, so it is never built twice.
    """
    selected = _selected_from_payloads(request.tool_payloads)
    tree_ids = _workbench()._extract_tool_ids(request.tool_tree or [])
    selected.extend(_Selected(tool_id=tool_id, tool_key=None) for tool_id in tree_ids)

    has_workspace = bool(request.file_dir)
    code_id = image_view_id = None
    # Tree ids carry no tool_key, so the two special rows are found by id. A
    # request made of flat payloads skips both lookups.
    if tree_ids:
        image_view_id, code_id = await asyncio.gather(
            _row_id_by_key(IMAGE_VIEW_TOOL_KEY),
            _row_id_by_key(CODE_INTERPRETER_TOOL_KEY) if has_workspace else asyncio.sleep(0),
        )

    kept: list[_Selected] = []
    code_ids: list[int] = []
    seen: set[int] = set()
    for item in selected:
        tool_id = int(item.tool_id) if item.tool_id else None
        if tool_id is not None:
            if tool_id in seen:
                continue
            seen.add(tool_id)
            if tool_id == image_view_id:
                logger.info("skip image_view tool id={}: config row is not a callable tool", tool_id)
                continue
        is_code = item.tool_key == CODE_INTERPRETER_TOOL_KEY or (tool_id is not None and tool_id == code_id)
        if has_workspace and is_code:
            if tool_id is not None:
                code_ids.append(tool_id)
            continue
        kept.append(item)
    return kept, code_ids


async def assemble_tools(request: ToolAssemblyRequest) -> ToolAssembly:
    """Unified assembly for the ``direct`` and the ``planned`` profile.

    Binds the selected tools, web search, the knowledge tool for the selected
    bases, and, when the run has a workspace, the workspace-bound code
    interpreter. Every initialisation runs concurrently and on its own: a tool
    that fails is left out and reported in ``failures``; the others still bind.

    Tool order: workspace code interpreter, selected tools in the order
    selected, knowledge tool.
    """
    cs = _chat_service()
    selected, code_ids = await _unified_selection(request)
    wrap = {
        "citation_collector": request.citation_collector,
        "image_registry": request.image_registry,
        "citation_scope": request.citation_scope,
        "kb_image_stage": request.kb_image_stage,
    }

    async def _one(item: _Selected) -> tuple[list[BaseTool], list[dict]]:
        try:
            tool, err = await _init_selected(item, request.user_id, request.app_type)
            if tool is not None:
                return [_finish_selected(tool, item.tool_key, **wrap)], []
        except Exception as exc:
            logger.opt(exception=True).warning("Failed to assemble tool id={} key={}", item.tool_id, item.tool_key)
            err = cs._handle_agent_tool_error(exc)
        return [], [_failure_entry(item.tool_key, item.tool_id, err)] if err else []

    async def _workspace_code_tool() -> tuple[list[BaseTool], list[dict]]:
        if not request.file_dir:
            return [], []
        try:
            # code_ids non-empty means the user selected the interpreter: a
            # permission denial is then an error instead of a silent skip.
            tools = await _workbench()._init_bisheng_code_tool(
                list(code_ids),
                request.file_dir,
                user_id=request.user_id,
                session_version_id=request.session_version_id,
            )
            # The workspace is where this interpreter's files go; the per-turn
            # deliverable collection of daily chat does not apply.
            return [
                _finish_selected(t, CODE_INTERPRETER_TOOL_KEY, collect_deliverables=False, **wrap) for t in tools
            ], []
        except Exception as exc:
            logger.opt(exception=True).warning("Failed to bind the workspace code interpreter")
            err = cs._handle_agent_tool_error(exc)
            return [], [_failure_entry(CODE_INTERPRETER_TOOL_KEY, None, err)]

    async def _knowledge_tool() -> tuple[list[BaseTool], list[dict]]:
        if not request.knowledge_bases_info:
            return [], []
        try:
            collector = request.citation_collector
            if collector is None:
                from bisheng.citation.domain.services.citation_prompt_helper import CitationRegistryCollector

                collector = CitationRegistryCollector()
            tool = await cs._build_knowledge_search_tool(
                knowledge_bases_info=request.knowledge_bases_info,
                # Permission scope travels in the tool's closure: the selected
                # bases are the whitelist, and retrieval checks this user.
                login_user=request.login_user,
                max_token=request.kb_max_token or _DEFAULT_KB_MAX_TOKEN,
                citation_collector=collector,
                image_registry=request.image_registry,
                citation_scope=request.citation_scope,
                kb_image_stage=request.kb_image_stage,
            )
            return ([tool] if tool is not None else []), []
        except Exception as exc:
            logger.opt(exception=True).warning("Failed to build the knowledge search tool")
            err = cs._handle_agent_tool_error(exc)
            return [], [_failure_entry(KNOWLEDGE_SEARCH_TOOL_NAME, None, err, tool_type="knowledge")]

    # Each coroutine catches its own errors, so gather needs no return_exceptions.
    parts = await asyncio.gather(_workspace_code_tool(), *(_one(item) for item in selected), _knowledge_tool())
    assembly = ToolAssembly()
    for tools, failures in parts:
        assembly.tools.extend(tools)
        assembly.failures.extend(failures)
    return assembly


class _DeferredWorkspaceExecutor:
    """A code executor whose workspace is prepared right before its first run (F004 决策 10).

    Every attribute other than ``run`` / ``arun`` is the wrapped executor's, so
    code that reads or sets ``workspace_prefix``, ``local_sync_path`` or calls
    ``close`` keeps working. Deep agents shallow-copy tools and share the
    executor, so the preparation is attached here and not to the tool object.
    """

    def __init__(self, inner: Any, prepare: Any):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_prepare", prepare)

    def __getattr__(self, name: str) -> Any:
        # Only reached for names this object does not have. Dunder lookups on a
        # half-built copy must fail here instead of recursing through ``_inner``.
        if name in ("_inner", "_prepare") or (name.startswith("__") and name.endswith("__")):
            raise AttributeError(name)
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)

    async def arun(self, code: str) -> Any:
        await self._prepare()
        inner_arun = getattr(self._inner, "arun", None)
        if inner_arun is None:
            return await asyncio.to_thread(self._inner.run, code)
        return await inner_arun(code)

    def run(self, code: str) -> Any:
        # The unified runtime drives tools with ``ainvoke``, which reaches ``arun``.
        # A synchronous call cannot await the preparation: refuse it loudly, because
        # running without the workspace would write the files to a temporary directory.
        raise RuntimeError("the workspace-bound code interpreter of a direct run must be called asynchronously")


def _executor_owner(tool: BaseTool) -> BaseTool:
    """The tool object that really holds ``executor``.

    A platform tool reaches the model as ``ToolExecutor(tool_instance=<interpreter>)``.
    ``ToolExecutor.__getattr__`` forwards reads to the inner tool, so ``tool.executor``
    reads fine, but assigning it on the pydantic wrapper raises "object has no field".
    Walk down ``tool_instance`` to the object that declares the attribute.
    """
    owner = tool
    for _ in range(8):
        if "executor" in getattr(type(owner), "model_fields", {}) or "executor" in getattr(owner, "__dict__", {}):
            return owner
        inner = getattr(owner, "__dict__", {}).get("tool_instance")
        if not isinstance(inner, BaseTool):
            break
        owner = inner
    raise TypeError(f"cannot find the object holding the executor of tool {getattr(tool, 'name', tool)!r}")


def defer_workspace_preparation(tools: list[BaseTool], prepare: Any) -> int:
    """Run ``await prepare()`` before the first execution of each code interpreter in ``tools``.

    ``prepare`` must be idempotent: it is awaited before every execution. A run
    that never executes code never calls it, so nothing local is created and the
    workspace is not read (AC-34). Returns how many tools were wrapped.
    """
    wrapped = 0
    for tool in tools:
        executor = getattr(tool, "executor", None)
        if getattr(tool, "name", None) != CODE_INTERPRETER_TOOL_KEY or executor is None:
            continue
        if isinstance(executor, _DeferredWorkspaceExecutor):
            continue
        _executor_owner(tool).executor = _DeferredWorkspaceExecutor(executor, prepare)
        wrapped += 1
    return wrapped
