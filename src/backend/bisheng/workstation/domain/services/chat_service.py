import asyncio
import json
import time
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from fastapi import Request
from fastapi.responses import StreamingResponse
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from loguru import logger

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schema.chat_schema import APIChatCompletion
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum, ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.errcode.knowledge import KnowledgeFileNotSupportedError
from bisheng.common.errcode.workstation import ConversationNotFoundError
from bisheng.common.schemas.telemetry.event_data_schema import (
    ApplicationAliveEventData,
    ApplicationProcessEventData,
    NewMessageSessionEventData,
)
from bisheng.common.services import telemetry_service
from bisheng.core.cache.utils import async_file_download
from bisheng.core.logger import trace_id_var
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from .chat_helpers import (
    gen_title,
    read_image_as_data_url,
    user_message,  # legacy `{created: true}` envelope — tells the client to
                   # insert a placeholder entry in the sidebar conversation list
                   # the moment a new chat is created (title updated later via
                   # gen_title). Must be emitted *before* any category event.
    _sse_resp,  # v2.5 Agent-mode SSE builder
)
from .constants import VISUAL_MODEL_FILE_TYPES
from .workstation_service import WorkStationService


async def get_file_content(filepath_local: str, file_name: str, invoke_user_id: int):
    """Extract uploaded file content for prompt building."""
    from bisheng.api.v1.schemas import FileProcessBase
    from bisheng.knowledge.rag.temp_file_pipeline import TempFilePipeline

    file_rule = FileProcessBase(
        knowledge_id=0,
        separator=['\n\n', '\n'],
        separator_rule=['after', 'after'],
        chunk_size=1000,
        chunk_overlap=0,
    )
    pipeline = TempFilePipeline(
        invoke_user_id=invoke_user_id,
        local_file_path=filepath_local,
        file_name=file_name,
        file_rule=file_rule,
    )
    try:
        result = await pipeline.arun()
        raw_texts = [doc.page_content for doc in result.documents]
    except KnowledgeFileNotSupportedError:
        raw_texts = []
    return knowledge_imp.KnowledgeUtils.chunk2promt(''.join(raw_texts), {'source': file_name})


async def initialize_chat(data: APIChatCompletion, login_user: UserPayload):
    """Initialize chat session, message, and llm."""
    ws_config = await WorkStationService.aget_config()
    model_info = next((model for model in ws_config.models if model.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")

    conversation_id = data.conversationId
    is_new_conversation = False
    if not conversation_id:
        is_new_conversation = True
        conversation_id = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversation_id,
                name='New Chat',
                flow_type=FlowType.WORKSTATION.value,
                user_id=login_user.user_id,
            )
        )
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversation_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source='platform',
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT,
            ),
        )

    conversation = await MessageSessionDao.async_get_one(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()

    if not is_new_conversation:
        await MessageSessionDao.touch_session(conversation_id)
        conversation = await MessageSessionDao.async_get_one(conversation_id)

    if data.overrideParentMessageId:
        message = await ChatMessageDao.aget_message_by_id(int(data.overrideParentMessageId))
    else:
        message = await ChatMessageDao.ainsert_one(
            ChatMessage(
                user_id=login_user.user_id,
                chat_id=conversation_id,
                flow_id='',
                type='human',
                is_bot=False,
                sender='User',
                files=json.dumps(data.files) if data.files else None,
                extra=json.dumps({'parentMessageId': data.parentMessageId}),
                message=data.text,
                category='question',
                source=0,
            )
        )

    bisheng_llm = await LLMService.get_bisheng_llm(
        model_id=data.model,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=login_user.user_id,
    )
    return ws_config, conversation, message, bisheng_llm, model_info, is_new_conversation


# --------------------------------------------------------------------------- #
# v2.5 Agent Mode Helper Functions
#
# These are the low-level building blocks for the LangGraph ReAct agent rewrite (P2-5):
#   - _get_agent_max_iterations: Reads the configurable recursion_limit from the database.
#   - _build_user_content: Concatenates the user prompt based on three scenarios: {Plain Text / +Files / +Knowledge Base}.
#   - _parse_tool_results: Normalizes BaseTool output to facilitate SSE (Server-Sent Events) and database storage.
#   - _build_tool_meta: Extracts tool display_name and tool_type for frontend display.
#   - _build_web_search_tool: Directly reuses the BaseTool from ToolExecutor.init_by_tool_id.
#   - _build_knowledge_search_tool: Wraps queryChunksFromDB using StructuredTool.
#   - _resolve_user_kb_selection: Resolves UseKnowledgeBaseParam into a list of KB metadata.
#   - _prepare_tools: Entry point function; integrates tool_payloads + knowledge_bases_info -> List[BaseTool].
# --------------------------------------------------------------------------- #

from pydantic import BaseModel as PydanticBaseModel, Field as PydanticField, SkipValidation

from langchain_core.tools import ArgsSchema, BaseTool, StructuredTool
from typing_extensions import Annotated

from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_PROMPT_RULES,
    CitationRegistryCollector,
    annotate_rag_documents_with_citations,
    annotate_web_results_with_citations,
    cache_citation_registry_items,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
    collect_web_citation_registry_items,
    save_message_citations,
    select_registry_items_for_persistence,
)
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

DEFAULT_AGENT_MAX_ITERATIONS = 50
DAILY_CHAT_CITATION_PROMPT_RULES = f"""{CITATION_PROMPT_RULES}

When the tool's results already contain the aforementioned private section reference markers, the final answer must retain these markers as is; they must not be deleted, rewritten, or interpreted.

Do not output this rule."""


