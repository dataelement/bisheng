import json
from typing import List, Optional

from fastapi import Request
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.errcode.llm import ServerExistError, ModelNameRepeatError, ServerAddError, ServerAddAllError
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import LLMServerInfo, LLMModelInfo, KnowledgeLLMConfig, AssistantLLMConfig, \
    EvaluationLLMConfig, AssistantLLMItem, LLMServerCreateReq
from bisheng.database.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.llm_server import LLMDao, LLMServer, LLMModel, LLMModelType
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm, instantiate_embedding


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
    def add_llm_server(cls, request: Request, login_user: UserPayload, server: LLMServerCreateReq) -> LLMServerInfo:
        """ 添加一个服务提供方 """
        exist_server = LLMDao.get_server_by_name(server.name)
        if exist_server:
            raise ServerExistError.http_exception()

        # TODO 尝试实例化下对应的模型组件是否可以成功初始化
        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.dict(), user_id=login_user.user_id)
            else:
                raise ModelNameRepeatError.http_exception()

        db_server = LLMServer(**server.dict(exclude={'models'}))
        db_server.user_id = login_user.user_id

        db_server = LLMDao.insert_server_with_models(db_server, list(model_dict.values()))

        ret = cls.get_one_llm(request, login_user, db_server.id)
        success_models = []
        success_msg = ''
        failed_models = []
        failed_msg = ''
        # 尝试实例化对应的模型，有报错的话删除
        for one in ret.models:
            try:
                if one.model_type == LLMModelType.LLM.value:
                    cls.get_bisheng_llm(model_id=one.id, ignore_online=True)
                elif one.model_type == LLMModelType.EMBEDDING.value:
                    cls.get_bisheng_embedding(model_id=one.id, ignore_online=True)
                success_msg += f'{one.model_name},'
                success_models.append(one)
            except Exception as e:
                logger.exception("init_model_error")
                # 模型初始化失败的话，不添加到模型列表里
                failed_msg += f'<{one.model_name}>添加失败，失败原因：{str(e)}\n'
                failed_models.append(one)

        # 说明模型全部添加失败了
        if len(success_models) == 0 and failed_msg:
            LLMDao.delete_server_by_id(ret.id)
            raise ServerAddAllError.http_exception(failed_msg)
        elif len(success_models) > 0 and failed_msg:
            # 部分模型添加成功了, 删除失败的模型信息
            ret.models = success_models
            LLMDao.delete_model_by_ids(model_ids=[one.id for one in failed_models])
            cls.add_llm_server_hook(request, login_user, ret)
            raise ServerAddError.http_exception(f"<{success_msg.rstrip(',')}>添加成功，{failed_msg}")

        cls.add_llm_server_hook(request, login_user, ret)
        return ret

    @classmethod
    def delete_llm_server(cls, request: Request, login_user: UserPayload, server_id: int) -> bool:
        """ 删除一个服务提供方 """
        LLMDao.delete_server_by_id(server_id)
        return True

    @classmethod
    def add_llm_server_hook(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> bool:
        """ 添加一个服务提供方 后续动作 """

        handle_types = []
        for one in server.models:
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = LLMDao.get_model_by_type(LLMModelType(one.model_type))
            # 判断是否是首个llm或者embedding模型
            if model_info.id == one.id:
                cls.set_default_model(request, login_user, model_info)
        return True

    @classmethod
    def set_default_model(cls, request: Request, login_user: UserPayload, model: LLMModel):
        """ 设置默认的模型配置 """
        # 设置默认的llm模型配置
        if model.model_type == LLMModelType.LLM.value:
            # 设置知识库的默认模型配置
            knowledge_llm = cls.get_knowledge_llm()
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
            evaluation_llm = cls.get_evaluation_llm()
            if not evaluation_llm.model_id:
                evaluation_llm.model_id = model.id
                cls.update_evaluation_llm(request, login_user, evaluation_llm)

            # 设置助手的默认模型配置
            assistant_llm = cls.get_assistant_llm()
            assistant_change = False
            if not assistant_llm.auto_llm:
                assistant_llm.auto_llm = AssistantLLMItem(model_id=model.id)
                assistant_change = True
            if not assistant_llm.llm_list:
                assistant_change = True
                assistant_llm.llm_list = [
                    AssistantLLMItem(model_id=model.id, default=True)
                ]
            if assistant_change:
                cls.update_assistant_llm(request, login_user, assistant_llm)

        elif model.model_type == LLMModelType.EMBEDDING.value:
            knowledge_llm = cls.get_knowledge_llm()
            if not knowledge_llm.embedding_model_id:
                knowledge_llm.embedding_model_id = model.id
                cls.update_knowledge_llm(request, login_user, knowledge_llm)

    @classmethod
    def update_llm_server(cls, request: Request, login_user: UserPayload, server: LLMServerCreateReq) -> LLMServerInfo:
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
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.dict())
                # 说明是新增模型
                if not one.id:
                    model_dict[one.model_name].user_id = login_user.user_id
                    model_dict[one.model_name].server_id = exist_server.id
            else:
                raise ModelNameRepeatError.http_exception()

        exist_server.name = server.name
        exist_server.description = server.description
        exist_server.type = server.type
        exist_server.limit_flag = server.limit_flag
        exist_server.limit = server.limit
        exist_server.config = server.config

        db_server = LLMDao.update_server_with_models(exist_server, list(model_dict.values()))

        return cls.get_one_llm(request, login_user, db_server.id)

    @classmethod
    def update_model_online(cls, request: Request, login_user: UserPayload, model_id: int,
                            online: bool) -> LLMModelInfo:
        """ 更新模型是否上线 """
        exist_model = LLMDao.get_model_by_id(model_id)
        if not exist_model:
            raise NotFoundError.http_exception()
        exist_model.online = online
        LLMDao.update_model_online(exist_model.id, online)
        return LLMModelInfo(**exist_model.dict())

    @classmethod
    def get_knowledge_llm(cls) -> KnowledgeLLMConfig:
        """ 获取知识库相关的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.KNOWLEDGE_LLM)
        if config:
            ret = json.loads(config.value)
        return KnowledgeLLMConfig(**ret)

    @classmethod
    def get_knowledge_source_llm(cls) -> Optional[BaseChatModel]:
        """ 获取知识库溯源的默认模型配置 """
        knowledge_llm = cls.get_knowledge_llm()
        # 没有配置模型，则用jieba
        if not knowledge_llm.source_model_id:
            return None
        return cls.get_bisheng_llm(model_id=knowledge_llm.source_model_id)

    @classmethod
    def get_knowledge_similar_llm(cls) -> Optional[BaseChatModel]:
        """ 获取知识库相似问的默认模型配置 """
        knowledge_llm = cls.get_knowledge_llm()
        # 没有配置模型，则用jieba
        if not knowledge_llm.qa_similar_model_id:
            return None
        return cls.get_bisheng_llm(model_id=knowledge_llm.qa_similar_model_id)

    @classmethod
    def get_knowledge_default_embedding(cls) -> Optional[Embeddings]:
        """ 获取知识库默认的embedding模型 """
        knowledge_llm = cls.get_knowledge_llm()
        # 没有配置模型，则用jieba
        if not knowledge_llm.embedding_model_id:
            return None
        return cls.get_bisheng_embedding(model_id=knowledge_llm.embedding_model_id)

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
    def get_assistant_llm(cls) -> AssistantLLMConfig:
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
    def get_evaluation_llm(cls) -> EvaluationLLMConfig:
        """ 获取评测功能的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.EVALUATION_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    def get_evaluation_llm_object(cls) -> BaseChatModel:
        evaluation_llm = cls.get_evaluation_llm()
        if not evaluation_llm.model_id:
            raise Exception('未配置评测模型')
        return cls.get_bisheng_llm(model_id=evaluation_llm.model_id)

    @classmethod
    def get_bisheng_llm(cls, **kwargs) -> BaseChatModel:
        """ 获取评测功能的默认模型配置 """
        class_object = import_by_type(_type='llms', name='BishengLLM')
        return instantiate_llm('BishengLLM', class_object, kwargs)

    @classmethod
    def get_bisheng_embedding(cls, **kwargs) -> Embeddings:
        """ 获取评测功能的默认模型配置 """
        class_object = import_by_type(_type='embeddings', name='BishengEmbedding')
        return instantiate_embedding(class_object, kwargs)

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

    @classmethod
    def get_assistant_llm_list(cls, request: Request, login_user: UserPayload) -> List[LLMServerInfo]:
        """ 获取助手可选的模型列表 """
        assistant_llm = cls.get_assistant_llm()
        if not assistant_llm.llm_list:
            return []
        model_list = LLMDao.get_model_by_ids([one.model_id for one in assistant_llm.llm_list])
        if not model_list:
            return []

        model_dict = {}
        for one in model_list:
            if one.server_id not in model_dict:
                model_dict[one.server_id] = []
            model_dict[one.server_id].append(LLMModelInfo(**one.dict(exclude={'config'})))
        server_list = LLMDao.get_server_by_ids(list(model_dict.keys()))

        ret = []
        for one in server_list:
            ret.append(LLMServerInfo(**one.dict(exclude={'config'}), models=model_dict[one.id]))

        return ret
