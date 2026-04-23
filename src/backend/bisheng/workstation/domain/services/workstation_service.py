import json
from typing import Any, Optional

from fastapi import BackgroundTasks, Request
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam
from bisheng.api.v1.schemas import (
    KnowledgeFileOne,
    KnowledgeFileProcess,
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    ToolConfig,
    WorkstationConfig,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import EmbeddingModelStatusError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.common.services.base import BaseService
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.database.constants import MessageCategory
from bisheng.database.models.message import ChatMessageDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao


class WorkStationService(BaseService):

    @classmethod
    def update_config(
            cls,
            request: Request,
            login_user: UserPayload,
            data: WorkstationConfig,
    ) -> WorkstationConfig:
        """Update workstation default configuration."""
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        if config:
            config.value = data.model_dump_json()
        else:
            config = Config(key=ConfigKeyEnum.WORKSTATION.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    def sync_tool_info(cls, tools: list[dict]) -> list[dict]:
        """Synchronize tool metadata from persistent storage."""
        if not tools:
            return []
        tool_type_ids = [tool.get('id') for tool in tools]
        tool_type_info = GptsToolsDao.get_all_tool_type(tool_type_ids)
        exists_tool_type = {tool.id: tool for tool in tool_type_info}
        tool_info = GptsToolsDao.get_list_by_type(list(exists_tool_type.keys()))
        exists_tool_info = {tool.id: tool for tool in tool_info}
        new_tools = []
        for tool in tools:
            new_tool = exists_tool_type.get(tool.get('id'))
            if not new_tool:
                continue
            tool['name'] = new_tool.name
            tool['description'] = new_tool.description
            new_children = []
            for item in tool.get('children', []):
                child = exists_tool_info.get(item.get('id'))
                if not child:
                    continue
                item['name'] = child.name
                item['description'] = child.desc
                item['tool_key'] = child.tool_key
                new_children.append(item)
            tool['children'] = new_children
            new_tools.append(tool)
        return new_tools

    @classmethod
    def parse_config(cls, config: Any) -> Optional[WorkstationConfig]:
        if not config:
            return None
        raw = json.loads(config.value)

        # Rollout from beta1 flat-leaf shape -> hierarchical LinSight shape:
        # flat entries carry `tool_key`; group them under their parent type_id
        # so Pydantic can load them into the new schema without data loss.
        raw_tools = raw.get('tools')
        if isinstance(raw_tools, list) and any(isinstance(t, dict) and 'tool_key' in t for t in raw_tools):
            try:
                type_ids = list({t.get('type_id') for t in raw_tools if isinstance(t, dict) and t.get('type_id')})
                parents = {p.id: p for p in GptsToolsDao.get_all_tool_type(type_ids)} if type_ids else {}
                grouped: dict = {}
                order: list = []
                for t in raw_tools:
                    if not isinstance(t, dict):
                        continue
                    parent_id = t.get('type_id') or t.get('id')
                    if parent_id not in grouped:
                        parent = parents.get(parent_id)
                        grouped[parent_id] = {
                            'id': parent_id,
                            'name': parent.name if parent else t.get('name', ''),
                            'is_preset': parent.is_preset if parent else None,
                            'description': parent.description if parent else t.get('description'),
                            'default_checked': bool(t.get('default_checked')),
                            'children': [],
                        }
                        order.append(parent_id)
                    # Prefer default_checked=True if any legacy leaf had it on.
                    if t.get('default_checked'):
                        grouped[parent_id]['default_checked'] = True
                    grouped[parent_id]['children'].append({
                        'id': t.get('id'),
                        'name': t.get('name'),
                        'tool_key': t.get('tool_key'),
                        'desc': t.get('description') or t.get('desc'),
                    })
                raw['tools'] = [grouped[pid] for pid in order]
            except Exception:
                # Best-effort; fall through and let Pydantic drop unknown keys.
                pass

        ret = WorkstationConfig(**raw)

        # Platform default: the built-in web_search tool must always appear in
        # `tools`. Fresh configs (tools is None) get it auto-seeded with
        # default_checked=True. Legacy rollout migrates from webSearch.enabled:
        # if admin had explicitly turned it off, preserve that by seeding with
        # default_checked=False instead of silently flipping it back on.
        if ret.tools is None:
            try:
                web_search_db = GptsToolsDao.get_tool_by_tool_key('web_search')
                if web_search_db:
                    parent_types = GptsToolsDao.get_all_tool_type([web_search_db.type])
                    parent = parent_types[0] if parent_types else None
                    legacy_disabled = ret.webSearch is not None and not ret.webSearch.enabled
                    ret.tools = [ToolConfig(
                        id=web_search_db.type,
                        name=parent.name if parent else '联网搜索',
                        is_preset=parent.is_preset if parent else 1,
                        description=parent.description if parent else 'Search the internet for real-time information',
                        default_checked=not legacy_disabled,
                        children=[{
                            'id': web_search_db.id,
                            'name': web_search_db.name,
                            'tool_key': web_search_db.tool_key,
                            'desc': web_search_db.desc,
                        }],
                    )]
            except Exception:
                # Best-effort migration; absence of the tool shouldn't break config load.
                pass
        if ret.orgKbs is None:
            ret.orgKbs = []

        if ret.assistantIcon and ret.assistantIcon.relative_path:
            ret.assistantIcon.image = cls.get_logo_share_link(ret.assistantIcon.relative_path)
        if ret.sidebarIcon and ret.sidebarIcon.relative_path:
            ret.sidebarIcon.image = cls.get_logo_share_link(ret.sidebarIcon.relative_path)
        return ret

    @classmethod
    def get_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration."""
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        return cls.parse_config(config)

    @classmethod
    async def aget_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration asynchronously."""
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION)
        return cls.parse_config(config)

    @classmethod
    async def get_daily_chat_config(cls) -> WorkstationConfig | None:
        """Get the default workstation configuration for daily chat."""
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION)
        return cls.parse_config(config)

    @classmethod
    async def update_daily_chat_config(cls, data: WorkstationConfig) -> WorkstationConfig:
        """Update the default workstation configuration for daily chat."""
        await ConfigDao.insert_or_update_config(
            ConfigKeyEnum.WORKSTATION.value,
            value=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_linsight_config(cls) -> Optional[LinsightConfig]:
        """Get Linsight configuration."""
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION_LINSIGHT)
        if not config:
            return None
        ret = LinsightConfig(**json.loads(config.value))
        ret.tools = cls.sync_tool_info(ret.tools)
        return ret

    @classmethod
    async def update_linsight_config(cls, data: LinsightConfig) -> LinsightConfig:
        """Update Linsight configuration."""
        await ConfigDao.insert_or_update_config(
            ConfigKeyEnum.WORKSTATION_LINSIGHT.value,
            value=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_subscription_config(cls) -> Optional[SubscriptionConfig]:
        """Get subscription configuration."""
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION_SUBSCRIPTION)
        if not config:
            return None
        return SubscriptionConfig(**json.loads(config.value))

    @classmethod
    async def update_subscription_config(cls, data: SubscriptionConfig) -> SubscriptionConfig:
        """Update subscription configuration."""
        await ConfigDao.insert_or_update_config(
            ConfigKeyEnum.WORKSTATION_SUBSCRIPTION.value,
            value=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    async def get_knowledge_space_config(cls) -> Optional[KnowledgeSpaceConfig]:
        """Get knowledge space configuration."""
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE)
        if not config:
            return None
        return KnowledgeSpaceConfig(**json.loads(config.value))

    @classmethod
    async def update_knowledge_space_config(cls, data: KnowledgeSpaceConfig) -> KnowledgeSpaceConfig:
        """Update knowledge space configuration."""
        await ConfigDao.insert_or_update_config(
            ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE.value,
            value=json.dumps(data.model_dump(mode='json'), ensure_ascii=True),
        )
        return data

    @classmethod
    def uploadPersonalKnowledge(
            cls,
            request: Request,
            login_user: UserPayload,
            file_path,
            background_tasks: BackgroundTasks,
    ):
        knowledge = KnowledgeDao.get_user_knowledge(
            login_user.user_id,
            None,
            KnowledgeTypeEnum.PRIVATE,
        )
        if not knowledge:
            model = LLMService.get_knowledge_llm()
            knowledge_create = KnowledgeCreate(
                name='Personal Knowledge Base',
                type=KnowledgeTypeEnum.PRIVATE.value,
                user_id=login_user.user_id,
                model=model.embedding_model_id,
            )
            knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge_create)
        else:
            knowledge = knowledge[0]
        req_data = KnowledgeFileProcess(
            knowledge_id=knowledge.id,
            file_list=[KnowledgeFileOne(file_path=file_path)],
        )
        try:
            _ = LLMService.get_bisheng_knowledge_embedding(login_user.user_id, int(knowledge.model))
        except Exception as exc:
            raise EmbeddingModelStatusError(exception=exc)
        return KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)

    @classmethod
    def queryKnowledgeList(
            cls,
            request: Request,
            login_user: UserPayload,
            page: int,
            size: int,
    ):
        knowledge = KnowledgeDao.get_user_knowledge(
            login_user.user_id,
            None,
            KnowledgeTypeEnum.PRIVATE,
        )
        if not knowledge:
            return [], 0
        res, total, _ = KnowledgeService.get_knowledge_files(
            request,
            login_user,
            knowledge[0].id,
            page=page,
            page_size=size,
        )
        return res, total

    @classmethod
    async def queryChunksFromDB(
        cls,
        question: str,
        use_knowledge_param: UseKnowledgeBaseParam,
        max_token: int,
        login_user: UserPayload,
    ) -> tuple[list[str], Optional[list[dict]], list[dict]]:
        """Query relevant knowledge blocks from the database.

        Returns (formatted_results, finally_docs, failures) where `failures`
        is a list of per-KB error descriptors:
            {'id': int, 'name': str, 'error': str}
        Caller (search_knowledge_bases) surfaces these to the UI as failed
        KB chips with the error message.
        """
        failures: list[dict] = []
        try:
            knowledge_ids = []
            if use_knowledge_param.organization_knowledge_ids:
                knowledge_ids.extend(use_knowledge_param.organization_knowledge_ids)

            knowledge_vector_list = await KnowledgeRag.get_multi_knowledge_vectorstore(
                invoke_user_id=login_user.user_id,
                knowledge_ids=knowledge_ids,
                user_name=login_user.user_name,
            )
            knowledge_space_list = await KnowledgeRag.get_multi_knowledge_vectorstore(
                invoke_user_id=login_user.user_id,
                knowledge_ids=use_knowledge_param.knowledge_space_ids,
                check_auth=False,
            )
            knowledge_vector_list.update(knowledge_space_list)

            # Per-KB failure isolation — a single KB whose embedding model is
            # broken (e.g. expired Volcengine key → 403) must not poison the
            # whole batch. Run each KB's retriever independently; record
            # failures so the caller can render them in the UI as failed KB
            # chips instead of silently dropping them.
            finally_docs: list = []
            kb_succeed: list = []
            max_total_docs = 100  # parity with old MultiRetriever finally_k

            for kb_id, vectorstore_info in knowledge_vector_list.items():
                if len(finally_docs) >= max_total_docs:
                    break
                milvus_vectorstore = vectorstore_info.get('milvus')
                es_vectorstore = vectorstore_info.get('es')
                kb_row = vectorstore_info.get('knowledge')
                kb_name = getattr(kb_row, 'name', '') or ''
                if milvus_vectorstore is None and es_vectorstore is None:
                    logger.info(
                        f'[queryChunksFromDB] kb={kb_id} no vectorstore, skip'
                    )
                    failures.append({
                        'id': int(kb_id) if isinstance(kb_id, (int, str)) and str(kb_id).isdigit() else kb_id,
                        'name': kb_name,
                        'error': '知识库未初始化向量存储',
                    })
                    continue

                try:
                    per_kb_milvus = (
                        MultiRetriever(
                            vectors=[milvus_vectorstore],
                            search_kwargs=[{'k': 100, 'param': {'ef': 110}}],
                            finally_k=100,
                        )
                        if milvus_vectorstore is not None else None
                    )
                    per_kb_es = (
                        MultiRetriever(
                            vectors=[es_vectorstore],
                            search_kwargs=[{'k': 100}],
                            finally_k=100,
                        )
                        if es_vectorstore is not None else None
                    )
                    per_kb_tool = KnowledgeRetrieverTool(
                        vector_retriever=per_kb_milvus,
                        elastic_retriever=per_kb_es,
                        max_content=max_token,
                        rrf_remove_zero_score=True,
                        sort_by_source_and_index=True,
                    )
                    kb_docs = await per_kb_tool.ainvoke({'query': question})
                    docs_count = len(kb_docs) if kb_docs else 0
                    if kb_docs:
                        finally_docs.extend(kb_docs)
                    kb_succeed.append(kb_id)
                    logger.info(
                        f'[queryChunksFromDB] kb={kb_id} ok docs={docs_count}'
                    )
                except Exception as exc:
                    err_msg = str(exc) or exc.__class__.__name__
                    failures.append({
                        'id': int(kb_id) if isinstance(kb_id, (int, str)) and str(kb_id).isdigit() else kb_id,
                        'name': kb_name,
                        'error': err_msg,
                    })
                    logger.warning(
                        f'[queryChunksFromDB] kb={kb_id} failed: {err_msg}'
                    )
                    continue

            if failures:
                logger.warning(
                    f'[queryChunksFromDB] partial failure:'
                    f' succeed={kb_succeed}'
                    f' failed={[f["id"] for f in failures]}'
                )

            if not finally_docs:
                return [], [], failures

            # Cap to match old MultiRetriever finally_k=100 ceiling.
            if len(finally_docs) > max_total_docs:
                finally_docs = finally_docs[:max_total_docs]

            formatted_results = []
            for doc in finally_docs:
                file_name = doc.metadata.get('source') or doc.metadata.get('document_name')
                content = doc.page_content.strip()
                formatted_results.append(
                    f'[file name]:{file_name}\n[file content begin]\n{content}\n[file content end]\n'
                )
            return formatted_results, finally_docs, failures
        except Exception as exc:
            logger.exception(f'queryChunksFromDB error: {exc}')
            return [], None, failures

    @classmethod
    async def get_chat_history(cls, chat_id: str, size: int = 4,
                               max_tokens: Optional[int] = None):
        """Build LLM-consumable chat history, backward compatible with both
        legacy plain-text messages and v2.5 JSON-formatted messages.

        Two-stage trimming:
          1. DB returns the MOST RECENT ``size`` rows in chronological order
             (see aget_messages_by_chat_id — fixed to DESC LIMIT + reverse).
          2. If the combined token count exceeds ``max_tokens``, drop oldest
             entries one at a time until the remainder fits. Token counting
             uses tiktoken (cl100k_base) with a char-based fallback — see
             chat_service._count_tokens. We always drop from the FRONT
             (oldest) of the list so the latest user/AI turn is preserved.

        ``max_tokens`` is resolved by the caller (typically from
        ``daily_chat.history_max_tokens`` in the DB config). If ``None`` the
        token-cap stage is skipped — keep this for callers that only want
        row-count trimming or that manage budgeting themselves.
        """
        import re as _re

        chat_history = []
        categories = [
            MessageCategory.QUESTION.value,
            MessageCategory.ANSWER.value,
            MessageCategory.AGENT_ANSWER.value,
        ]
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, categories, size)

        for one in messages:
            raw = one.message or ''
            if one.category == MessageCategory.QUESTION.value:
                # Try new JSON format: {"query": "..."}
                try:
                    parsed = json.loads(raw)
                    content = parsed.get('query', raw) if isinstance(parsed, dict) else raw
                except (json.JSONDecodeError, TypeError):
                    content = raw
                # Legacy rows may carry a rewritten prompt in `extra.prompt`.
                try:
                    extra = json.loads(one.extra) if one.extra else {}
                    if isinstance(extra, dict) and extra.get('prompt'):
                        content = extra['prompt']
                except (json.JSONDecodeError, TypeError):
                    pass
                chat_history.append(HumanMessage(content=content))

            elif one.category == MessageCategory.AGENT_ANSWER.value:
                # New JSON format: {"msg":"...", ...}
                try:
                    parsed = json.loads(raw)
                    content = parsed.get('msg', '') if isinstance(parsed, dict) else raw
                except (json.JSONDecodeError, TypeError):
                    content = raw
                chat_history.append(AIMessage(content=content))

            elif one.category == MessageCategory.ANSWER.value:
                # Legacy plain-text: strip :::thinking / :::web markup so the
                # model sees only the visible answer.
                content = _re.sub(r':::thinking\n[\s\S]*?\n:::', '', raw)
                content = _re.sub(r':::web\n[\s\S]*?\n:::', '', content).strip()
                chat_history.append(AIMessage(content=content))

        # Token-count cap: drop oldest until total tokens ≤ max_tokens.
        # Keep at least one message (the most recent) so the model still
        # sees some context; if that single message alone exceeds the cap,
        # leave it untouched — the LLM layer will raise, which is more
        # actionable than silently chopping the latest turn.
        if max_tokens is not None and max_tokens > 0 and chat_history:
            from .chat_service import _count_tokens  # local import avoids cycle

            def _msg_tokens(m) -> int:
                c = getattr(m, 'content', '')
                if isinstance(c, str):
                    return _count_tokens(c)
                try:
                    return _count_tokens(str(c))
                except Exception:
                    return 0

            per_msg = [_msg_tokens(m) for m in chat_history]
            total = sum(per_msg)
            dropped = 0
            while total > max_tokens and len(chat_history) > 1:
                chat_history.pop(0)
                total -= per_msg.pop(0)
                dropped += 1
            if dropped:
                logger.info(
                    f'history token-cap trimmed {dropped} oldest messages '
                    f'(final_tokens={total} cap={max_tokens})'
                )

        logger.info(f'loaded {len(chat_history)} chat history for chat_id {chat_id}')
        return chat_history
