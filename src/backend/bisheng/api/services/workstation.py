import asyncio
import json

from bisheng.api.services import llm
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess, WorkstationConfig
from bisheng.database.models.config import Config, ConfigDao, ConfigKeyEnum
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum
from fastapi import BackgroundTasks, Request


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

            knowledge = KnowledgeService.create_knowledge(request,
                                                          UserPayload(user_id=login_user.user_id),
                                                          knowledgeCreate)
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
            return {'total': 0, 'list': []}
        res, total, _ = KnowledgeService.get_knowledge_files(
            request,
            UserPayload(user_id=login_user.user_id),
            knowledge[0].id,
            page=page,
            page_size=size)
        return res, total


class SSECallbackClient:

    def __init__(self):
        self.queue = asyncio.Queue()

    async def send_json(self, data):
        self.queue.put_nowait(data)
