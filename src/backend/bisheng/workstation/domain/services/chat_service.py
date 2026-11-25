from __future__ import annotations

import json
import mimetypes
import time
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import StreamingResponse
from json_repair import json_repair
from langchain_core.tools import ArgsSchema, BaseTool, StructuredTool
from loguru import logger
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field as PydanticField
from pydantic import SkipValidation
from pydantic import field_validator as PydanticFieldValidator

from bisheng.api.services import knowledge_imp
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.schemas.user_message import serialize_user_question
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.citation.domain.services.citation_handle_service import drop_web_citation_keys
from bisheng.citation.domain.services.citation_prompt_helper import (
    CitationRegistryCollector,
    FetchedPageCitationRegistry,
    annotate_fetched_page_with_citation,
    annotate_rag_documents_with_citations,
    annotate_web_results_with_citations,
    cache_citation_registry_items,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
    collect_web_citation_registry_items,
    exclude_known_registry_items,
    is_web_citation_tool,
    is_web_fetch_tool,
    save_message_citations,  # noqa: F401  (re-exported for run_projector_direct)
)
from bisheng.citation.domain.services.daily_citation_scope import DailyCitationScope
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.workstation import (
    ConversationNotFoundError,
    DepartmentDailyChatConcurrentLimitError,
)
from bisheng.common.image_view import (
    ImageRegistry,
    annotate,
)
from bisheng.common.schemas.telemetry.event_data_schema import (
    ApplicationAliveEventData,
    ApplicationProcessEventData,
    NewMessageSessionEventData,
)
from bisheng.common.services import telemetry_service
from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.chat_attachment import promote_chat_attachments
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.llm.domain import LLMService
from bisheng.memory.domain.services.activity import MemoryActivity
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.workstation.domain.schemas.chat import APIChatCompletion
from bisheng.workstation.domain.services.kb_image_stage import KbImageStage

from .content_safety import (  # noqa: F401  (blocked_answer_* re-exported for run_projector_direct)
    blocked_answer_extra,
    blocked_answer_payload,
    build_blocked_answer_row,
    iter_blocked_sse,
    mark_session_content_violation,
    workbench_tenant_id,
)
from .daily_citation import (
    handles_for_chunks,
    handles_for_web_results,
    select_cited_items,  # noqa: F401  (re-exported for run_projector_direct)
    strip_ids_for_sync_path,
)
from .daily_memory import (
    MemoryRegister,
    register_session,
)
from .workstation_service import WorkStationService

# --------------------------------------------------------------------------- #
# v2.5 Agent Mode Helper Functions
#
# Building blocks of daily-chat tools; the direct run of the unified runtime
# assembles its tools from them (F004):
#   - _parse_tool_results: Normalizes BaseTool output to facilitate SSE (Server-Sent Events) and database storage.
#   - _build_tool_meta: Extracts tool display_name and tool_type for frontend display.
#   - _build_web_search_tool: Directly reuses the BaseTool from ToolExecutor.init_by_tool_id.
#   - _build_knowledge_search_tool: Wraps queryChunksFromDB using StructuredTool.
#   - _resolve_user_kb_selection: Resolves UseKnowledgeBaseParam into a list of KB metadata.
#   - _prepare_tools: Entry point function; integrates tool_payloads + knowledge_bases_info -> List[BaseTool].
# --------------------------------------------------------------------------- #


class DailyChatCitationToolWrapper(BaseTool):
    """Add citation prompt context for daily chat tool invocations."""

    name: str
    description: str
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = PydanticField(default=None)
    tool: BaseTool
    citation_collector: CitationRegistryCollector = PydanticField(exclude=True)
    kb_name_by_id: dict[str, str] = PydanticField(default_factory=dict, exclude=True)
    image_registry: Any = PydanticField(default=None, exclude=True)
    # Request-scoped stage that exposes retrieved knowledge images to the code interpreter
    kb_image_stage: Any = PydanticField(default=None, exclude=True)
    # F075: session handle table mirror; results show [Sn] handles, not registry keys
    citation_scope: Any = PydanticField(default=None, exclude=True)
    fetched_pages: FetchedPageCitationRegistry = PydanticField(
        default_factory=FetchedPageCitationRegistry, exclude=True
    )

    @classmethod
    def wrap(
        cls,
        tool: BaseTool,
        citation_collector: CitationRegistryCollector,
        image_registry: ImageRegistry | None = None,
        citation_scope: DailyCitationScope | None = None,
        kb_image_stage: KbImageStage | None = None,
    ) -> BaseTool:
        return cls(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            tool=tool,
            citation_collector=citation_collector,
            image_registry=image_registry,
            citation_scope=citation_scope,
            kb_image_stage=kb_image_stage,
        )

    def _is_web_search_tool(self) -> bool:
        return is_web_citation_tool(self.tool) and not is_web_fetch_tool(self.tool)

    def _has_knowledge_rag_tool(self) -> bool:
        return hasattr(self.tool, "knowledge_retriever_tool")

    def _append_fetch_citation(self, output: Any) -> Any:
        output, items = annotate_fetched_page_with_citation(output, self.fetched_pages)
        self._extend_citation_registry_items(exclude_known_registry_items(self.citation_collector.list_items(), items))
        # Sync calls cannot await the handle allocator: show no source id.
        return drop_web_citation_keys(output) if self.citation_scope is not None else output

    async def _aappend_fetch_citation(self, output: Any) -> Any:
        output, items = annotate_fetched_page_with_citation(output, self.fetched_pages)
        await self._aextend_citation_registry_items(
            exclude_known_registry_items(self.citation_collector.list_items(), items)
        )
        return await handles_for_web_results(self.citation_scope, items, output)

    def _append_web_citation(self, output: Any) -> Any:
        if not isinstance(output, str):
            return output
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        if not isinstance(results, list):
            return output
        results = annotate_web_results_with_citations(results)
        self._extend_citation_registry_items(collect_web_citation_registry_items(results))
        dumped = json.dumps(results, ensure_ascii=False)
        # Sync calls cannot await the handle allocator: show no source id.
        return drop_web_citation_keys(dumped) if self.citation_scope is not None else dumped

    async def _aappend_web_citation(self, output: Any) -> Any:
        if not isinstance(output, str):
            return output
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        if not isinstance(results, list):
            return output
        results = annotate_web_results_with_citations(results)
        items = collect_web_citation_registry_items(results)
        await self._aextend_citation_registry_items(items)
        return await handles_for_web_results(self.citation_scope, items, json.dumps(results, ensure_ascii=False))

    def _format_knowledge_results(self, retrieval_result: Any) -> str:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        self._extend_citation_registry_items(collect_rag_citation_registry_items(source_documents))
        chunks = strip_ids_for_sync_path(self.citation_scope, self._format_knowledge_chunks(source_documents))
        return self._dump_knowledge_chunks(chunks)

    async def _aformat_knowledge_results(self, retrieval_result: Any) -> str:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        items = collect_rag_citation_registry_items(source_documents)
        await self._aextend_citation_registry_items(items)
        chunks = await handles_for_chunks(self.citation_scope, items, self._format_knowledge_chunks(source_documents))
        return self._dump_knowledge_chunks(chunks)

    def _format_knowledge_chunks(self, source_documents: list) -> list[str]:
        chunks = []
        for doc in source_documents:
            meta = getattr(doc, "metadata", {}) or {}
            kb_id_raw = meta.get("knowledge_id") or meta.get("kb_id") or ""
            kb_id = str(kb_id_raw) if kb_id_raw not in (None, "") else ""
            kb_name = self.kb_name_by_id.get(kb_id, "")
            chunks.append(knowledge_imp.KnowledgeUtils.format_retrieved_chunk(doc, kb_name))
        return chunks

    def _dump_knowledge_chunks(self, chunks: list[str]) -> str:
        results = [_annotate_retrieved_chunk(chunk, self.image_registry, self.kb_image_stage) for chunk in chunks]
        return json.dumps(results, ensure_ascii=False)

    def _extend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        cache_citation_registry_items_sync(items)
        self.citation_collector.extend(items)

    async def _aextend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        await cache_citation_registry_items(items)
        self.citation_collector.extend(items)

    def _run(self, query: str = "", config=None, **kwargs: Any) -> Any:
        if is_web_fetch_tool(self.tool):
            return self._append_fetch_citation(self.tool.invoke({"url": kwargs.get("url", "")}, config=config))
        if self._is_web_search_tool():
            return self._append_web_citation(self.tool.invoke({"query": query}, config=config))
        if not self._has_knowledge_rag_tool():
            return self.tool.invoke({"query": query}, config=config)

        # Called directly rather than through `invoke`: the retriever is this
        # wrapper's internal step, and opening a run for it adds a stray tool
        # entry named after the retriever instead of the knowledge base.
        retrieval_result = self.tool.knowledge_retriever_tool._run(query)
        return self._format_knowledge_results(retrieval_result)

    async def _arun(self, query: str = "", config=None, **kwargs: Any) -> Any:
        if is_web_fetch_tool(self.tool):
            return await self._aappend_fetch_citation(
                await self.tool.ainvoke({"url": kwargs.get("url", "")}, config=config)
            )
        if self._is_web_search_tool():
            return await self._aappend_web_citation(await self.tool.ainvoke({"query": query}, config=config))
        if not self._has_knowledge_rag_tool():
            return await self.tool.ainvoke({"query": query}, config=config)

        retrieval_result = await self.tool.knowledge_retriever_tool._arun(query)
        return await self._aformat_knowledge_results(retrieval_result)


