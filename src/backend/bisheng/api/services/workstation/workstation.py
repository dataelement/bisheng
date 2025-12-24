import asyncio
import json
from datetime import datetime
from typing import Optional, Any

from fastapi import BackgroundTasks, Request
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from openai import BaseModel
from pydantic import field_validator

from bisheng.api.services.base import BaseService
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, WorkstationConfig
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.server import EmbeddingModelStatusError
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.database.constants import MessageCategory
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.llm.domain.services import LLMService
from bisheng.tool.domain.langchain.knowledge import KnowledgeRetrieverTool
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.user.domain.models.user import UserDao


class WorkStationService(BaseService):

    @classmethod
    def update_config(cls, request: Request, login_user: UserPayload, data: WorkstationConfig) \
            -> WorkstationConfig:
        """ 更新workflow的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        if config:
            config.value = data.model_dump_json()
        else:
            config = Config(key=ConfigKeyEnum.WORKSTATION.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)

        return data

    @classmethod
    def sync_tool_info(cls, tools: list[dict]) -> list[dict]:
        """ 同步工具信息 """
        if not tools:
            return []
        tool_type_ids = [t.get("id") for t in tools]
        tool_type_info = GptsToolsDao.get_all_tool_type(tool_type_ids)
        exists_tool_type = {t.id: t for t in tool_type_info}
        tool_info = GptsToolsDao.get_list_by_type(list(exists_tool_type.keys()))
        exists_tool_info = {t.id: t for t in tool_info}
        new_tools = []
        for one in tools:
            new_one = exists_tool_type.get(one.get("id"))
            if not new_one:
                continue
            one["name"] = new_one.name
            one["description"] = new_one.description
            new_children = []
            for item in one.get("children", []):
                if not exists_tool_info.get(item.get("id")):
                    continue
                item["name"] = exists_tool_info[item.get("id")].name
                item["description"] = exists_tool_info[item.get("id")].desc
                item["tool_key"] = exists_tool_info[item.get("id")].tool_key
                new_children.append(item)
            one["children"] = new_children
            new_tools.append(one)
        return new_tools

    @classmethod
    def parse_config(cls, config: Any) -> Optional[WorkstationConfig]:
        if config:
            ret = json.loads(config.value)
            ret = WorkstationConfig(**ret)
            if ret.assistantIcon and ret.assistantIcon.relative_path:
                ret.assistantIcon.image = cls.get_logo_share_link(ret.assistantIcon.relative_path)
            if ret.sidebarIcon and ret.sidebarIcon.relative_path:
                ret.sidebarIcon.image = cls.get_logo_share_link(ret.sidebarIcon.relative_path)

            # 兼容旧的websearch配置
            if ret.webSearch and not ret.webSearch.params:
                ret.webSearch.tool = 'bing'
                ret.webSearch.params = {'api_key': ret.webSearch.bingKey, 'base_url': ret.webSearch.bingUrl}
            if ret.linsightConfig:
                # 判断工具是否被删除, 同步工具最新的信息名称和描述等
                ret.linsightConfig.tools = cls.sync_tool_info(ret.linsightConfig.tools)
            return ret
        return None

    @classmethod
    def get_config(cls) -> WorkstationConfig | None:
        """ 获取工作台的默认配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        return cls.parse_config(config)

    @classmethod
    async def aget_config(cls) -> WorkstationConfig | None:
        """ 异步获取工作台的默认配置 """
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKSTATION)
        return cls.parse_config(config)

    @classmethod
    def uploadPersonalKnowledge(
            cls,
            request: Request,
            login_user: UserPayload,
            file_path,
            background_tasks: BackgroundTasks,
    ):
        # 查询是否有个人知识库
        knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                    KnowledgeTypeEnum.PRIVATE)
        if not knowledge:
            model = LLMService.get_knowledge_llm()
            knowledgeCreate = KnowledgeCreate(name='个人知识库',
                                              type=KnowledgeTypeEnum.PRIVATE.value,
                                              user_id=login_user.user_id,
                                              model=model.embedding_model_id)

            knowledge = KnowledgeService.create_knowledge(request, login_user, knowledgeCreate)
        else:
            knowledge = knowledge[0]
        req_data = KnowledgeFileProcess(knowledge_id=knowledge.id,
                                        file_list=[KnowledgeFileOne(file_path=file_path)])
        try:
            _ = LLMService.get_bisheng_knowledge_embedding(login_user.user_id, int(knowledge.model))
        except Exception as e:
            raise EmbeddingModelStatusError(exception=e)
        res = KnowledgeService.process_knowledge_file(request,
                                                      login_user,
                                                      background_tasks, req_data)
        return res

    @classmethod
    def queryKnowledgeList(
            cls,
            request: Request,
            login_user: UserPayload,
            page: int,
            size: int,
    ):
        # 查询是否有个人知识库
        knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                    KnowledgeTypeEnum.PRIVATE)
        if not knowledge:
            return [], 0
        res, total, _ = KnowledgeService.get_knowledge_files(
            request,
            login_user,
            knowledge[0].id,
            page=page,
            page_size=size)
        return res, total

    @classmethod
    async def queryChunksFromDB(cls, question: str, use_knowledge_param: UseKnowledgeBaseParam,
                                max_token: int,
                                login_user: UserPayload) -> tuple[list[Any], None] | tuple[list[Any], Any]:
        """
        从数据库中查询相关知识块
        
        Args:
            max_token: 最大token限制
            question: 用户查询问题
            use_knowledge_param: 使用知识库的参数
            login_user: 登录用户信息
            
        Returns:
            List[str]: 格式化后的知识库内容列表，格式为：
                "[file name]:文件名\n[file content begin]\n内容\n[file content end]\n"
        """
        try:
            knowledge_ids = []

            if use_knowledge_param.organization_knowledge_ids:
                # 如果有组织知识库，则调用知识库服务获取知识块
                knowledge_ids.extend(use_knowledge_param.organization_knowledge_ids)

            if use_knowledge_param.personal_knowledge_enabled:
                # 如果启用了个人知识库，则添加个人知识库ID
                personal_knowledge = await KnowledgeDao.aget_user_knowledge(login_user.user_id,
                                                                            knowledge_type=KnowledgeTypeEnum.PRIVATE)
                if personal_knowledge:
                    knowledge_ids.append(personal_knowledge[0].id)

            knowledge_vector_list = await KnowledgeRag.get_multi_knowledge_vectorstore(
                invoke_user_id=login_user.user_id,
                knowledge_ids=knowledge_ids,
                user_name=login_user.user_name)

            all_milvus, all_milvus_filter = [], []
            all_es, all_es_filter = [], []
            multi_milvus_retriever, multi_es_retriever = None, None
            for knowledge_id, vectorstore_info in knowledge_vector_list.items():
                milvus_vectorstore = vectorstore_info.get("milvus")
                es_vectorstore = vectorstore_info.get("es")
                all_milvus.append(milvus_vectorstore)
                all_milvus_filter.append({"k": 100, "param": {"ef": 110}})
                all_es.append(es_vectorstore)
                all_es_filter.append({"k": 100})
            if all_milvus:
                multi_milvus_retriever = MultiRetriever(
                    vectors=all_milvus,
                    search_kwargs=all_milvus_filter,
                    finally_k=100
                )
            if all_es:
                multi_es_retriever = MultiRetriever(
                    vectors=all_es,
                    search_kwargs=all_es_filter,
                    finally_k=100
                )
            knowledge_retriever_tool = KnowledgeRetrieverTool(
                vector_retriever=multi_milvus_retriever,
                elastic_retriever=multi_es_retriever,
                max_content=max_token,
                rrf_remove_zero_score=True
            )

            finally_docs = await knowledge_retriever_tool.ainvoke({"query": question})

            # 将检索结果格式化为指定的模板格式
            formatted_results = []
            if finally_docs:
                for doc in finally_docs:
                    # 获取文件名，优先从 metadata 中获取
                    file_name = doc.metadata.get('source') or doc.metadata.get('document_name')
                    # 获取文档内容
                    content = doc.page_content.strip()

                    # 按照模板格式组织内容
                    formatted_content = f"[file name]:{file_name}\n[file content begin]\n{content}\n[file content end]\n"
                    formatted_results.append(formatted_content)

            return formatted_results, finally_docs
        except Exception as e:
            logger.error(f"queryChunksFromDB error: {e}")
            return [], None

    @classmethod
    async def get_chat_history(cls, chat_id: str, size: int = 4):
        chat_history = []
        messages = await ChatMessageDao.aget_messages_by_chat_id(chat_id, ['question', 'answer'], size)
        for one in messages:
            # bug fix When constructing multi-turn dialogues, the input and response of
            # the user and the assistant were reversed, leading to incorrect question-and-answer sequences.
            extra = json.loads(one.extra) or {}
            content = extra['prompt'] if 'prompt' in extra else one.message
            if one.category == MessageCategory.QUESTION.value:
                chat_history.append(HumanMessage(content=content))
            elif one.category == MessageCategory.ANSWER.value:
                chat_history.append(AIMessage(content=content))
        logger.info(f'loaded {len(chat_history)} chat history for chat_id {chat_id}')
        return chat_history


