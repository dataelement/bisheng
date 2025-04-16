import asyncio
import json
from datetime import datetime
from typing import Optional

from bisheng.api.services import knowledge_imp, llm
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, WorkstationConfig
from bisheng.database.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession
from bisheng.utils.minio_client import MinioClient
from fastapi import BackgroundTasks, Request
from openai import BaseModel

minio_client = MinioClient()


class WorkStationService:

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
    def get_config(cls) -> WorkstationConfig:
        """ 获取评测功能的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.WORKSTATION)
        if config:
            ret = json.loads(config.value)
        return WorkstationConfig(**ret)

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


class SSECallbackClient:

    def __init__(self):
        self.queue = asyncio.Queue()

    async def send_json(self, data):
        self.queue.put_nowait(data)