CODE_INTERPRETER_TOOL_KEY = "bisheng_code_interpreter"


def _annotate_retrieved_chunk(
    chunk: str,
    image_registry: ImageRegistry | None,
    kb_image_stage: KbImageStage | None = None,
) -> str:
    # The stage serves the code interpreter and image_registry serves view_image.
    # They are independent, so the stage must run before the image_registry early return.
    if kb_image_stage is not None:
        chunk = kb_image_stage.annotate(chunk)
    if image_registry is None:
        return chunk
    return annotate(chunk, image_registry)


def _attach_kb_image_stage(tool: BaseTool, stage: KbImageStage) -> None:
    """Give a code-interpreter tool access to this request's retrieved knowledge images."""
    inner = getattr(tool, "tool_instance", tool)
    executor = getattr(inner, "executor", None)
    if executor is None or not hasattr(executor, "attach_stage"):
        return
    executor.attach_stage(stage)
    if not getattr(executor, "supports_kb_stage", False):
        return
    # The description the model sees is a copy taken at construction; refresh it so it
    # carries the knowledge-image usage hint.
    description = executor.description
    inner.description = description
    if inner is not tool:
        tool.description = description


GENERATED_FILES_LIMIT = 50
GENERATED_FILE_SOURCE = "code_interpreter"
_DELIVERABLE_HINT = (
    "Files you save under output/ are attached to your reply automatically and shown to the user as "
    "download cards. Do not write download links, URLs or output/ paths in your reply; mention a file "
    "by its file name only."
)


def _code_executor_of(tool: BaseTool):
    return getattr(getattr(tool, "tool_instance", tool), "executor", None)


def _enable_deliverable_collection(tool: BaseTool) -> None:
    """Have a code-interpreter tool record its output/ files so the answer can carry them."""
    inner = getattr(tool, "tool_instance", tool)
    executor = getattr(inner, "executor", None)
    if executor is None or not hasattr(executor, "collect_deliverables"):
        return
    executor.collect_deliverables = True
    if hasattr(executor, "keep_sandbox"):
        # One E2B sandbox per turn, so a later call can read what an earlier one wrote;
        # _release_code_sandboxes closes it when the turn ends.
        executor.keep_sandbox = True
    description = f"{inner.description}\n\n{_DELIVERABLE_HINT}"
    inner.description = description
    if inner is not tool:
        tool.description = description


def _collect_generated_files(tools: list[BaseTool]) -> list[dict]:
    """Attachment items for the files this turn's code runs left under output/.

    A path written twice keeps its last version; only the last
    GENERATED_FILES_LIMIT files are kept.
    """
    latest: dict[str, dict] = {}
    for tool in tools or []:
        entries = getattr(_code_executor_of(tool), "published_deliverables", None)
        if not isinstance(entries, list):
            continue
        for entry in list(entries):
            latest.pop(entry["path"], None)
            latest[entry["path"]] = entry
    return [
        {
            "file_id": uuid4().hex,
            "file_name": entry["name"],
            "path": entry["path"],
            "type": mimetypes.guess_type(entry["name"])[0] or "",
            "size": entry["size"],
            "source": GENERATED_FILE_SOURCE,
            "filepath": entry["url"],
        }
        for entry in list(latest.values())[-GENERATED_FILES_LIMIT:]
    ]


async def _promote_generated_files(
    tools: list[BaseTool], chat_id: str, user_id: int, storage_partition: str | None
) -> list[dict]:
    files = _collect_generated_files(tools)
    if files:
        await promote_chat_attachments(files, user_id, storage_partition=storage_partition)
        _log_generated_files(chat_id, files)
    return files


def _log_generated_files(chat_id: str, files: list[dict]) -> None:
    logger.info(
        "daily chat generated files chat_id={} count={} promoted={}",
        chat_id,
        len(files),
        sum(1 for f in files if f.get("object_name")),
    )