class WorkstationMessage(BaseModel):
    messageId: str
    conversationId: str
    createdAt: datetime
    isCreatedByUser: bool
    model: Optional[str]
    parentMessageId: Optional[str]
    user_name: Optional[str]
    sender: str
    text: str
    updateAt: datetime
    files: Optional[list]
    error: Optional[bool] = False
    unfinished: Optional[bool] = False
    flow_name: Optional[str] = None
    source: Optional[int] = None

    @field_validator('messageId', mode='before')
    @classmethod
    def convert_message_id(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)

    @field_validator('parentMessageId', mode='before')
    @classmethod
    def convert_parent_message_id(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        return str(value)

    @classmethod
    async def from_chat_message(cls, message: ChatMessage):
        files = json.loads(message.files) if message.files else []
        user_model = await UserDao.aget_user(message.user_id)
        message_session_model = await MessageSessionDao.async_get_one(chat_id=message.chat_id)
        return cls(
            messageId=str(message.id),
            conversationId=message.chat_id,
            createdAt=message.create_time,
            updateAt=message.update_time,
            isCreatedByUser=not message.is_bot,
            model=None,
            parentMessageId=json.loads(message.extra).get('parentMessageId'),
            error=json.loads(message.extra).get('error', False),
            unfinished=json.loads(message.extra).get('unfinished', False),
            user_name=user_model.user_name,
            sender=message.sender,
            text=message.message,
            files=files,
            flow_name=message_session_model.flow_name if message_session_model else None,
            source=message.source
        )


class WorkstationConversation(BaseModel):
    conversationId: str
    user: str
    createdAt: datetime
    updateAt: datetime
    model: Optional[str]
    title: Optional[str]

    @classmethod
    def from_chat_session(cls, session: MessageSession):
        return cls(
            conversationId=session.chat_id,
            user=str(session.user_id),
            createdAt=session.create_time,
            updateAt=session.update_time,
            model=None,
            title=session.flow_name,
        )

    @field_validator('user', mode='before')
    @classmethod
    def convert_user(cls, v: Any) -> str:
        if isinstance(v, str):
            return v
        return str(v)


class SSECallbackClient:

    def __init__(self):
        self.queue = asyncio.Queue()

    async def send_json(self, data):
        self.queue.put_nowait(data)
