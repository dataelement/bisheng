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
    WorkstationConfig,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import EmbeddingModelStatusError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.common.services.base import BaseService
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
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
        ret = WorkstationConfig(**json.loads(config.value))
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
    ) -> tuple[list[Any], None, list[CitationRegistryItemSchema]] | tuple[list[Any], Any, list[CitationRegistryItemSchema]]:
        """Query relevant knowledge blocks from the database."""
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

            all_milvus, all_milvus_filter = [], []
            all_es, all_es_filter = [], []
            multi_milvus_retriever, multi_es_retriever = None, None
            for _, vectorstore_info in knowledge_vector_list.items():
                milvus_vectorstore = vectorstore_info.get('milvus')
                es_vectorstore = vectorstore_info.get('es')
                all_milvus.append(milvus_vectorstore)
                all_milvus_filter.append({'k': 100, 'param': {'ef': 110}})
                all_es.append(es_vectorstore)
                all_es_filter.append({'k': 100})
            if all_milvus:
                multi_milvus_retriever = MultiRetriever(
                    vectors=all_milvus,
                    search_kwargs=all_milvus_filter,
                    finally_k=100,
                )
            if all_es:
                multi_es_retriever = MultiRetriever(
                    vectors=all_es,
                    search_kwargs=all_es_filter,
                    finally_k=100,
                )
            knowledge_retriever_tool = KnowledgeRetrieverTool(
                vector_retriever=multi_milvus_retriever,
                elastic_retriever=multi_es_retriever,
                max_content=max_token,
                rrf_remove_zero_score=True,
                sort_by_source_and_index=True,
            )

            finally_docs = await knowledge_retriever_tool.ainvoke({'query': question})
            if not finally_docs:
                return [], [], []

            prompt_context = ''
            if not prompt_context:
                formatted_results = []
                for doc in finally_docs:
                    file_name = doc.metadata.get('source') or doc.metadata.get('document_name')
                    content = doc.page_content.strip()
                    formatted_results.append(
                        f'[file name]:{file_name}\n[file content begin]\n{content}\n[file content end]\n'
                    )
                return formatted_results, finally_docs, []

            return [prompt_context], finally_docs, []
        except Exception as exc:
            logger.exception(f'queryChunksFromDB error: {exc}')
            return [], None, []

    @classmethod
    async def get_chat_history(cls, chat_id: str, size: int = 4):
        chat_history = []
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, ['question', 'answer'], size)
        for one in messages:
            content = one.message
            if one.category == MessageCategory.QUESTION.value:
                chat_history.append(HumanMessage(content=content))
            elif one.category == MessageCategory.ANSWER.value:
                chat_history.append(AIMessage(content=content))
        logger.info(f'loaded {len(chat_history)} chat history for chat_id {chat_id}')
        return chat_history