def build_daily_answer_row(
    *,
    user_id: int,
    chat_id: str,
    sender: str,
    db_content: dict,
    files: list[dict] | None = None,
    error: dict | None = None,
) -> ChatMessage:
    """The answer row of one daily-chat turn.

    One builder for the SSE path and the F004 run projector, so both write the
    same row. ``error`` holds ``error_msg`` plus the public failure metadata of a
    turn that failed or was interrupted; None for a clean turn.
    """
    return ChatMessage(
        files=json.dumps(files, ensure_ascii=False) if files else None,
        user_id=user_id,
        chat_id=chat_id,
        flow_id="",
        type="end",
        is_bot=True,
        # `default` is a last-resort net: tool results are already
        # sanitised by _parse_tool_results, but a serialisation crash
        # here would abort the stream and lose the whole turn, so never
        # let an unexpected object type get that far.
        message=json.dumps(db_content, ensure_ascii=False, default=str),
        category="agent_answer",
        sender=sender,
        extra=json.dumps({"error": True, **error}) if error is not None else "{}",
        source=0,
    )


def _wrap_daily_chat_citation_tool(
    tool: BaseTool,
    citation_collector: CitationRegistryCollector,
    image_registry: ImageRegistry | None = None,
    citation_scope: DailyCitationScope | None = None,
    kb_image_stage: KbImageStage | None = None,
) -> BaseTool:
    if is_web_citation_tool(tool) or hasattr(tool, "knowledge_retriever_tool"):
        return DailyChatCitationToolWrapper.wrap(
            tool,
            citation_collector,
            image_registry=image_registry,
            citation_scope=citation_scope,
            kb_image_stage=kb_image_stage,
        )
    return tool


# Lazily-cached tiktoken encoder — `cl100k_base` is the tokenizer for
# gpt-4 / gpt-5 family and is a reasonable universal estimator. It may
# slightly over-count for Chinese (which leans conservative — preferable
# when enforcing a budget) and slightly under-count for Claude (safe
# direction too: we'd drop a tiny bit more than strictly necessary).
_HISTORY_TOKENIZER = None


