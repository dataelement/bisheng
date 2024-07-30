import json
from typing import List

from fastapi import Request

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.errcode.llm import ServerExistError, ModelNameRepeatError
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import LLMServerInfo, LLMModelInfo, KnowledgeLLMConfig, AssistantLLMConfig, \
    EvaluationLLMConfig, AssistantLLMItem
from bisheng.database.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.llm_server import LLMDao, LLMServer, LLMModel, LLMModelType


class LLMService:

    @classmethod
    def get_all_llm(cls, request: Request, login_user: UserPayload) -> List[LLMServerInfo]:
        """ 获取所有的模型数据， 不包含key等敏感信息 """
        llm_servers = LLMDao.get_all_server()
        ret = []
        server_ids = []
        for one in llm_servers:
            server_ids.append(one.id)
            ret.append(LLMServerInfo(**one.model_dump(exclude={'config'})))

        llm_models = LLMDao.get_model_by_server_ids(server_ids)
        server_dicts = {}
        for one in llm_models:
            if one.server_id not in server_dicts:
                server_dicts[one.server_id] = []
            server_dicts[one.server_id].append(one.model_dump(exclude={'config'}))

        for one in ret:
            one.models = server_dicts.get(one.id, [])
        return ret

    @classmethod
    def get_one_llm(cls, request: Request, login_user: UserPayload, server_id: int) -> LLMServerInfo:
        """ 获取一个服务提供方的详细信息 包含了key等敏感的配置信息 """
        llm = LLMDao.get_server_by_id(server_id)
        if not llm:
            raise NotFoundError.http_exception()

        models = LLMDao.get_model_by_server_ids([server_id])
        models = [LLMModelInfo(**one.model_dump()) for one in models]
        return LLMServerInfo(**llm.model_dump(), models=models)

    @classmethod
    def add_llm_server(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> LLMServerInfo:
        """ 添加一个服务提供方 """
        exist_server = LLMDao.get_server_by_name(server.name)
        if exist_server:
            raise ServerExistError.http_exception(f'<{server.name}>已存在')

        # TODO 尝试实例化下对应的模型组件是否可以成功初始化
        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = one
            else:
                raise ModelNameRepeatError.http_exception()

        db_server = LLMServer(**server.model_dump(exclude={'models'}))
        db_server = LLMDao.insert_server_with_models(db_server, [LLMModel(**one.model_dump()) for one in server.models])
        ret = cls.get_one_llm(request, login_user, db_server.id)
        cls.add_llm_server_hook(request, login_user, ret)
        return ret

    @classmethod
    def add_llm_server_hook(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> bool:
        """ 添加一个服务提供方 后续动作 """

        handle_types = []
        for one in server.models:
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = LLMDao.get_model_by_type(one.model_type)
            # 判断是否是首个 模型
            if model_info.id == one.id:
                cls.set_default_model(request, login_user, model_info)
        return True

    @classmethod
    def set_default_model(cls, request: Request, login_user: UserPayload, model: LLMModel):
        """ 设置默认的模型配置 """
        # 设置默认的llm模型配置
        if model.model_type == LLMModelType.LLM:
            # 设置知识库的默认模型配置
            knowledge_llm = cls.get_knowledge_llm(request, login_user)
            knowledge_change = False
            if not knowledge_llm.extract_title_model_id:
                knowledge_llm.extract_title_model_id = model.id
                knowledge_change = True
            if not knowledge_llm.source_model_id:
                knowledge_llm.source_model_id = model.id
                knowledge_change = True
            if not knowledge_llm.qa_similar_model_id:
                knowledge_llm.qa_similar_model_id = model.id
                knowledge_change = True
            if knowledge_change:
                cls.update_knowledge_llm(request, login_user, knowledge_llm)

            # 设置评测的默认模型配置
            evaluation_llm = cls.get_evaluation_llm(request, login_user)
            if not evaluation_llm.model_id:
                evaluation_llm.model_id = model.id
                cls.update_evaluation_llm(request, login_user, evaluation_llm)

            # 设置助手的默认模型配置
            assistant_llm = cls.get_assistant_llm(request, login_user)
            assistant_change = False
            if not assistant_llm.auto_llm:
                assistant_llm.auto_llm = model.id
                assistant_change = True
            if not assistant_llm.llm_list:
                assistant_change = True
                assistant_llm.llm_list = [
                    AssistantLLMItem(
                        model_id=model.id,
                        agent_executor_type='React',
                        knowledge_search_max_content=15000,
                        knowledge_sort_index=False,
                        default=False
                    )
                ]
            if assistant_change:
                cls.update_assistant_llm(request, login_user, assistant_llm)

        elif model.model_type == LLMModelType.EMBEDDING:
            knowledge_llm = cls.get_knowledge_llm(request, login_user)
            if not knowledge_llm.embedding_model_id:
                knowledge_llm.embedding_model_id = model.id
                cls.update_knowledge_llm(request, login_user, knowledge_llm)

    @classmethod
    def update_llm_server(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> LLMServerInfo:
        """ 更新服务提供方信息 """
        exist_server = LLMDao.get_server_by_id(server.id)
        if not exist_server:
            raise NotFoundError.http_exception()
        if exist_server.name != server.name:
            # 改名的话判断下是否已经存在
            name_server = LLMDao.get_server_by_name(server.name)
            if name_server and name_server.id != server.id:
                raise ServerExistError.http_exception(f'<{server.name}>已存在')

        model_dict = {}
        for one in server.models:
            if one.name not in model_dict:
                model_dict[one.name] = one
            else:
                raise ModelNameRepeatError.http_exception()

        db_server = LLMServer(**server.model_dump(exclude={'models'}))
        db_server = LLMDao.insert_server_with_models(db_server, [LLMModel(**one.model_dump()) for one in server.models])

        return cls.get_one_llm(request, login_user, db_server.id)

    @classmethod
    def get_knowledge_llm(cls, request: Request, login_user: UserPayload) -> KnowledgeLLMConfig:
        """ 获取知识库相关的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.KNOWLEDGE_LLM)
        if config:
            ret = json.loads(config.value)
        return KnowledgeLLMConfig(**ret)

    @classmethod
    def update_knowledge_llm(cls, request: Request, login_user: UserPayload, data: KnowledgeLLMConfig) \
            -> KnowledgeLLMConfig:
        """ 更新知识库相关的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.KNOWLEDGE_LLM)
        if config:
            config.value = json.dumps(data.dict())
        else:
            config = Config(key=ConfigKeyEnum.KNOWLEDGE_LLM.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    def get_assistant_llm(cls, request: Request, login_user: UserPayload) -> AssistantLLMConfig:
        """ 获取助手相关的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.ASSISTANT_LLM)
        if config:
            ret = json.loads(config.value)
        return AssistantLLMConfig(**ret)

    @classmethod
    def update_assistant_llm(cls, request: Request, login_user: UserPayload, data: AssistantLLMConfig) \
            -> AssistantLLMConfig:
        """ 更新助手相关的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.ASSISTANT_LLM)
        if config:
            config.value = json.dumps(data.dict())
        else:
            config = Config(key=ConfigKeyEnum.ASSISTANT_LLM.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    def get_evaluation_llm(cls, request: Request, login_user: UserPayload) -> EvaluationLLMConfig:
        """ 获取评测功能的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.EVALUATION_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    def update_evaluation_llm(cls, request: Request, login_user: UserPayload, data: EvaluationLLMConfig) \
            -> EvaluationLLMConfig:
        """ 更新评测功能的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.EVALUATION_LLM)
        if config:
            config.value = json.dumps(data.dict())
        else:
            config = Config(key=ConfigKeyEnum.EVALUATION_LLM.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data
