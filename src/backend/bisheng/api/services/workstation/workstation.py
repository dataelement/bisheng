import asyncio
import json
from datetime import datetime
from typing import Optional, Any

from pydantic import field_validator

from bisheng.api.services import knowledge_imp, llm
from bisheng.api.services.base import BaseService
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, WorkstationConfig
from bisheng.database.constants import MessageCategory
from bisheng.database.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession
from fastapi import BackgroundTasks, Request
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from openai import BaseModel


class WorkStationService(BaseService):

    @classmethod
    def update_config(cls, request: Request, login_user: UserPayload, data: WorkstationConfig) \
            -> WorkstationConfig:
        """ 更新workflow的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        if config:
            config.value = json.dumps(data.dict())
        else:
            config = Config(key=ConfigKeyEnum.WORKSTATION.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    def get_config(cls) -> WorkstationConfig | None:
        """ 获取工作台的默认配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
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
            return ret
        return None

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
            model = llm.LLMService.get_knowledge_llm()
            knowledgeCreate = KnowledgeCreate(name='个人知识库',
                                              type=KnowledgeTypeEnum.PRIVATE.value,
                                              user_id=login_user.user_id,
                                              model=model.embedding_model_id)

            knowledge = KnowledgeService.create_knowledge(request, login_user, knowledgeCreate)
        else:
            knowledge = knowledge[0]
        req_data = KnowledgeFileProcess(knowledge_id=knowledge.id,
                                        file_list=[KnowledgeFileOne(file_path=file_path)])
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
        knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                    KnowledgeTypeEnum.PRIVATE)

        if not knowledge:
            return []

        search_kwargs = {'partition_key': knowledge[0].id}
        embedding = knowledge_imp.decide_embeddings(knowledge[0].model)
        vectordb = knowledge_imp.decide_vectorstores(knowledge[0].collection_name, 'Milvus',
                                                     embedding)
        vectordb.partition_key = knowledge[0].id
        content = vectordb.as_retriever(search_kwargs=search_kwargs)._get_relevant_documents(
            question, run_manager=None)
        if content:
            content = [
                knowledge_imp.KnowledgeUtils.chunk2promt(c.page_content, c.metadata)
                for c in content
            ]
        else:
            content = []
        return content

    @classmethod
    def get_chat_history(cls, chat_id: str, size: int = 4):
        chat_history = []
        messages = ChatMessageDao.get_messages_by_chat_id(chat_id, ['question', 'answer'], size)
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
    sender: str
    text: str
    updateAt: datetime
    files: Optional[list]
    error: Optional[bool] = False
    unfinished: Optional[bool] = False

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
    def from_chat_message(cls, message: ChatMessage):
        files = json.loads(message.files) if message.files else []
        return cls(
            messageId=message.id,
            conversationId=message.chat_id,
            createdAt=message.create_time,
            updateAt=message.update_time,
            isCreatedByUser=not message.is_bot,
            model=None,
            parentMessageId=json.loads(message.extra).get('parentMessageId'),
            error=json.loads(message.extra).get('error', False),
            unfinished=json.loads(message.extra).get('unfinished', False),
            sender=message.sender,
            text=message.message,
            files=files,
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
            user=session.user_id,
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