def _count_tokens(text: str) -> int:
    """Count tokens in `text` using tiktoken's cl100k_base encoding; fall
    back to a simple char heuristic if tiktoken cannot be loaded (e.g.
    offline install without the bundled BPE files). Used only for the
    history budget guardrail — accuracy within ~15% is sufficient.
    """
    if not text:
        return 0
    global _HISTORY_TOKENIZER
    if _HISTORY_TOKENIZER is None:
        try:
            import tiktoken  # already a transitive dep via assistant_base

            _HISTORY_TOKENIZER = tiktoken.get_encoding("cl100k_base")
        except Exception as exc:
            logger.warning(f"tiktoken unavailable, falling back to char/2 estimator: {exc}")
            _HISTORY_TOKENIZER = False  # sentinel: never retry
    if _HISTORY_TOKENIZER is False:
        # Rough estimator: ~2 chars per token for Chinese-heavy text.
        return max(1, len(text) // 2)
    try:
        return len(_HISTORY_TOKENIZER.encode(text))
    except Exception:
        return max(1, len(text) // 2)


def _json_safe(obj):
    """Recursively coerce a value into a JSON-serialisable structure.

    Tool outputs occasionally carry non-serialisable leaves — most commonly raw
    LangChain ``Document`` objects from a retriever tool whose ``on_tool_end``
    output is the bare return value. Left untouched they make the persist-time
    ``json.dumps({"msg", "events"})`` raise ``TypeError`` and abort the SSE
    stream *after* the answer was already streamed, so the assistant turn is
    lost and the client sees an ``IncompleteRead``.

    Native JSON types pass through; pydantic models (Document → page_content +
    metadata, ToolMessage, schemas) are expanded via ``model_dump`` / ``dict``;
    containers recurse; anything else degrades to ``str``.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    for attr in ("model_dump", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                return _json_safe(method())
            except Exception:
                break
    return str(obj)


def _parse_tool_results(raw_output, tool_name: str):
    """Best-effort parse a tool's raw output into a JSON-serialisable list/dict.

    Covers strings (try json.loads), lists/dicts (deep-sanitised so embedded
    ``Document``/model objects can't break persistence), LangChain
    ToolMessage-like objects with `.content`, and fallback to str().
    """
    if raw_output is None:
        return []
    if isinstance(raw_output, (list, dict)):
        return _json_safe(raw_output)
    if isinstance(raw_output, str):
        s = raw_output.strip()
        if not s:
            return []
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return [{"text": raw_output}]
    content = getattr(raw_output, "content", None)
    if content is not None and content is not raw_output:
        return _parse_tool_results(content, tool_name)
    return [{"text": str(raw_output)}]


_WEB_SEARCH_TOOL_NAMES = {"web_search", "search_web", "bing_search", "tavily_search", "web_fetch"}


def _extract_tool_error(raw_output) -> str | None:
    """Return the error message when a tool produced an error observation.

    When ``_handle_agent_tool_error`` swallows a failure, LangGraph emits a
    ToolMessage with ``status='error'``. Surface that to the frontend so the
    tool-call block can be rendered as failed, while the model still receives
    the message as a normal observation.
    """
    content = getattr(raw_output, "content", raw_output)
    try:
        payload = json.loads(content) if isinstance(content, str) else content
    except (ValueError, TypeError):
        payload = None
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if isinstance(item, dict) and (item.get("error") or item.get("状态") == "失败"):
            return "Tool execution failed."
    if getattr(raw_output, "status", None) == "error":
        return "Tool execution failed."
    return None


def _handle_agent_tool_error(e: Exception) -> str:
    """Turn a tool execution error into ToolMessage content so the ReAct loop
    keeps running instead of crashing the whole agent stream.

    LangGraph's default ``handle_tool_errors`` (``_default_handle_tool_errors``)
    only swallows ``ToolInvocationError`` (bad-args validation) and re-raises
    everything else, so a genuine runtime failure (e.g. an upstream API
    returning 403) propagates out of ``astream_events`` and aborts the chat.
    Feeding the error back to the model as the tool's output lets the agent
    react to it (retry, pick another tool, or tell the user) like a normal
    observation.
    """
    logger.warning(f"[agent_chat] tool execution error fed back to model: {e!r}")
    payload = {"error": "Tool execution failed."}
    if info := FailureContextAdapter.from_error(e):
        payload["failure_info"] = info
    return json.dumps(payload, ensure_ascii=False)


def _build_tool_meta(tool: BaseTool) -> dict:
    """Extract display_name + tool_type from a BaseTool for SSE frontend display.

    Localisation lives on the frontend (`BUILTIN_TOOL_I18N` in
    `ToolCallDisplay.tsx`), so we just forward the raw tool.name here —
    the client maps known keys (search_knowledge_bases, web_search, web_fetch) to
    translated labels and falls back to tool.name for everything else.
    """
    name = tool.name or ""
    lname = name.lower()
    if name == "search_knowledge_bases":
        tool_type = "knowledge"
    elif lname in _WEB_SEARCH_TOOL_NAMES or "web_search" in lname:
        tool_type = "web"
    else:
        tool_type = "tool"
    return {
        "display_name": name,
        "tool_type": tool_type,
    }


async def _build_web_search_tool(user_id: int, tool_id: int | None = None) -> tuple[BaseTool | None, str | None]:
    """Return (tool, error_msg). A non-None error_msg means the agent should
    surface the failure to the user (e.g. missing provider config) rather
    than silently dropping the tool.
    """
    try:
        if tool_id is None:
            web_search_info = GptsToolsDao.get_tool_by_tool_key("web_search")
            if not web_search_info:
                msg = "联网搜索工具未注册到 GptsTools"
                logger.warning(f"{msg}, skipping.")
                return None, msg
            tool_id = web_search_info.id
        t = await ToolExecutor.init_by_tool_id(
            tool_id=tool_id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name=ApplicationTypeEnum.DAILY_CHAT.value,
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=user_id,
        )
        return t, None
    except Exception as exc:
        err = str(exc)
        # Typical symptom for fresh installs: admin hasn't picked a provider.
        if "requires some parameters" in err and "config" in err:
            err = '联网搜索未配置: 请在平台管理的"内置工具 → 联网搜索"设置服务商 (Bing/Tavily/…) 及 API Key'
        else:
            err = _handle_agent_tool_error(exc)
        logger.warning(f"Failed to initialise web_search tool: {err}")
        return None, err


def _parse_model_tool_argument(value: Any) -> Any:
    """Best-effort decode nested structures stringified by tool-calling models."""
    current = value
    for _ in range(2):
        if not isinstance(current, str):
            break
        text = current.strip()
        if not text:
            break
        is_container = text.startswith(("{", "["))
        is_json_string = len(text) >= 2 and text.startswith('"') and text.endswith('"')
        if not (is_container or is_json_string):
            break
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            if not is_container:
                break
            try:
                parsed = json_repair.loads(text)
            except Exception:
                # Recovery is optional; field-specific coercion safely handles the original value.
                break
        if parsed == current:
            break
        current = parsed
    return current


async def _build_knowledge_search_tool(
    knowledge_bases_info: list[dict],
    login_user: UserPayload,
    max_token: int,
    citation_collector: CitationRegistryCollector,
    image_registry: ImageRegistry | None = None,
    citation_scope: DailyCitationScope | None = None,
    kb_image_stage: KbImageStage | None = None,
) -> StructuredTool | None:
    """StructuredTool wrapper around WorkStationService.queryChunksFromDB.

    Tool signature (matches v2.5 Agent spec):
      - `knowledge_base_ids`: list[str]  (required)
      - `query`: str                     (required)
      - `filters.knowledge_base_filters`: optional per-KB tag filters with
        tag_match_mode ∈ {ANY, ALL}.

    Output is a JSON-serialised list of strings, each wrapping one chunk:
      "{<chunk_id>...</chunk_id>
        <file_title>...</file_title>
        <file_abstract>...</file_abstract>
        <paragraph_content>...</paragraph_content>}"
    """
    if not knowledge_bases_info:
        return None

    selected_tag_filters = {
        int(kb["id"]): int(kb["selected_tag_id"])
        for kb in knowledge_bases_info
        if kb.get("source") == "space" and kb.get("selected_tag_id") is not None
    }
    kb_id_whitelist = [str(kb["id"]) for kb in knowledge_bases_info]
    # Space-type KBs skip auth check in queryChunksFromDB; org-type go
    # through KnowledgeDao.ajudge_knowledge_permission. Preserve the
    # distinction the caller captured in `source` so a single LLM-chosen
    # subset still routes each id through the correct path.
    space_id_set: set[int] = {int(kb["id"]) for kb in knowledge_bases_info if kb.get("source") == "space"}
    # kb_id (str) → display name. Used by _format_chunk to embed the source KB
    # name on every chunk, so the frontend can group/dedupe by KB instead of
    # surfacing one chip per file.
    kb_name_by_id: dict[str, str] = {str(kb["id"]): (kb.get("name") or "") for kb in knowledge_bases_info}
    desc_lines = []
    for kb in knowledge_bases_info:
        tags = kb.get("tags") or []
        tag_hint = f" tags={tags}" if tags else ""
        desc_lines.append(
            f"  - id={kb.get('id')} name={kb.get('name', '')} desc={kb.get('description', '') or ''}{tag_hint}"
        )
    description = (
        "Search content in the user-selected knowledge bases. Supports querying "
        "one or more of the available knowledge bases, with optional per-KB tag "
        "filtering (tag_match_mode=ANY|ALL). Call this tool when the user "
        "question can be answered by information in these knowledge bases.\n"
        "Available knowledge bases (with file-level tags you may filter by):\n" + "\n".join(desc_lines)
    )

    class _KbFilter(PydanticBaseModel):
        knowledge_base_id: str = PydanticField(
            description="Which KB this filter applies to. Must appear in knowledge_base_ids.",
        )
        tags: list[str] = PydanticField(
            description="Tag names to filter files inside this KB.",
        )
        tag_match_mode: str = PydanticField(
            default="ANY",
            description="ANY: match any tag; ALL: must carry every tag.",
        )

        @PydanticFieldValidator("knowledge_base_id", mode="before")
        @classmethod
        def _coerce_knowledge_base_id(cls, value):
            return value if value is None else str(value)

        @PydanticFieldValidator("tags", mode="before")
        @classmethod
        def _coerce_tags(cls, value):
            parsed = _parse_model_tool_argument(value)
            if parsed in (None, ""):
                return []
            items = parsed if isinstance(parsed, (list, tuple, set)) else [parsed]
            return [str(item) for item in items if isinstance(item, (str, int, float)) and str(item)]

        @PydanticFieldValidator("tag_match_mode", mode="before")
        @classmethod
        def _coerce_tag_match_mode(cls, value):
            return str(value or "ANY").upper()

    class _Filters(PydanticBaseModel):
        knowledge_base_filters: list[_KbFilter] | None = PydanticField(
            default=None,
            description="Per-KB tag filters.",
        )

        @PydanticFieldValidator("knowledge_base_filters", mode="before")
        @classmethod
        def _coerce_knowledge_base_filters(cls, value):
            parsed = _parse_model_tool_argument(value)
            if parsed in (None, ""):
                return None
            items = parsed if isinstance(parsed, list) else [parsed]
            normalized = []
            for item in items:
                item = _parse_model_tool_argument(item)
                if isinstance(item, (_KbFilter, dict)):
                    normalized.append(item)
            return normalized or None

    class _SearchKbArgs(PydanticBaseModel):
        knowledge_base_ids: list[str] = PydanticField(
            default_factory=lambda: list(kb_id_whitelist),
            description=(
                "Subset of knowledge base IDs (as strings) to search; defaults "
                "to all available. Must be a subset of the advertised IDs."
            ),
        )
        query: str = PydanticField(
            description="Search query in natural language — typically derived from the user question.",
        )
        filters: _Filters | None = PydanticField(
            default=None,
            description="Optional search filters (per-KB tag filters).",
        )

        @PydanticFieldValidator("knowledge_base_ids", mode="before")
        @classmethod
        def _coerce_knowledge_base_ids(cls, value):
            parsed = _parse_model_tool_argument(value)
            if parsed in (None, ""):
                return list(kb_id_whitelist)
            items = parsed if isinstance(parsed, (list, tuple, set)) else [parsed]
            normalized = [str(item) for item in items if isinstance(item, (str, int, float)) and str(item)]
            return normalized or list(kb_id_whitelist)

        @PydanticFieldValidator("query", mode="before")
        @classmethod
        def _coerce_query(cls, value):
            return value if value is None or isinstance(value, str) else str(value)

        @PydanticFieldValidator("filters", mode="before")
        @classmethod
        def _coerce_filters(cls, value):
            parsed = _parse_model_tool_argument(value)
            if parsed in (None, ""):
                return None
            if isinstance(parsed, (_Filters, dict)):
                return parsed
            if isinstance(parsed, list):
                return {"knowledge_base_filters": parsed}
            return None

    def _format_chunk(doc) -> str:
        # Shared formatter (unwrap stored wrapper + preserve citation_key + aligned
        # tag format) lives in KnowledgeUtils so the workstation and the workflow
        # agent knowledge tool can't drift. kb_name resolution stays caller-side.
        meta = getattr(doc, "metadata", {}) or {}
        kb_id_raw = meta.get("knowledge_id") or meta.get("kb_id") or ""
        kb_id = str(kb_id_raw) if kb_id_raw not in (None, "") else ""
        kb_name = kb_name_by_id.get(kb_id, "")
        return knowledge_imp.KnowledgeUtils.format_retrieved_chunk(doc, kb_name)

    async def _resolve_tag_filter_file_ids(
        kb_filters: list[_KbFilter],
    ) -> dict[int, set[int]] | None:
        """Resolve {kb_id: allowed_file_ids_set} from tag-name filters.

        Empty dict ⇒ no filter active. None ⇒ filters resolved but yielded
        zero allowed files (caller should short-circuit to empty results).
        """
        if not kb_filters:
            return {}
        try:
            from bisheng.database.models.group_resource import ResourceTypeEnum
            from bisheng.database.models.tag import TagDao
            from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        except Exception as exc:
            logger.warning(f"[search_kb] tag-filter unavailable: {exc}")
            return {}

        allowed: dict[int, set[int]] = {}
        for f in kb_filters:
            try:
                kb_id = int(f.knowledge_base_id)
            except (TypeError, ValueError):
                continue
            tag_names = [t for t in (f.tags or []) if t]
            if not tag_names:
                continue

            # File-level tag filters are resolved against the KB's file set.
            try:
                files = await KnowledgeFileDao.aget_file_by_filters(
                    knowledge_id=kb_id,
                    page=1,
                    page_size=10000,
                )
            except Exception:
                files = []
            kb_file_ids = [str(fl.id) for fl in files]
            if not kb_file_ids:
                allowed[kb_id] = set()
                continue
            # Space KBs store file tags under SPACE_FILE; org KBs under
            # KNOWLEDGE_FILE. get_tags_by_resource is strict on resource_type,
            # so route per source — otherwise the LLM's tag filter silently
            # returns zero files for org KBs.
            resource_type = ResourceTypeEnum.SPACE_FILE if kb_id in space_id_set else ResourceTypeEnum.KNOWLEDGE_FILE
            tag_map = TagDao.get_tags_by_resource(
                resource_type,
                kb_file_ids,
            )
            wanted = set(tag_names)
            mode = (f.tag_match_mode or "ANY").upper()
            matching: set[int] = set()
            for fid, tags in tag_map.items():
                names = {t.name for t in tags if t.name}
                if mode == "ALL":
                    if wanted.issubset(names):
                        try:
                            matching.add(int(fid))
                        except (TypeError, ValueError):
                            continue
                else:  # ANY
                    if names & wanted:
                        try:
                            matching.add(int(fid))
                        except (TypeError, ValueError):
                            continue
            allowed[kb_id] = matching
        return allowed

    async def _search(
        knowledge_base_ids: list[str],
        query: str,
        # Nested `_Filters` is not in this module's globals. LangGraph ToolNode
        # runs get_type_hints(func) and would raise NameError if we annotate it.
        # Runtime type still comes from args_schema=_SearchKbArgs.
        filters: Any = None,
    ) -> str:
        from bisheng.workstation.domain.schemas.chat import UseKnowledgeBaseParam

        logger.info(
            f"[search_kb] invoke user={login_user.user_id}"
            f" kb_ids={knowledge_base_ids} query={query!r}"
            f" filters={filters.model_dump() if filters else None}"
        )

        allowed = set(kb_id_whitelist)
        kb_ids_int: list[int] = []
        for kid in knowledge_base_ids or []:
            if str(kid) in allowed:
                try:
                    kb_ids_int.append(int(kid))
                except (TypeError, ValueError):
                    continue
        if not kb_ids_int:
            kb_ids_int = [int(k) for k in kb_id_whitelist]
            logger.info(f"[search_kb] hallucinated kb_ids; falling back to whitelist={kb_ids_int}")

        # Fixed user tags are enforced before retrieval; model filters cannot replace them.
        model_filters = [
            item
            for item in ((filters.knowledge_base_filters if filters else None) or [])
            if str(item.knowledge_base_id).isdigit()
            if int(item.knowledge_base_id) not in selected_tag_filters
        ]
        # Resolve tag filters into {kb_id: allowed_file_ids}. Applied as a
        # post-retrieval filter on the docs returned by queryChunksFromDB so
        # we don't have to plumb file-id filters into the milvus/es layer.
        try:
            file_filter = await _resolve_tag_filter_file_ids(
                model_filters,
            )
        except Exception as exc:
            logger.warning(f"[search_kb] tag resolution failed: {exc}")
            file_filter = {}

        # Split back into the two buckets so queryChunksFromDB picks the
        # right auth-check behaviour per KB source.
        space_bucket = [i for i in kb_ids_int if i in space_id_set]
        org_bucket = [i for i in kb_ids_int if i not in space_id_set]
        failures: list[dict] = []
        try:
            _formatted, finally_docs, failures = await WorkStationService.queryChunksFromDB(
                question=query,
                use_knowledge_param=UseKnowledgeBaseParam(
                    knowledge_space_ids=space_bucket,
                    organization_knowledge_ids=org_bucket,
                    knowledge_space_tag_filters={
                        space_id: selected_tag_filters[space_id]
                        for space_id in space_bucket
                        if space_id in selected_tag_filters
                    },
                ),
                max_token=max_token,
                login_user=login_user,
            )
        except Exception as exc:
            logger.exception(f"[search_kb] queryChunksFromDB failed: {exc}")
            return _handle_agent_tool_error(exc)

        docs = list(finally_docs or [])
        if file_filter:

            def _doc_allowed(doc) -> bool:
                meta = getattr(doc, "metadata", {}) or {}
                try:
                    kb_id = int(meta.get("knowledge_id") or meta.get("kb_id") or 0)
                    file_id = int(meta.get("document_id") or meta.get("file_id") or 0)
                except (TypeError, ValueError):
                    return True
                if kb_id not in file_filter:
                    return True  # no filter set for this KB
                return file_id in file_filter[kb_id]

            pre = len(docs)
            docs = [d for d in docs if _doc_allowed(d)]
            logger.info(
                f"[search_kb] tag-filter applied docs={pre}->{len(docs)}"
                f" allow_map={{kb: [n_files]}}="
                f"{ {k: len(v) for k, v in file_filter.items()} }"
            )

        docs = annotate_rag_documents_with_citations(docs)
        citation_items = collect_rag_citation_registry_items(docs)
        await cache_citation_registry_items(citation_items)
        citation_collector.extend(citation_items)
        # F075: the model sees <ref>S3</ref>, never the registry key.
        chunks = await handles_for_chunks(citation_scope, citation_items, [_format_chunk(doc) for doc in docs])
        results = [_annotate_retrieved_chunk(chunk, image_registry, kb_image_stage) for chunk in chunks]

        # Surface per-KB failures as synthetic chunks carrying
        # <retrieval_error>. The frontend detects these and renders the KB
        # chip in an error state with the error message, so users see which
        # KB failed and why instead of the tool silently dropping them.
        for f in failures or []:
            kb_name = f.get("name") or ""
            if not kb_name:
                # fall back to the name we resolved earlier
                kb_name = kb_name_by_id.get(str(f.get("id", "")), "")
            err_text = str(f.get("error") or "").replace("</retrieval_error>", "")
            results.append(
                "{"
                f"<knowledge_base_id>{f.get('id', '')}</knowledge_base_id>\n"
                f"<knowledge_base_name>{kb_name}</knowledge_base_name>\n"
                f"<retrieval_error>{err_text}</retrieval_error>"
                "}"
            )
            if info := FailureContextAdapter.validate(f.get("failure_info")):
                results.append({"error": "Knowledge retrieval failed.", "failure_info": info})

        logger.info(
            f"[search_kb] returning {len(results)} chunks"
            f" (ok={len(results) - len(failures or [])} failed={len(failures or [])})"
            f" total_chars={sum(len(r) for r in results)}"
        )
        return json.dumps(results, ensure_ascii=False)

    return StructuredTool.from_function(
        func=None,
        coroutine=_search,
        name="search_knowledge_bases",
        description=description,
        args_schema=_SearchKbArgs,
    )


async def _resolve_user_kb_selection(data: APIChatCompletion) -> list[dict]:
    """Translate APIChatCompletion.use_knowledge_base into KB metadata dicts.

    Returns [] if the user hasn't picked any KB. Used both for building the
    `search_knowledge_bases` tool and for composing the user prompt's
    <selected_knowledge_bases> section. Each KB dict carries the set of tag
    names attached to files inside it (aggregated), so the model can pick
    meaningful tag filters when calling search_knowledge_bases.
    """
    ukb = data.use_knowledge_base
    if not ukb:
        return []
    from bisheng.knowledge.domain.services.knowledge_space_tag_filter_service import KnowledgeSpaceTagFilterService

    await KnowledgeSpaceTagFilterService().validate_selection(ukb.knowledge_space_tag_filters)
    org_ids = list(ukb.organization_knowledge_ids or [])
    space_ids = list(ukb.knowledge_space_ids or [])
    ids = org_ids + space_ids
    if not ids:
        return []
    # Preserve the bucket each ID came from so `queryChunksFromDB` can route
    # space-type KBs past the auth check (they're personal) while org-type
    # still enforce permissions.
    space_id_set = set(space_ids)
    try:
        kbs = await KnowledgeDao.aget_list_by_ids(ids)
    except Exception as exc:
        logger.warning(f"Failed to load Knowledge rows for {ids}: {exc}")
        return []

    # Best-effort aggregation of file-level tags per KB. A KB with many files
    # can have a large tag set; we cap the total tags advertised per KB at 50
    # to avoid prompt bloat.
    tags_by_kb: dict[int, list[str]] = {}
    try:
        from bisheng.database.models.group_resource import ResourceTypeEnum
        from bisheng.database.models.tag import TagDao
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        for kb in kbs:
            try:
                files = await KnowledgeFileDao.aget_file_by_filters(
                    knowledge_id=kb.id,
                    page=1,
                    page_size=500,
                )
            except Exception:
                files = []
            file_ids = [str(f.id) for f in files] if files else []
            if not file_ids:
                tags_by_kb[kb.id] = []
                continue
            try:
                # Route by KB source: knowledge space files use SPACE_FILE,
                # organization knowledge base files use KNOWLEDGE_FILE. Without
                # this, tags on org-KB files never reach the prompt.
                resource_type = (
                    ResourceTypeEnum.SPACE_FILE if kb.id in space_id_set else ResourceTypeEnum.KNOWLEDGE_FILE
                )
                tag_map = TagDao.get_tags_by_resource(resource_type, file_ids)
                seen: set[str] = set()
                names: list[str] = []
                for tags in tag_map.values():
                    for tag in tags:
                        if tag.name and tag.name not in seen:
                            seen.add(tag.name)
                            names.append(tag.name)
                            if len(names) >= 50:
                                break
                    if len(names) >= 50:
                        break
                tags_by_kb[kb.id] = names
            except Exception as exc:
                logger.warning(f"Failed to aggregate tags for kb={kb.id}: {exc}")
                tags_by_kb[kb.id] = []
    except Exception as exc:
        logger.warning(f"Tag aggregation unavailable: {exc}")

    resolved = [
        {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description or "",
            "tags": tags_by_kb.get(kb.id, []),
            "source": "space" if kb.id in space_id_set else "organization",
            **(
                {"selected_tag_id": ukb.knowledge_space_tag_filters[kb.id]}
                if kb.id in ukb.knowledge_space_tag_filters
                else {}
            ),
        }
        for kb in kbs
    ]
    logger.info(
        f"[resolve_user_kb] resolved {len(resolved)} kbs"
        f" ids={[kb['id'] for kb in resolved]}"
        f" tag_counts={[len(kb['tags']) for kb in resolved]}"
    )
    return resolved


async def _prepare_tools(
    tool_payloads: list[dict] | None,
    login_user: UserPayload,
    ws_config,  # WorkstationConfig; kept untyped to avoid circular import cost
    citation_collector: CitationRegistryCollector,
    knowledge_bases_info: list[dict] | None = None,
    image_registry: ImageRegistry | None = None,
    citation_scope: DailyCitationScope | None = None,
    kb_image_stage: KbImageStage | None = None,
) -> tuple[list[BaseTool], list[dict]]:
    """Assemble the BaseTool list passed to LangGraph create_react_agent.

    `tool_payloads` items come from the frontend request; each payload has
    at least {id: int, tool_key: str, type: 'tool'|'knowledge'}.  Only
    entries with type=='tool' are materialised here; knowledge base is
    handled exclusively through the `search_knowledge_bases` tool built
    from `knowledge_bases_info`.
    """
    # Shared with the unified runtime (F004 T022). Imported here because the
    # linsight package imports this module.
    from bisheng.linsight.domain.services.tool_assembly import assemble_daily_tools

    return await assemble_daily_tools(
        tool_payloads,
        login_user,
        ws_config,
        citation_collector,
        knowledge_bases_info=knowledge_bases_info,
        image_registry=image_registry,
        citation_scope=citation_scope,
        kb_image_stage=kb_image_stage,
    )


async def log_telemetry_events(user_id: str, conversation_id: str, start_time: float):
    """Log application alive and duration telemetry."""
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)
    common_data = {
        "app_id": ApplicationTypeEnum.DAILY_CHAT.value,
        "app_name": ApplicationTypeEnum.DAILY_CHAT.value,
        "app_type": ApplicationTypeEnum.DAILY_CHAT,
        "chat_id": conversation_id,
        "start_time": int(start_time),
        "end_time": int(end_time),
    }
    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
        trace_id=trace_id_var.get(),
        event_data=ApplicationAliveEventData(**common_data),
    )
    await telemetry_service.log_event(
        user_id=user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
        trace_id=trace_id_var.get(),
        event_data=ApplicationProcessEventData(**common_data, process_time=duration_ms),
    )


# =========================================================================== #
# v2.5 — LangGraph Agent-mode chat completion                                  #
# =========================================================================== #


async def _agent_initialize_chat(
    data: APIChatCompletion,
    login_user: UserPayload,
    session_subject: SessionSubject | None = None,
    *,
    skip_llm: bool = False,
    memory_register: MemoryRegister | None = None,
):
    """Agent-mode init: creates/fetches the conversation and inserts the user's
    question row with its query, attachments and optional composer references
    under category='question', type='over'.

    Differences vs legacy initialize_chat:
      - `message` column is JSON (not plain text)
      - `type` is 'over' (aligned with ChatResponse semantics in workflow)
      - `extra` is '{}' (no parentMessageId — new data is linear, no tree)
      - `overrideParentMessageId` is ignored (regenerate UI removed)
    """
    ws_config = await WorkStationService.aget_config()
    from bisheng.dsh.domain.services.model_catalog import user_workbench_models

    ws_config.models = await user_workbench_models(login_user.user_id)
    model_info = next((m for m in ws_config.models if m.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")

    conversation_id = data.conversationId
    is_new_conversation = False
    if not conversation_id:
        is_new_conversation = True
        conversation_id = uuid4().hex
        new_session = MessageSession(
            chat_id=conversation_id,
            name="New Chat",
            flow_type=FlowType.WORKSTATION.value,
            user_id=login_user.user_id,
        )
        if session_subject is not None:
            new_session = session_subject.stamp(new_session)
        if data.project_id is not None:
            if session_subject is not None:
                from bisheng.common.errcode.chat import ProjectInputError

                raise ProjectInputError()
            await ChatSessionService.create_owned_project_session(new_session, login_user, data.project_id)
        else:
            await MessageSessionDao.async_insert_one(new_session)
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversation_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source="platform",
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT,
            ),
        )

    conversation = (
        await ChatSessionService.get_subject_session(conversation_id, session_subject)
        if session_subject is not None
        else await MessageSessionDao.async_get_one(conversation_id)
    )
    if conversation is None:
        raise ConversationNotFoundError()
    if not is_new_conversation:
        await MessageSessionDao.touch_session(conversation_id)
        conversation = await MessageSessionDao.async_get_one(conversation_id)

    # F132: login-state endpoints register the conversation for long-term memory
    # (decision 6). It runs before this turn's question row so the watermark set
    # at first registration excludes only earlier history (AC-40).
    await register_session(memory_register, conversation_id)

    # Same as the legacy flow: the attachment becomes permanent at send time,
    # not at upload time (see promote_chat_attachments).
    await promote_chat_attachments(
        data.files,
        login_user.user_id,
        storage_partition=session_subject.storage_partition if session_subject is not None else None,
    )

    # Always insert a brand-new question row — Agent flow has no regenerate.
    message = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=login_user.user_id,
            chat_id=conversation_id,
            flow_id="",
            type="over",
            is_bot=False,
            sender="User",
            files=json.dumps(data.files) if data.files else None,
            extra="{}",
            message=serialize_user_question(data.text, data.files, data.composer_references),
            category="question",
            source=0,
            sensitive_status=SensitiveStatus.VIOLATIONS.value if skip_llm else SensitiveStatus.PASS.value,
        )
    )
    if skip_llm:
        mark_session_content_violation(conversation_id)
        return ws_config, conversation, message, None, model_info, is_new_conversation
    bisheng_llm = await LLMService.get_bisheng_llm(
        model_id=data.model,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=login_user.user_id,
    )
    return ws_config, conversation, message, bisheng_llm, model_info, is_new_conversation


async def persist_blocked_workbench_answer(conversation, model_info, auto_reply: str) -> ChatMessage:
    """Record the auto-reply of a blocked input and mark the conversation.

    Shared by the SSE answer below and the F004 run-protocol answer
    (``run_send._blocked_response``), so both store the same rows.
    """
    row = build_blocked_answer_row(
        user_id=conversation.user_id,
        conversation_id=conversation.chat_id,
        sender=getattr(model_info, "displayName", "") or "",
        auto_reply=auto_reply,
    )
    resp = await ChatMessageDao.ainsert_one(row)
    mark_session_content_violation(conversation.chat_id)
    # F132: a blocked turn is never consolidated into long-term memory; move the
    # watermark past it (no-op for chats not registered for memory).
    try:
        await MemoryActivity.end_turn(conversation.chat_id, resp.id, False)
    except Exception:
        logger.exception("memory: ending a blocked turn failed chat_id={}", conversation.chat_id)
    return resp


def _respond_blocked_workbench(conversation, message, model_info, data: APIChatCompletion, auto_reply: str):
    """Short SSE: user row already persisted; write auto-reply and close the turn."""

    async def event_stream():
        resp = await persist_blocked_workbench_answer(conversation, model_info, auto_reply)
        for chunk in iter_blocked_sse(
            conversation_id=conversation.chat_id,
            user_message_id=message.id,
            user_text=data.text or "",
            files=data.files or [],
            auto_reply=auto_reply,
            answer_message_id=resp.id,
        ):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _department_limit_stream_response() -> StreamingResponse:
    """SSE error for a rejected execution lease at a submit entry."""
    return StreamingResponse(
        iter([DepartmentDailyChatConcurrentLimitError().to_sse_event_instance_str()]),
        media_type="text/event-stream",
    )


async def stream_chat_completion(
    request: Request,
    data: APIChatCompletion,
    login_user: UserPayload,
    *,
    session_subject: SessionSubject | None = None,
    memory_register: MemoryRegister | None = None,
):
    """The one entry of every workstation chat request; both callers use the unified runtime (F004).

    The login-state endpoint (no ``session_subject``) gets daily chat and deep
    research (``data.task_mode``) alike, under either response protocol.

    The Open API entry passes ``session_subject``. Its contract is unchanged
    (AC-39): ``run_send`` answers it with today's SSE stream and the answer of
    this message (see the ``run_send`` module docstring). It always sends
    ``task_mode=False`` (``OpenDailyChatCompletionReq.to_internal``; an Open API
    task is submitted through ``OpenTaskModeService.submit``), mounts no skills
    and passes no ``memory_register``, so its turns never use long-term memory
    (F132 AC-10).
    """
    from . import run_send

    if session_subject is None:
        return await run_send.unified_send(request, data, login_user, memory_register=memory_register)
    daily_data = data.model_copy(update={"skills": [], "task_mode": False})
    return await run_send.unified_send(request, daily_data, login_user, session_subject=session_subject)


def _to_linsight_submit(data: APIChatCompletion):
    """Map the unified chat request to a linsight submit schema (F035 Track J).

    Sound mappings only — question, conversation (session_id), the per-turn
    execution model, and the knowledge booleans.

    Model IS threaded: the daily ``model`` is an id from the same LLM registry
    linsight resolves against (agent_factory._resolve_model), so the user's
    picked model takes effect on the task turn (falling back to the tenant
    linsight default only when absent).

    Unified-resource direction (2026-06-16, user decision): task mode reuses the
    DAILY resources; linsight's own resource subsystems are deprecated. Tools and
    files are now threaded from the daily fields:

    - **Tools**: daily ``ToolPayload`` ids live in the SAME ``GptsTools`` table as
      linsight (both resolve via ``ToolExecutor``); the linsight per-app config
      whitelist is dropped (see ``init_linsight_config_tools``), so the user's
      daily tool selection binds directly. We wrap the flat ids into the grouped
      linsight tool shape (``_extract_tool_ids`` reads ``children[].id``).
    - **Files**: threaded as linsight-resolvable refs (see below).
    """
    from bisheng.linsight.domain.schemas.linsight_schema import (
        LinsightQuestionSubmitSchema,
        LinsightToolSchema,
        SubmitFileSchema,
        ToolChildrenSchema,
    )

    ukb = data.use_knowledge_base

    # Tools: wrap the daily flat selection into one grouped linsight tool whose
    # children carry the real GptsTools ids. The whitelist is dropped downstream,
    # so every selected tool the user has access to binds in the task agent.
    submit_tools = None
    if data.tools:
        children = [
            ToolChildrenSchema(id=int(tp.id), tool_key=tp.tool_key)
            for tp in data.tools
            if (tp.type or "tool") == "tool" and tp.id
        ]
        if children:
            submit_tools = [LinsightToolSchema(id=0, name="daily", is_preset=0, children=children)]

    # Files (unified-resource): task mode reuses the DAILY upload bucket. Each
    # daily file dict carries `filepath` (raw MinIO path) — pass it as `file_url`
    # so linsight parses it on-the-fly via TempFilePipeline at ingestion. Files
    # uploaded via the linsight pipeline (no filepath) keep the legacy path.
    submit_files = None
    if data.files:
        submit_files = []
        for item in data.files:
            file_id = item.get("file_id") or item.get("id")
            if not file_id:
                continue
            submit_files.append(
                SubmitFileSchema(
                    file_id=str(file_id),
                    file_name=item.get("file_name") or item.get("filename") or item.get("name") or "",
                    parsing_status=item.get("parsing_status") or "completed",
                    file_url=item.get("filepath") or item.get("file_url"),
                    # Folder upload: the tree the user dropped is rebuilt inside the
                    # task workspace from this. Absent on a plain single-file pick.
                    relative_path=item.get("relative_path") or None,
                    size=int(item.get("size") or 0),
                )
            )
        submit_files = submit_files or None

    # Knowledge (unified-resource): thread the daily picker's EXACT selection so
    # the task agent searches precisely the chosen KBs — organization (NORMAL) KB
    # ids + knowledge-space (SPACE) ids — instead of every KB of a coarse type.
    # The booleans are still set for storage/back-compat but no longer drive
    # injection (task_exec resolves from the id lists).
    org_ids = list(ukb.organization_knowledge_ids or []) if ukb else []
    space_ids = list(ukb.knowledge_space_ids or []) if ukb else []
    personal_enabled = bool(ukb and ukb.personal_knowledge_enabled)

    return LinsightQuestionSubmitSchema(
        question=data.text or "",
        session_id=data.conversationId,
        personal_knowledge_enabled=personal_enabled,
        org_knowledge_enabled=bool(org_ids),
        organization_knowledge_ids=org_ids or None,
        knowledge_space_ids=space_ids or None,
        model=data.model or None,
        files=submit_files,
        tools=submit_tools,
        # F035 Track H: thread the daily task-mode skill picker onto the submit so
        # only the user's explicit selection is materialized (None/[] = no skills).
        skills=data.skills,
        skill_ids=data.skill_ids,
    )