class DailyChatCitationToolWrapper(BaseTool):
    """Add citation prompt context for daily chat tool invocations."""

    name: str
    description: str
    args_schema: Annotated[Optional[ArgsSchema], SkipValidation()] = PydanticField(default=None)
    tool: BaseTool
    citation_collector: CitationRegistryCollector = PydanticField(exclude=True)

    @classmethod
    def wrap(cls, tool: BaseTool, citation_collector: CitationRegistryCollector) -> BaseTool:
        return cls(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            tool=tool,
            citation_collector=citation_collector,
        )

    def _is_web_search_tool(self) -> bool:
        return self.tool.name == 'web_search' or getattr(self.tool, 'tool_name', None) == 'web_search'

    def _has_knowledge_rag_tool(self) -> bool:
        return hasattr(self.tool, 'knowledge_retriever_tool')

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
        return json.dumps(results, ensure_ascii=False)

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
        await self._aextend_citation_registry_items(collect_web_citation_registry_items(results))
        return json.dumps(results, ensure_ascii=False)

    def _build_knowledge_prompt(self) -> ChatPromptTemplate:
        messages = list(self.tool.chat_prompt.messages)
        citation_rules_message = SystemMessagePromptTemplate.from_template(CITATION_PROMPT_RULES)
        insert_index = 1 if messages and isinstance(messages[0], SystemMessagePromptTemplate) else 0
        messages.insert(insert_index, citation_rules_message)
        return ChatPromptTemplate.from_messages(messages)

    def _build_knowledge_inputs(self, query: str, retrieval_result: Any) -> dict:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        self._extend_citation_registry_items(collect_rag_citation_registry_items(source_documents))
        inputs = {'context': source_documents}
        if 'question' in self.tool.chat_prompt.input_variables:
            inputs['question'] = query
        return inputs

    async def _abuild_knowledge_inputs(self, query: str, retrieval_result: Any) -> dict:
        source_documents = list(retrieval_result or [])
        source_documents = annotate_rag_documents_with_citations(source_documents)
        await self._aextend_citation_registry_items(collect_rag_citation_registry_items(source_documents))
        inputs = {'context': source_documents}
        if 'question' in self.tool.chat_prompt.input_variables:
            inputs['question'] = query
        return inputs

    def _extend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        cache_citation_registry_items_sync(items)
        self.citation_collector.extend(items)

    async def _aextend_citation_registry_items(self, items: list[CitationRegistryItemSchema]) -> None:
        await cache_citation_registry_items(items)
        self.citation_collector.extend(items)

    def _run(self, query: str, config=None, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            return self._append_web_citation(self.tool.invoke({'query': query}, config=config))
        if not self._has_knowledge_rag_tool():
            return self.tool.invoke({'query': query}, config=config)

        retrieval_result = self.tool.knowledge_retriever_tool.invoke({'query': query}, config=config)
        llm_inputs = self._build_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return qa_chain.invoke(llm_inputs, config=config)

    async def _arun(self, query: str, config=None, **kwargs: Any) -> Any:
        if self._is_web_search_tool():
            return await self._aappend_web_citation(await self.tool.ainvoke({'query': query}, config=config))
        if not self._has_knowledge_rag_tool():
            return await self.tool.ainvoke({'query': query}, config=config)

        retrieval_result = await self.tool.knowledge_retriever_tool.ainvoke({'query': query}, config=config)
        llm_inputs = await self._abuild_knowledge_inputs(query, retrieval_result)
        qa_chain = create_stuff_documents_chain(llm=self.tool.llm, prompt=self._build_knowledge_prompt())
        return await qa_chain.ainvoke(llm_inputs, config=config)


def _wrap_daily_chat_citation_tool(
        tool: BaseTool,
        citation_collector: CitationRegistryCollector,
) -> BaseTool:
    if tool.name == 'web_search' or hasattr(tool, 'knowledge_retriever_tool'):
        return DailyChatCitationToolWrapper.wrap(tool, citation_collector)
    return tool


async def _get_agent_max_iterations() -> int:
    """Return the DB-configured max recursion depth for the ReAct agent loop.

    Reads `daily_chat.agent_max_iterations` from the DB config (via
    ConfigService.aget_daily_chat_conf). Any failure path returns 50.
    The DailyChatConf field validator already normalises missing/invalid/
    <=0 values to 50, so this just a defensive wrapper over the async fetch.
    """
    try:
        from bisheng.common.services.config_service import settings as bisheng_settings
        conf = await bisheng_settings.aget_daily_chat_conf()
        n = int(conf.agent_max_iterations)
        return n if n > 0 else DEFAULT_AGENT_MAX_ITERATIONS
    except Exception as exc:
        logger.warning(f'Failed to read agent_max_iterations, falling back to 50: {exc}')
        return DEFAULT_AGENT_MAX_ITERATIONS


DEFAULT_HISTORY_MAX_TOKENS = 8000


async def _get_history_max_tokens() -> int:
    """Return the DB-configured token budget for chat history injected into
    the LLM prompt.

    Reads `daily_chat.history_max_tokens` from the DB config (via
    ConfigService.aget_daily_chat_conf). Any failure path returns
    DEFAULT_HISTORY_MAX_TOKENS. Schema validator normalises
    missing/invalid/<=0 values upstream, so this is a defensive wrapper.
    """
    try:
        from bisheng.common.services.config_service import settings as bisheng_settings
        conf = await bisheng_settings.aget_daily_chat_conf()
        n = int(conf.history_max_tokens)
        return n if n > 0 else DEFAULT_HISTORY_MAX_TOKENS
    except Exception as exc:
        logger.warning(
            f'Failed to read history_max_tokens, falling back to '
            f'{DEFAULT_HISTORY_MAX_TOKENS}: {exc}'
        )
        return DEFAULT_HISTORY_MAX_TOKENS


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
            _HISTORY_TOKENIZER = tiktoken.get_encoding('cl100k_base')
        except Exception as exc:
            logger.warning(
                f'tiktoken unavailable, falling back to char/2 estimator: {exc}'
            )
            _HISTORY_TOKENIZER = False  # sentinel: never retry
    if _HISTORY_TOKENIZER is False:
        # Rough estimator: ~2 chars per token for Chinese-heavy text.
        return max(1, len(text) // 2)
    try:
        return len(_HISTORY_TOKENIZER.encode(text))
    except Exception:
        return max(1, len(text) // 2)


def _build_user_content(
        question: str,
        file_context: str = '',
        knowledge_bases_info: list[dict] | None = None,
) -> str:
    """Compose the user message content for the LLM.

    3 scenarios:
      (1) plain text question
      (2) question + uploaded file content
      (3) question + file content + selected knowledge bases (told to the model
          via <selected_knowledge_bases>, which hints it to call search_knowledge_bases).
    """
    has_kb = bool(knowledge_bases_info)
    has_file = bool(file_context)

    if not has_kb and not has_file:
        logger.info(
            f'[build_user_content] scenario=plain question_len={len(question)}'
            f' preview={question[:120]!r}'
        )
        return question

    parts: list[str] = []
    if has_kb:
        kb_brief = [
            {
                'id': kb.get('id'),
                'name': kb.get('name', ''),
                'description': kb.get('description', '') or '',
                'tags': kb.get('tags') or [],
            }
            for kb in knowledge_bases_info
        ]
        parts.append(
            '<selected_knowledge_bases>\n'
            f'{json.dumps(kb_brief, ensure_ascii=False)}\n'
            '</selected_knowledge_bases>'
        )
    if has_file:
        parts.append(f'<uploaded_file_content>\n{file_context}\n</uploaded_file_content>')
    parts.append(f'<user_question>\n{question}\n</user_question>')
    final_content = '\n\n'.join(parts)

    # Debug trace for QA: mirrors the exact prompt fed to the LLM.
    scenario = 'kb+file' if (has_kb and has_file) else ('kb' if has_kb else 'file')
    logger.info(
        f'[build_user_content] scenario={scenario}'
        f' kb_count={len(knowledge_bases_info or [])}'
        f' file_context_len={len(file_context or "")}'
        f' question_len={len(question)}'
        f' final_len={len(final_content)}'
    )
    logger.info(f'[build_user_content] final_content=\n{final_content}')
    return final_content


def _parse_tool_results(raw_output, tool_name: str):
    """Best-effort parse a tool's raw output into a JSON-serialisable list/dict.

    Covers strings (try json.loads), lists/dicts (pass through), LangChain
    ToolMessage-like objects with `.content`, and fallback to str().
    """
    if raw_output is None:
        return []
    if isinstance(raw_output, (list, dict)):
        return raw_output
    if isinstance(raw_output, str):
        s = raw_output.strip()
        if not s:
            return []
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return [{'text': raw_output}]
    content = getattr(raw_output, 'content', None)
    if content is not None and content is not raw_output:
        return _parse_tool_results(content, tool_name)
    return [{'text': str(raw_output)}]


_WEB_SEARCH_TOOL_NAMES = {'web_search', 'search_web', 'bing_search', 'tavily_search'}


def _build_tool_meta(tool: BaseTool) -> dict:
    """Extract display_name + tool_type from a BaseTool for SSE frontend display.

    Localisation lives on the frontend (`BUILTIN_TOOL_I18N` in
    `ToolCallDisplay.tsx`), so we just forward the raw tool.name here —
    the client maps known keys (search_knowledge_bases, web_search) to
    translated labels and falls back to tool.name for everything else.
    """
    name = tool.name or ''
    lname = name.lower()
    if name == 'search_knowledge_bases':
        tool_type = 'knowledge'
    elif lname in _WEB_SEARCH_TOOL_NAMES or 'web_search' in lname:
        tool_type = 'web'
    else:
        tool_type = 'tool'
    return {
        'display_name': name,
        'tool_type': tool_type,
    }


async def _build_web_search_tool(user_id: int) -> tuple[BaseTool | None, str | None]:
    """Return (tool, error_msg). A non-None error_msg means the agent should
    surface the failure to the user (e.g. missing provider config) rather
    than silently dropping the tool.
    """
    web_search_info = GptsToolsDao.get_tool_by_tool_key('web_search')
    if not web_search_info:
        msg = '联网搜索工具未注册到 GptsTools'
        logger.warning(f'{msg}, skipping.')
        return None, msg
    try:
        t = await ToolExecutor.init_by_tool_id(
            tool_id=web_search_info.id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name=ApplicationTypeEnum.DAILY_CHAT.value,
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=user_id,
        )
        return t, None
    except Exception as exc:
        err = str(exc)
        # Typical symptom for fresh installs: admin hasn't picked a provider.
        if 'requires some parameters' in err and 'config' in err:
            err = '联网搜索未配置：请在平台管理的"内置工具 → 联网搜索"设置服务商（Bing/Tavily/…）及 API Key'
        logger.warning(f'Failed to initialise web_search tool: {err}')
        return None, err


async def _build_knowledge_search_tool(
        knowledge_bases_info: list[dict],
        login_user: UserPayload,
        max_token: int,
        citation_collector: CitationRegistryCollector,
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

    kb_id_whitelist = [str(kb['id']) for kb in knowledge_bases_info]
    # Space-type KBs skip auth check in queryChunksFromDB; org-type go
    # through KnowledgeDao.ajudge_knowledge_permission. Preserve the
    # distinction the caller captured in `source` so a single LLM-chosen
    # subset still routes each id through the correct path.
    space_id_set: set[int] = {
        int(kb['id']) for kb in knowledge_bases_info
        if kb.get('source') == 'space'
    }
    # kb_id (str) → display name. Used by _format_chunk to embed the source KB
    # name on every chunk, so the frontend can group/dedupe by KB instead of
    # surfacing one chip per file.
    kb_name_by_id: dict[str, str] = {
        str(kb['id']): (kb.get('name') or '') for kb in knowledge_bases_info
    }
    desc_lines = []
    for kb in knowledge_bases_info:
        tags = kb.get('tags') or []
        tag_hint = f" tags={tags}" if tags else ''
        desc_lines.append(
            f"  - id={kb.get('id')} name={kb.get('name', '')}"
            f" desc={kb.get('description', '') or ''}{tag_hint}"
        )
    description = (
            'Search content in the user-selected knowledge bases. Supports querying '
            'one or more of the available knowledge bases, with optional per-KB tag '
            'filtering (tag_match_mode=ANY|ALL). Call this tool when the user '
            'question can be answered by information in these knowledge bases.\n'
            'Available knowledge bases (with file-level tags you may filter by):\n'
            + '\n'.join(desc_lines)
    )

    class _KbFilter(PydanticBaseModel):
        knowledge_base_id: str = PydanticField(
            description='Which KB this filter applies to. Must appear in knowledge_base_ids.',
        )
        tags: list[str] = PydanticField(
            description='Tag names to filter files inside this KB.',
        )
        tag_match_mode: str = PydanticField(
            default='ANY',
            description='ANY: match any tag; ALL: must carry every tag.',
        )

    class _Filters(PydanticBaseModel):
        knowledge_base_filters: list[_KbFilter] | None = PydanticField(
            default=None,
            description='Per-KB tag filters.',
        )

    class _SearchKbArgs(PydanticBaseModel):
        knowledge_base_ids: list[str] = PydanticField(
            default_factory=lambda: list(kb_id_whitelist),
            description=(
                'Subset of knowledge base IDs (as strings) to search; defaults '
                'to all available. Must be a subset of the advertised IDs.'
            ),
        )
        query: str = PydanticField(
            description='Search query in natural language — typically derived from the user question.',
        )
        filters: _Filters | None = PydanticField(
            default=None,
            description='Optional search filters (per-KB tag filters).',
        )

    def _format_chunk(doc) -> str:
        meta = getattr(doc, 'metadata', {}) or {}
        doc_id = meta.get('document_id') or ''
        chunk_idx = meta.get('chunk_index', '')
        chunk_id = (
                meta.get('chunk_id')
                or (f'{doc_id}-{chunk_idx}' if doc_id != '' else str(chunk_idx))
        )
        file_title = (
                meta.get('document_name')
                or meta.get('source')
                or meta.get('file_name')
                or ''
        )
        file_abstract = meta.get('file_abstract') or meta.get('abstract') or ''
        content = (getattr(doc, 'page_content', '') or '').strip()
        kb_id_raw = meta.get('knowledge_id') or meta.get('kb_id') or ''
        kb_id = str(kb_id_raw) if kb_id_raw not in (None, '') else ''
        kb_name = kb_name_by_id.get(kb_id, '')
        return (
            '{'
            f'<knowledge_base_id>{kb_id}</knowledge_base_id>\n'
            f'<knowledge_base_name>{kb_name}</knowledge_base_name>\n'
            f'<chunk_id>{chunk_id}</chunk_id>\n'
            f'<file_title>{file_title}</file_title>\n'
            f'<file_abstract>{file_abstract}</file_abstract>\n'
            f'<paragraph_content>{content}</paragraph_content>'
            '}'
        )

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
            from bisheng.database.models.tag import TagDao
            from bisheng.database.models.group_resource import ResourceTypeEnum
            from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        except Exception as exc:
            logger.warning(f'[search_kb] tag-filter unavailable: {exc}')
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

            tag_rows = await TagDao.get_tags_by_business(
                business_type=None,  # type: ignore[arg-type]
                business_id=str(kb_id),
            ) if False else []
            # Above helper is business-keyed; for file-level tags we query by
            # name against all tags and intersect with the KB's file set.
            try:
                files = await KnowledgeFileDao.aget_file_by_filters(
                    knowledge_id=kb_id, page=1, page_size=10000,
                )
            except Exception:
                files = []
            kb_file_ids = [str(fl.id) for fl in files]
            if not kb_file_ids:
                allowed[kb_id] = set()
                continue
            tag_map = TagDao.get_tags_by_resource(
                ResourceTypeEnum.SPACE_FILE, kb_file_ids,
            )
            wanted = set(tag_names)
            mode = (f.tag_match_mode or 'ANY').upper()
            matching: set[int] = set()
            for fid, tags in tag_map.items():
                names = {t.name for t in tags if t.name}
                if mode == 'ALL':
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
            filters: _Filters | None = None,
    ) -> str:
        from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam

        logger.info(
            f'[search_kb] invoke user={login_user.user_id}'
            f' kb_ids={knowledge_base_ids} query={query!r}'
            f' filters={filters.model_dump() if filters else None}'
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
            logger.info(
                f'[search_kb] hallucinated kb_ids; falling back to whitelist={kb_ids_int}'
            )

        # Resolve tag filters into {kb_id: allowed_file_ids}. Applied as a
        # post-retrieval filter on the docs returned by queryChunksFromDB so
        # we don't have to plumb file-id filters into the milvus/es layer.
        try:
            file_filter = await _resolve_tag_filter_file_ids(
                (filters.knowledge_base_filters if filters else None) or [],
            )
        except Exception as exc:
            logger.warning(f'[search_kb] tag resolution failed: {exc}')
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
                ),
                max_token=max_token,
                login_user=login_user,
            )
        except Exception as exc:
            logger.exception(f'[search_kb] queryChunksFromDB failed: {exc}')
            return json.dumps([], ensure_ascii=False)

        docs = list(finally_docs or [])
        if file_filter:
            def _doc_allowed(doc) -> bool:
                meta = getattr(doc, 'metadata', {}) or {}
                try:
                    kb_id = int(meta.get('knowledge_id') or meta.get('kb_id') or 0)
                    file_id = int(meta.get('document_id') or meta.get('file_id') or 0)
                except (TypeError, ValueError):
                    return True
                if kb_id not in file_filter:
                    return True  # no filter set for this KB
                return file_id in file_filter[kb_id]

            pre = len(docs)
            docs = [d for d in docs if _doc_allowed(d)]
            logger.info(
                f'[search_kb] tag-filter applied docs={pre}->{len(docs)}'
                f' allow_map={{kb: [n_files]}}='
                f'{ {k: len(v) for k, v in file_filter.items()} }'
            )

        docs = annotate_rag_documents_with_citations(docs)
        citation_items = collect_rag_citation_registry_items(docs)
        await cache_citation_registry_items(citation_items)
        citation_collector.extend(citation_items)
        results = [_format_chunk(doc) for doc in docs]

        # Surface per-KB failures as synthetic chunks carrying
        # <retrieval_error>. The frontend detects these and renders the KB
        # chip in an error state with the error message, so users see which
        # KB failed and why instead of the tool silently dropping them.
        for f in failures or []:
            kb_name = f.get('name') or ''
            if not kb_name:
                # fall back to the name we resolved earlier
                kb_name = kb_name_by_id.get(str(f.get('id', '')), '')
            err_text = str(f.get('error') or '').replace('</retrieval_error>', '')
            results.append(
                '{'
                f'<knowledge_base_id>{f.get("id", "")}</knowledge_base_id>\n'
                f'<knowledge_base_name>{kb_name}</knowledge_base_name>\n'
                f'<retrieval_error>{err_text}</retrieval_error>'
                '}'
            )

        logger.info(
            f'[search_kb] returning {len(results)} chunks'
            f' (ok={len(results) - len(failures or [])} failed={len(failures or [])})'
            f' total_chars={sum(len(r) for r in results)}'
        )
        return json.dumps(results, ensure_ascii=False)

    return StructuredTool.from_function(
        func=None,
        coroutine=_search,
        name='search_knowledge_bases',
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
        logger.warning(f'Failed to load Knowledge rows for {ids}: {exc}')
        return []

    # Best-effort aggregation of file-level tags per KB. A KB with many files
    # can have a large tag set; we cap the total tags advertised per KB at 50
    # to avoid prompt bloat.
    tags_by_kb: dict[int, list[str]] = {}
    try:
        from bisheng.database.models.tag import TagDao
        from bisheng.database.models.group_resource import ResourceTypeEnum
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        for kb in kbs:
            try:
                files = await KnowledgeFileDao.aget_file_by_filters(
                    knowledge_id=kb.id, page=1, page_size=500,
                )
            except Exception:
                files = []
            file_ids = [str(f.id) for f in files] if files else []
            if not file_ids:
                tags_by_kb[kb.id] = []
                continue
            try:
                tag_map = TagDao.get_tags_by_resource(ResourceTypeEnum.SPACE_FILE, file_ids)
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
                logger.warning(f'Failed to aggregate tags for kb={kb.id}: {exc}')
                tags_by_kb[kb.id] = []
    except Exception as exc:
        logger.warning(f'Tag aggregation unavailable: {exc}')

    resolved = [
        {
            'id': kb.id,
            'name': kb.name,
            'description': kb.description or '',
            'tags': tags_by_kb.get(kb.id, []),
            'source': 'space' if kb.id in space_id_set else 'organization',
        }
        for kb in kbs
    ]
    logger.info(
        f'[resolve_user_kb] resolved {len(resolved)} kbs'
        f' ids={[kb["id"] for kb in resolved]}'
        f' tag_counts={[len(kb["tags"]) for kb in resolved]}'
    )
    return resolved


async def _prepare_tools(
        tool_payloads: list[dict] | None,
        login_user: UserPayload,
        ws_config,  # WorkstationConfig; kept untyped to avoid circular import cost
        citation_collector: CitationRegistryCollector,
        knowledge_bases_info: list[dict] | None = None,
) -> tuple[list[BaseTool], list[dict]]:
    """Assemble the BaseTool list passed to LangGraph create_react_agent.

    `tool_payloads` items come from the frontend request; each payload has
    at least {id: int, tool_key: str, type: 'tool'|'knowledge'}.  Only
    entries with type=='tool' are materialised here; knowledge base is
    handled exclusively through the `search_knowledge_bases` tool built
    from `knowledge_bases_info`.
    """
    tools: list[BaseTool] = []
    # Failures surfaced to caller so the agent can emit synthetic tool_call
    # events and let the user see why a tool they selected didn't run.
    failures: list[dict] = []

    for tp in tool_payloads or []:
        tool_type = (tp.get('type') if isinstance(tp, dict) else getattr(tp, 'type', None)) or 'tool'
        if tool_type != 'tool':
            continue
        tool_key = tp.get('tool_key') if isinstance(tp, dict) else getattr(tp, 'tool_key', None)
        tool_id = tp.get('id') if isinstance(tp, dict) else getattr(tp, 'id', None)

        t = None
        err: str | None = None
        if tool_key == 'web_search':
            t, err = await _build_web_search_tool(login_user.user_id)
        elif tool_id:
            try:
                t = await ToolExecutor.init_by_tool_id(
                    tool_id=int(tool_id),
                    app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                    app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                    app_type=ApplicationTypeEnum.DAILY_CHAT,
                    user_id=login_user.user_id,
                )
            except Exception as exc:
                err = str(exc)
                logger.warning(f'Failed to initialise tool id={tool_id} key={tool_key}: {err}')

        if t is not None:
            tools.append(_wrap_daily_chat_citation_tool(t, citation_collector))
        elif err:
            failures.append({
                'tool_key': tool_key or str(tool_id or ''),
                'tool_type': 'web' if tool_key == 'web_search' else 'tool',
                # display_name is resolved on the frontend via i18n — just
                # advertise the raw tool_key so the client can map it.
                'display_name': tool_key or '',
                'error': err,
            })

    if knowledge_bases_info:
        kb_tool = await _build_knowledge_search_tool(
            knowledge_bases_info=knowledge_bases_info,
            login_user=login_user,
            max_token=getattr(ws_config, 'maxTokens', 15000) or 15000,
            citation_collector=citation_collector,
        )
        if kb_tool is not None:
            tools.append(kb_tool)

    return tools, failures


async def log_telemetry_events(user_id: str, conversation_id: str, start_time: float):
    """Log application alive and duration telemetry."""
    end_time = time.time()
    duration_ms = int((end_time - start_time) * 1000)
    common_data = {
        'app_id': ApplicationTypeEnum.DAILY_CHAT.value,
        'app_name': ApplicationTypeEnum.DAILY_CHAT.value,
        'app_type': ApplicationTypeEnum.DAILY_CHAT,
        'chat_id': conversation_id,
        'start_time': int(start_time),
        'end_time': int(end_time),
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

async def _agent_initialize_chat(data: APIChatCompletion, login_user: UserPayload):
    """Agent-mode init: creates/fetches the conversation and inserts the user's
    question row in the NEW JSON format (`{"query": str, "files": [...]}`)
    under category='question', type='over'.

    Differences vs legacy initialize_chat:
      - `message` column is JSON (not plain text)
      - `type` is 'over' (aligned with ChatResponse semantics in workflow)
      - `extra` is '{}' (no parentMessageId — new data is linear, no tree)
      - `overrideParentMessageId` is ignored (regenerate UI removed)
    """
    ws_config = await WorkStationService.aget_config()
    model_info = next((m for m in ws_config.models if m.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")

    conversation_id = data.conversationId
    is_new_conversation = False
    if not conversation_id:
        is_new_conversation = True
        conversation_id = uuid4().hex
        await MessageSessionDao.async_insert_one(
            MessageSession(
                chat_id=conversation_id,
                name='New Chat',
                flow_type=FlowType.WORKSTATION.value,
                user_id=login_user.user_id,
            )
        )
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversation_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source='platform',
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT,
            ),
        )

    conversation = await MessageSessionDao.async_get_one(conversation_id)
    if conversation is None:
        raise ConversationNotFoundError()
    if not is_new_conversation:
        await MessageSessionDao.touch_session(conversation_id)
        conversation = await MessageSessionDao.async_get_one(conversation_id)

    # Always insert a brand-new question row — Agent flow has no regenerate.
    message = await ChatMessageDao.ainsert_one(
        ChatMessage(
            user_id=login_user.user_id,
            chat_id=conversation_id,
            flow_id='',
            type='over',
            is_bot=False,
            sender='User',
            files=json.dumps(data.files) if data.files else None,
            extra='{}',
            message=json.dumps(
                {'query': data.text or '', 'files': data.files or []},
                ensure_ascii=False,
            ),
            category='question',
            source=0,
        )
    )

    bisheng_llm = await LLMService.get_bisheng_llm(
        model_id=data.model,
        app_id=ApplicationTypeEnum.DAILY_CHAT.value,
        app_name=ApplicationTypeEnum.DAILY_CHAT.value,
        app_type=ApplicationTypeEnum.DAILY_CHAT,
        user_id=login_user.user_id,
    )
    return ws_config, conversation, message, bisheng_llm, model_info, is_new_conversation


async def _process_agent_files(data: APIChatCompletion, model_info, login_user, ws_config):
    """Split uploaded files into visual (image base64 data URLs) and doc
    (extracted text chunks concatenated up to maxTokens)."""
    if not data.files:
        return '', []
    # Skip entries without a filepath (upload in flight / failed uploads still
    # sometimes reach us). Prevents `NoneType.split` inside async_file_download.
    valid_files = [f for f in data.files if f and f.get('filepath')]
    if not valid_files:
        logger.info(
            f'[process_agent_files] no files with filepath (received={len(data.files)})'
        )
        return '', []
    download_tasks = [async_file_download(f.get('filepath')) for f in valid_files]
    downloaded_files = await asyncio.gather(*download_tasks)

    visual_tasks, doc_tasks = [], []
    for filepath, filename in downloaded_files:
        ext = filename.split('.')[-1].lower()
        if model_info.visual and ext in VISUAL_MODEL_FILE_TYPES:
            visual_tasks.append(read_image_as_data_url(filepath=filepath, filename=filename))
        else:
            doc_tasks.append(
                get_file_content(
                    filepath_local=filepath,
                    file_name=filename,
                    invoke_user_id=login_user.user_id,
                )
            )
    visual_results, doc_results = await asyncio.gather(
        asyncio.gather(*visual_tasks),
        asyncio.gather(*doc_tasks),
    )
    max_token = getattr(ws_config, 'maxTokens', 15000) or 15000
    file_context = '\n'.join(doc_results)[:max_token]
    logger.info(
        f'[process_agent_files] docs={len(doc_results)} visuals={len(visual_results)}'
        f' file_context_len={len(file_context)} max_token={max_token}'
    )
    return file_context, list(visual_results)


async def _agent_stream_chat_completion(
        request: Request, data: APIChatCompletion, login_user: UserPayload,
):
    """v2.5 LangGraph ReAct Agent chat completion.

    Flow:
      1. init conversation + insert question row (JSON format)
      2. resolve selected knowledge bases → KB metadata list
      3. prepare LangChain tools (user-selected + search_knowledge_bases)
      4. process uploaded files (images → data URLs; docs → text context)
      5. compose user prompt (3 scenarios via _build_user_content)
      6. If tools non-empty → create_react_agent + astream_events v2
         Else → direct bisheng_llm.astream (still in new SSE format)
      7. Stream events mapped to SSE ChatResponse categories:
           on_chat_model_stream → agent_thinking/stream + agent_answer/stream
           on_tool_start        → agent_tool_call/start
           on_tool_end          → agent_tool_call/end
      8. Persist agent_answer row as {msg, events[]} where events is a single
         ordered log of {type: thinking|tool_call, ...} entries in arrival
         order. Frontend renders this array directly.
    """
    start_time = time.time()
    try:
        ws_config, conversation, message, bisheng_llm, model_info, is_new_conv = \
            await _agent_initialize_chat(data, login_user)
        conversation_id = conversation.chat_id
    except (BaseErrorCode, ValueError) as exc:
        error_response = exc if isinstance(exc, BaseErrorCode) else ServerError(message=str(exc))
        return StreamingResponse(
            iter([error_response.to_sse_event_instance_str()]),
            media_type='text/event-stream',
        )
    except Exception as exc:
        logger.exception(f'Error in agent chat completions setup: {exc}')
        return StreamingResponse(
            iter([ServerError(exception=exc).to_sse_event_instance_str()]),
            media_type='text/event-stream',
        )

    async def event_stream():
        # Single ordered event log — one entry per thinking segment or tool
        # call, in arrival order. The frontend renders this array directly;
        # parallel arrays + `segment_idx`/`after_segment` cross-references
        # are gone.
        #
        # Event shapes:
        #   {'type': 'thinking', 'content': str, 'duration_ms'?: int}
        #   {'type': 'tool_call', 'tool_call_id': str, 'tool_name': str,
        #    'display_name': str, 'tool_type': str, 'args': dict,
        #    'results'?: Any, 'error'?: str | None}
        events: list[dict] = []
        final_msg = ''
        # Pointer to the currently-open thinking event (None when the model is
        # emitting answer text or running a tool). Used to stream deltas and
        # finalise `duration_ms` without scanning `events`.
        current_thinking_idx: int | None = None
        current_thinking_start: float | None = None
        # Maps tool_call_id → its index in `events`, so on_tool_end can update
        # in O(1).
        inflight_tool_idx: dict[str, int] = {}
        error_flag = False
        error_msg = ''
        citation_collector = CitationRegistryCollector()

        def close_thinking() -> int | None:
            """Finalise the open thinking event (if any). Returns its duration
            in ms, or None when no segment was open. Caller yields the SSE."""
            nonlocal current_thinking_idx, current_thinking_start
            if current_thinking_idx is None:
                return None
            duration_ms = int((time.time() - (current_thinking_start or 0)) * 1000)
            events[current_thinking_idx]['duration_ms'] = duration_ms
            current_thinking_idx = None
            current_thinking_start = None
            return duration_ms

        # Emit first so the client can add the sidebar placeholder before any
        # streaming content arrives. onCreated hook in useAiChat keys on this.
        yield user_message(message.id, conversation_id, 'User', data.text or '')
        yield _sse_resp('processing', 'begin', '', conversation_id)
        yield _sse_resp(
            'question', 'over',
            {'query': data.text or '', 'files': data.files or []},
            conversation_id, message_id=message.id, is_bot=False,
        )

        try:
            # ---- Step 1: resolve user-selected KBs ----
            knowledge_bases_info = await _resolve_user_kb_selection(data)

            # ---- Step 2: assemble LangChain tools ----
            tool_payloads = [t.model_dump() for t in (data.tools or [])]
            langchain_tools, tool_failures = await _prepare_tools(
                tool_payloads=tool_payloads,
                login_user=login_user,
                ws_config=ws_config,
                citation_collector=citation_collector,
                knowledge_bases_info=knowledge_bases_info,
            )

            # Surface init failures as synthetic tool_call events so the user
            # sees *something* (e.g. "联网搜索 失败：未配置服务商") rather than
            # the model silently hallucinating a citation.
            for f in tool_failures:
                tc_id = f'init_fail_{uuid4().hex[:10]}'
                start_payload = {
                    'tool_call_id': tc_id,
                    'tool_name': f['tool_key'],
                    'display_name': f['display_name'],
                    'tool_type': f['tool_type'],
                    'args': {},
                }
                yield _sse_resp('agent_tool_call', 'start', start_payload, conversation_id)
                end_payload = {**start_payload, 'results': [], 'error': f['error']}
                events.append({'type': 'tool_call', **end_payload})
                yield _sse_resp('agent_tool_call', 'end', end_payload, conversation_id)

            # ---- Step 3: process uploaded files ----
            file_context, image_bases64 = await _process_agent_files(
                data, model_info, login_user, ws_config,
            )

            # ---- Step 4: compose user content + history ----
            user_text = _build_user_content(
                question=data.text or '',
                file_context=file_context,
                knowledge_bases_info=knowledge_bases_info,
            )

            # Row-count ceiling just limits DB work; the real trimming
            # happens inside get_chat_history via the token cap
            # (daily_chat.history_max_tokens in config.yaml).
            history_max_tokens = await _get_history_max_tokens()
            history = (
                await WorkStationService.get_chat_history(
                    conversation_id,
                    size=10,
                    max_tokens=history_max_tokens,
                )
            )[:-1]

            if image_bases64:
                content_payload = [{'type': 'text', 'text': user_text}]
                for img in image_bases64:
                    content_payload.append({'type': 'image_url', 'image_url': {'url': img}})
            else:
                content_payload = user_text

            sys_prompt = None
            if ws_config.systemPrompt:
                # Use plain `replace` instead of `str.format` — admin prompts can
                # legitimately contain `{...}` JSON snippets (e.g. a tool-call
                # schema example) that would otherwise trip KeyError.
                sys_prompt = ws_config.systemPrompt.replace(
                    '{cur_date}',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                )
            if knowledge_bases_info or any(
                    isinstance(tool, DailyChatCitationToolWrapper)
                    for tool in langchain_tools
            ):
                sys_prompt = (
                    f'{sys_prompt}\n\n{DAILY_CHAT_CITATION_PROMPT_RULES}'
                    if sys_prompt
                    else DAILY_CHAT_CITATION_PROMPT_RULES
                )

            llm_messages = list(history) + [HumanMessage(content=content_payload)]

            logger.info(
                f'[agent_chat] prepared messages user={login_user.user_id}'
                f' history_len={len(history)} has_sys_prompt={bool(sys_prompt)}'
                f' tool_count={len(langchain_tools)}'
                f' tool_names={[t.name for t in langchain_tools]}'
                f' visual_count={len(image_bases64)}'
                f' kb_count={len(knowledge_bases_info or [])}'
            )

            # [debug] Dump the exact, UNTRUNCATED payload sent to the LLM to
            # /tmp/bisheng_agent_dumps/<trace>.json so the full system prompt
            # and message history can be inspected verbatim.
            #
            # Gated behind BISHENG_AGENT_DUMP env var — OFF by default so
            # there's no I/O overhead in production. To enable for debugging:
            #   export BISHENG_AGENT_DUMP=1   # then restart the backend
            # Accepted truthy values: 1, true, yes, on (case-insensitive).
            import os as _os
            if _os.environ.get('BISHENG_AGENT_DUMP', '').lower() in ('1', 'true', 'yes', 'on'):
                try:
                    from bisheng.core.logger import trace_id_var
                    trace_id = trace_id_var.get() or 'notrace'
                except Exception:
                    trace_id = 'notrace'

                def _serialize_message(m):
                    content = getattr(m, 'content', '')
                    if isinstance(content, list):
                        parts = []
                        for p in content:
                            if isinstance(p, dict) and p.get('type') == 'image_url':
                                parts.append({'type': 'image_url', 'image_url': '<base64 omitted>'})
                            else:
                                parts.append(p)
                        content_out = parts
                    else:
                        content_out = content
                    return {'role': type(m).__name__, 'content': content_out}

                dump_payload = {
                    'trace_id': trace_id,
                    'user_id': login_user.user_id,
                    'conversation_id': conversation_id,
                    'tool_count': len(langchain_tools),
                    'tool_names': [t.name for t in langchain_tools],
                    'kb_count': len(knowledge_bases_info or []),
                    'system_prompt': sys_prompt,
                    'messages': [_serialize_message(m) for m in llm_messages],
                }
                try:
                    _os.makedirs('/tmp/bisheng_agent_dumps', exist_ok=True)
                    dump_path = f'/tmp/bisheng_agent_dumps/{trace_id}.json'
                    with open(dump_path, 'w', encoding='utf-8') as fp:
                        json.dump(dump_payload, fp, ensure_ascii=False, indent=2, default=str)
                    logger.info(f'[agent_chat][dump] wrote full payload -> {dump_path}')
                except Exception as dump_exc:
                    logger.warning(f'[agent_chat][dump] failed: {dump_exc}')

            # ---- Step 5: execute ----
            if langchain_tools:
                from langgraph.prebuilt import create_react_agent
                from langchain_core.runnables import RunnableConfig

                agent = create_react_agent(
                    bisheng_llm,
                    langchain_tools,
                    prompt=sys_prompt,  # may be None
                )

                tool_meta_map = {t.name: _build_tool_meta(t) for t in langchain_tools}
                inflight: dict[str, dict] = {}
                max_iter = await _get_agent_max_iterations()

                async for ev in agent.astream_events(
                        {'messages': llm_messages},
                        version='v2',
                        config=RunnableConfig(recursion_limit=max_iter),
                ):
                    et = ev.get('event', '')
                    name = ev.get('name', '') or ''

                    if et == 'on_chat_model_stream':
                        chunk = (ev.get('data') or {}).get('chunk')
                        if chunk is None:
                            continue
                        text = getattr(chunk, 'content', '') or ''
                        reasoning = (getattr(chunk, 'additional_kwargs', None) or {}).get(
                            'reasoning_content', ''
                        )
                        if reasoning:
                            if current_thinking_idx is None:
                                events.append({'type': 'thinking', 'content': ''})
                                current_thinking_idx = len(events) - 1
                                current_thinking_start = time.time()
                            events[current_thinking_idx]['content'] += reasoning
                            yield _sse_resp(
                                'agent_thinking', 'stream',
                                {'content': reasoning},
                                conversation_id,
                            )
                        if text:
                            d = close_thinking()
                            if d is not None:
                                yield _sse_resp(
                                    'agent_thinking', 'end',
                                    {'duration_ms': d},
                                    conversation_id,
                                )
                            final_msg += text
                            yield _sse_resp(
                                'agent_answer', 'stream', {'msg': text}, conversation_id,
                            )

                    elif et == 'on_tool_start':
                        # Close any in-flight thinking before the tool call
                        # so each ReAct round gets its own collapsible block.
                        d = close_thinking()
                        if d is not None:
                            yield _sse_resp(
                                'agent_thinking', 'end',
                                {'duration_ms': d},
                                conversation_id,
                            )

                        tool_name = name
                        tc_id = str(ev.get('run_id') or f'call_{uuid4().hex[:12]}')
                        meta = tool_meta_map.get(tool_name, {
                            'display_name': tool_name, 'tool_type': 'tool',
                        })
                        tool_event = {
                            'type': 'tool_call',
                            'tool_call_id': tc_id,
                            'tool_name': tool_name,
                            'display_name': meta['display_name'],
                            'tool_type': meta['tool_type'],
                            'args': (ev.get('data') or {}).get('input', {}),
                        }
                        events.append(tool_event)
                        inflight_tool_idx[tc_id] = len(events) - 1
                        # SSE payload uses the bare tool_call shape (no type:).
                        yield _sse_resp(
                            'agent_tool_call', 'start',
                            {k: v for k, v in tool_event.items() if k != 'type'},
                            conversation_id,
                        )

                    elif et == 'on_tool_end':
                        tc_id = str(ev.get('run_id') or '')
                        idx = inflight_tool_idx.pop(tc_id, None)
                        raw_output = (ev.get('data') or {}).get('output')
                        if idx is not None:
                            tool_event = events[idx]
                            results = _parse_tool_results(raw_output, tool_event.get('tool_name'))
                            tool_event['results'] = results
                            tool_event['error'] = None
                            payload = {k: v for k, v in tool_event.items() if k != 'type'}
                        else:
                            # Edge case: tool_end without a matching start. Synthesise one.
                            results = _parse_tool_results(raw_output, name)
                            tool_event = {
                                'type': 'tool_call',
                                'tool_call_id': tc_id,
                                'tool_name': name,
                                'display_name': name,
                                'tool_type': 'tool',
                                'args': {},
                                'results': results,
                                'error': None,
                            }
                            events.append(tool_event)
                            payload = {k: v for k, v in tool_event.items() if k != 'type'}
                        yield _sse_resp('agent_tool_call', 'end', payload, conversation_id)
                    # other events (on_chain_start/on_chain_end/etc.) ignored
            else:
                # No tools → direct streaming still in new SSE format
                if sys_prompt:
                    llm_messages.insert(0, SystemMessage(content=sys_prompt))
                async for chunk in bisheng_llm.astream(llm_messages):
                    text = getattr(chunk, 'content', '') or ''
                    reasoning = (getattr(chunk, 'additional_kwargs', None) or {}).get(
                        'reasoning_content', ''
                    )
                    if reasoning:
                        if current_thinking_idx is None:
                            events.append({'type': 'thinking', 'content': ''})
                            current_thinking_idx = len(events) - 1
                            current_thinking_start = time.time()
                        events[current_thinking_idx]['content'] += reasoning
                        yield _sse_resp(
                            'agent_thinking', 'stream',
                            {'content': reasoning},
                            conversation_id,
                        )
                    if text:
                        d = close_thinking()
                        if d is not None:
                            yield _sse_resp(
                                'agent_thinking', 'end',
                                {'duration_ms': d},
                                conversation_id,
                            )
                        final_msg += text
                        yield _sse_resp(
                            'agent_answer', 'stream', {'msg': text}, conversation_id,
                        )
        except BaseErrorCode as exc:
            error_flag = True
            error_msg = str(exc)
            logger.exception('Agent chat BaseErrorCode')
            yield exc.to_sse_event_instance_str()
        except Exception as exc:
            error_flag = True
            error_msg = str(exc)
            logger.exception('Agent chat execution error')
            yield ServerError(exception=exc).to_sse_event_instance_str()

        # Finalise any dangling thinking event (e.g. stream interrupted mid-reasoning).
        close_thinking()

        # Persist agent_answer — new unified shape is `{msg, events}`.
        db_content: dict = {'msg': final_msg, 'events': events}

        resp_msg = await ChatMessageDao.ainsert_one(
            ChatMessage(
                user_id=conversation.user_id,
                chat_id=conversation_id,
                flow_id='',
                type='end',
                is_bot=True,
                message=json.dumps(db_content, ensure_ascii=False),
                category='agent_answer',
                sender=model_info.displayName,
                extra=json.dumps({'error': True, 'error_msg': error_msg}) if error_flag else '{}',
                source=0,
            )
        )
        citation_items = select_registry_items_for_persistence(
            citation_collector.list_items(),
            final_msg,
        )
        await save_message_citations(
            message_id=resp_msg.id,
            items=citation_items,
            chat_id=conversation_id,
            flow_id='',
        )

        yield _sse_resp(
            'agent_answer', 'end', db_content,
            conversation_id, message_id=resp_msg.id,
            citations=citation_items,
        )
        yield _sse_resp('processing', 'close', '', conversation_id)

        # Terminal `final` sentinel so the frontend SSE hook's onEnd() fires
        # reliably (it listens for `data.final != null`). Without this the send
        # button stays stuck in "stop" state until the TCP stream closes.
        final_payload = {
            'final': True,
            'conversation': {'conversationId': conversation_id},
            'responseMessage': {
                'messageId': resp_msg.id,
                'conversationId': conversation_id,
            },
        }
        yield f'data: {json.dumps(final_payload, ensure_ascii=False)}\n\n'

        if is_new_conv or (conversation.name in (None, '', 'New Chat')):
            asyncio.create_task(
                gen_title(data.text or '', final_msg, bisheng_llm, conversation_id, login_user, request)
            )
        await log_telemetry_events(str(login_user.user_id), conversation_id, start_time)

    return StreamingResponse(event_stream(), media_type='text/event-stream')


async def stream_chat_completion(
        request: Request, data: APIChatCompletion, login_user: UserPayload,
):
    """v2.5 unified entry — every workstation chat request goes through the
    LangGraph ReAct Agent flow. When `data.tools` is empty/None the agent
    falls back to a plain `bisheng_llm.astream` branch (same new SSE format),
    so callers don't need to opt in explicitly.
    """
    return await _agent_stream_chat_completion(request, data, login_user)
