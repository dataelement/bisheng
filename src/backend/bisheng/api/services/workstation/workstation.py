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
from bisheng.api.services.knowledge import mixed_retrieval_recall
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, WorkstationConfig
from bisheng.common.errcode.server import EmbeddingModelStatusError
from bisheng.database.constants import MessageCategory
from bisheng.common.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.database.models.user import UserDao
from bisheng.llm.domain.services import LLMService
from bisheng.utils.embedding import create_knowledge_keyword_store, decide_embeddings
from bisheng.utils.embedding import create_knowledge_vector_store


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
    async def uploadPersonalKnowledge(
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
            _ = decide_embeddings(knowledge.model)
        except Exception as e:
            raise EmbeddingModelStatusError(exception=e)
        res = KnowledgeService.process_knowledge_file(request,
                                                      UserPayload(user_id=login_user.user_id),
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
            UserPayload(user_id=login_user.user_id),
            knowledge[0].id,
            page=page,
            page_size=size)
        return res, total

    @classmethod
    def queryChunksFromDB(cls, question: str, login_user: UserPayload):
        """
        从数据库中查询相关知识块
        
        Args:
            question: 用户查询问题
            login_user: 登录用户信息
            
        Returns:
            List[str]: 格式化后的知识库内容列表，格式为：
                "[file name]:文件名\n[file content begin]\n内容\n[file content end]\n"
        """
        knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                    KnowledgeTypeEnum.PRIVATE)

        if not knowledge:
            return []

        try:
            _ = decide_embeddings(knowledge[0].model)
        except Exception as e:
            raise EmbeddingModelStatusError(exception=e)

        vector_store = create_knowledge_vector_store([str(knowledge[0].id)], login_user.user_name)
        keyword_store = create_knowledge_keyword_store([str(knowledge[0].id)], login_user.user_name)

        # 获取配置中的最大token数，如果没有配置则使用默认值
        config = cls.get_config()
        max_tokens = config.maxTokens if config else 1500

        # 获取知识库溯源模型 ID，如果没有配置则使用知识库的嵌入模型 ID
        knowledge_llm = LLMService.get_knowledge_llm()
        model_id = knowledge_llm.source_model_id

        docs = mixed_retrieval_recall(question, vector_store, keyword_store, max_tokens, model_id)
        logger.info(f"docs message: {docs}")
        # 将检索结果格式化为指定的模板格式
        formatted_results = []
        if docs:
            for doc in docs:
                # 获取文件名，优先从 metadata 中获取
                file_name = doc.metadata.get('file_name', 'unknown_file')
                if not file_name or file_name == 'unknown_file':
                    # 尝试从其他字段获取文件名
                    file_name = doc.metadata.get('source', doc.metadata.get('filename', 'unknown_file'))

                # 获取文档内容
                content = doc.page_content.strip()

                # 按照模板格式组织内容
                formatted_content = f"[file name]:{file_name}\n[file content begin]\n{content}\n[file content end]\n"
                formatted_results.append(formatted_content)

        return formatted_results

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
