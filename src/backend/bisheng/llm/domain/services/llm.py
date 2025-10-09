import json
from typing import List, Optional

from fastapi import Request, BackgroundTasks, UploadFile
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.errcode.http_error import NotFoundError, ServerError
from bisheng.api.errcode.llm import ServerExistError, ModelNameRepeatError, ServerAddError, ServerAddAllError
from bisheng.api.errcode.server import NoAsrModelConfigError, AsrModelConfigDeletedError, NoTtsModelConfigError, \
    TtsModelConfigDeletedError
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import LLMServerInfo, LLMModelInfo, KnowledgeLLMConfig, AssistantLLMConfig, \
    EvaluationLLMConfig, AssistantLLMItem, LLMServerCreateReq, WorkbenchModelConfig
from bisheng.database.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.database.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.database.models.knowledge import KnowledgeState
from bisheng.database.models.llm_server import LLMDao, LLMServer, LLMModel, LLMModelType
from bisheng.interface.importing import import_by_type
from bisheng.interface.initialize.loading import instantiate_llm, instantiate_embedding
from bisheng.llm.domain.llm.asr import BishengASR
from bisheng.llm.domain.llm.tts import BishengTTS
from bisheng.utils.embedding import decide_embeddings


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
            server_dicts[one.server_id].append(LLMModelInfo(**one.model_dump(exclude={'config'})))

        for one in ret:
            one.models = server_dicts.get(one.id, [])
        return ret

    @classmethod
    async def get_one_llm(cls, request: Request, login_user: UserPayload, server_id: int) -> LLMServerInfo:
        """ 获取一个服务提供方的详细信息 包含了key等敏感的配置信息 """
        llm = LLMDao.get_server_by_id(server_id)
        if not llm:
            raise NotFoundError.http_exception()

        models = LLMDao.get_model_by_server_ids([server_id])
        models = [LLMModelInfo(**one.model_dump()) for one in models]
        return LLMServerInfo(**llm.model_dump(), models=models)

    @classmethod
    async def add_llm_server(cls, request: Request, login_user: UserPayload,
                             server: LLMServerCreateReq) -> LLMServerInfo:
        """ 添加一个服务提供方 """
        exist_server = await LLMDao.aget_server_by_name(server.name)
        if exist_server:
            raise ServerExistError.http_exception()

        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.model_dump(), user_id=login_user.user_id)
            else:
                raise ModelNameRepeatError.http_exception()

        db_server = LLMServer(**server.model_dump(exclude={'models'}))
        db_server.user_id = login_user.user_id

        db_server = await LLMDao.ainsert_server_with_models(db_server, list(model_dict.values()))

        ret = await cls.get_one_llm(request, login_user, db_server.id)
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
                elif one.model_type == LLMModelType.ASR.value:
                    await cls.get_bisheng_asr(model_id=one.id, ignore_online=True)
                elif one.model_type == LLMModelType.TTS.value:
                    await cls.get_bisheng_tts(model_id=one.id, ignore_online=True)

                success_msg += f'{one.model_name},'
                success_models.append(one)
            except Exception as e:
                logger.exception("init_model_error")
                # 模型初始化失败的话，不添加到模型列表里
                failed_msg += f'<{one.model_name}>添加失败，失败原因：{str(e)}\n'
                failed_models.append(one)

        # 说明模型全部添加失败了
        if len(success_models) == 0 and failed_msg:
            await LLMDao.adelete_server_by_id(ret.id)
            raise ServerAddAllError.http_exception(failed_msg)
        elif len(success_models) > 0 and failed_msg:
            # 部分模型添加成功了, 删除失败的模型信息
            ret.models = success_models
            await LLMDao.adelete_model_by_ids(model_ids=[one.id for one in failed_models])
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
            # test model status
            cls.test_model_status(one)
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = LLMDao.get_model_by_type(LLMModelType(one.model_type))
            # 判断是否是首个llm或者embedding模型
            if model_info.id == one.id:
                cls.set_default_model(request, login_user, model_info)
        return True

    @classmethod
    def test_model_status(cls, model: LLMModel | LLMModelInfo):
        try:
            if model.model_type == LLMModelType.LLM.value:
                bisheng_model = cls.get_bisheng_llm(model_id=model.id, ignore_online=True, cache=False)
                bisheng_model.invoke('hello')
            elif model.model_type == LLMModelType.EMBEDDING.value:
                bisheng_embed = cls.get_bisheng_embedding(model_id=model.id, ignore_online=True, cache=False)
                bisheng_embed.embed_query('hello')
        except Exception as e:
            LLMDao.update_model_status(model.id, 1, str(e))
            logger.exception(f'test model status: {model.id} {model.model_name}')

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
    async def update_llm_server(cls, request: Request, login_user: UserPayload,
                                server: LLMServerCreateReq) -> LLMServerInfo:
        """ 更新服务提供方信息 """
        exist_server = LLMDao.get_server_by_id(server.id)
        if not exist_server:
            raise NotFoundError.http_exception()

        old_models = LLMDao.get_model_by_server_ids([exist_server.id])
        old_model_dict = {
            one.id: one for one in old_models
        }
        if exist_server.name != server.name:
            # 改名的话判断下是否已经存在
            name_server = LLMDao.get_server_by_name(server.name)
            if name_server and name_server.id != server.id:
                raise ServerExistError.http_exception(f'<{server.name}>已存在')

        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.model_dump())
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
        new_server_info = await cls.get_one_llm(request, login_user, db_server.id)

        # 判断是否需要重新判断模型状态
        for one in new_server_info.models:
            # 新增的模型，或者模型名字或者类型发生了变化
            if (one.id not in old_model_dict or old_model_dict[one.id].model_name != one.model_name
                    or old_model_dict[one.id].model_type != one.model_type):
                cls.test_model_status(one)
        return new_server_info

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
    async def aget_knowledge_llm(cls) -> KnowledgeLLMConfig:
        """ 获取知识库相关的默认模型配置 """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.KNOWLEDGE_LLM)
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
        """ 初始化毕昇llm对话模型 """
        class_object = import_by_type(_type='llms', name='BishengLLM')
        return instantiate_llm('BishengLLM', class_object, kwargs)

    @classmethod
    def get_bisheng_embedding(cls, **kwargs) -> Embeddings:
        """ 初始化毕昇embedding模型 """
        class_object = import_by_type(_type='embeddings', name='BishengEmbedding')
        return instantiate_embedding(class_object, kwargs)

    @classmethod
    async def get_bisheng_asr(cls, **kwargs):
        """ 初始化毕昇asr模型 """
        return await BishengASR.get_bisheng_asr(**kwargs)

    @classmethod
    async def get_bisheng_tts(cls, **kwargs):
        """ 初始化毕昇tts模型 """
        return await BishengTTS.get_bisheng_tts(**kwargs)

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
    def update_workflow_llm(cls, request: Request, login_user: UserPayload, data: EvaluationLLMConfig) \
            -> EvaluationLLMConfig:
        """ 更新workflow的默认模型配置 """
        config = ConfigDao.get_config(ConfigKeyEnum.WORKFLOW_LLM)
        if config:
            config.value = json.dumps(data.dict())
        else:
            config = Config(key=ConfigKeyEnum.WORKFLOW_LLM.value, value=json.dumps(data.dict()))
        ConfigDao.insert_config(config)
        return data

    @classmethod
    def get_workflow_llm(cls) -> EvaluationLLMConfig:
        """ 获取评测功能的默认模型配置 """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.WORKFLOW_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    def get_assistant_llm_list(cls, request: Request, login_user: UserPayload) -> List[LLMServerInfo]:
        """ 获取助手可选的模型列表 """
        assistant_llm = cls.get_assistant_llm()
        if not assistant_llm.llm_list:
            return []
        model_list = LLMDao.get_model_by_ids([one.model_id for one in assistant_llm.llm_list])
        if not model_list:
            return []

        default_llm = next(filter(lambda x: x.default, assistant_llm.llm_list), None)
        if not default_llm:
            default_llm = assistant_llm.llm_list[0]
        model_dict = {}
        default_server = None
        for one in model_list:
            if one.server_id not in model_dict:
                model_dict[one.server_id] = []
            if one.id == default_llm.model_id:
                default_server = one.server_id
                model_dict[one.server_id].insert(0, LLMModelInfo(**one.dict(exclude={'config'})))
                continue
            model_dict[one.server_id].append(LLMModelInfo(**one.dict(exclude={'config'})))
        server_list = LLMDao.get_server_by_ids(list(model_dict.keys()))

        ret = []
        for one in server_list:
            if one.id == default_server:
                ret.insert(0, LLMServerInfo(**one.dict(exclude={'config'}), models=model_dict[one.id]))
                continue
            ret.append(LLMServerInfo(**one.dict(exclude={'config'}), models=model_dict[one.id]))

        return ret

    @classmethod
    async def update_workbench_llm(cls, config_obj: WorkbenchModelConfig, background_tasks: BackgroundTasks):
        """
        更新灵思模型配置
        :param config_obj:
        :return:
        """
        # 延迟导入以避免循环导入
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery

        config = await ConfigDao.aget_config(ConfigKeyEnum.LINSIGHT_LLM)
        if not config:
            config = Config(key=ConfigKeyEnum.LINSIGHT_LLM.value, value='{}')

        if config_obj.embedding_model:
            # 判断是否一致
            config_old_obj = WorkbenchModelConfig(**json.loads(config.value)) if config else WorkbenchModelConfig()
            if (config_obj.embedding_model.id and config_old_obj.embedding_model is None or
                    config_obj.embedding_model.id != config_old_obj.embedding_model.id):
                embeddings = decide_embeddings(config_obj.embedding_model.id)
                try:
                    await embeddings.aembed_query("test")
                except Exception as e:
                    raise Exception(f"Embedding模型初始化失败: {str(e)}")
                from bisheng.api.services.linsight.sop_manage import SOPManageService

                background_tasks.add_task(SOPManageService.rebuild_sop_vector_store_task, embeddings)

                # 更新个人知识库
                # 1.更新所有type为2(私有知识库)的knowledge状态和模型
                private_knowledges = KnowledgeDao.get_all_knowledge(
                    knowledge_type=KnowledgeTypeEnum.PRIVATE
                )

                updated_count = 0
                for knowledge in private_knowledges:
                    # 更新状态为重建中，模型为新的model_id
                    knowledge.state = KnowledgeState.REBUILDING.value
                    knowledge.model = str(embeddings.model_id)
                    KnowledgeDao.update_one(knowledge)
                    updated_count += 1

                    # 3. 为每个knowledge发起异步任务
                    rebuild_knowledge_celery.delay(knowledge.id, str(embeddings.model_id))
                    logger.info(
                        f"Started rebuild task for knowledge_id={knowledge.id} with model_id={embeddings.model_id}")

                logger.info(
                    f"Updated {updated_count} private knowledge bases to use new embedding model {embeddings.model_id}")

        config.value = json.dumps(config_obj.model_dump(), ensure_ascii=False)

        await ConfigDao.async_insert_config(config)

        return config_obj

    @classmethod
    async def get_workbench_llm(cls) -> WorkbenchModelConfig:
        """
        获取工作台模型配置
        :return:
        """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.LINSIGHT_LLM)
        if config:
            ret = json.loads(config.value)
        return WorkbenchModelConfig(**ret)

    @classmethod
    async def invoke_workbench_asr(cls, file: UploadFile) -> str:
        """
        调用工作台的asr模型 将语音转为文字
        :param file:
        :return:
        """
        if not file:
            raise ServerError.http_exception("no file upload")
        workbench_llm = await cls.get_workbench_llm()
        if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
            raise NoAsrModelConfigError.http_exception()
        model_info = await cls.get_bisheng_asr(model_id=int(workbench_llm.asr_model.id))
        if not model_info:
            raise AsrModelConfigDeletedError.http_exception()
        asr_client = await cls.get_bisheng_asr(model_id=int(workbench_llm.asr_model.id))
        return await asr_client.ainvoke(file.file)

    @classmethod
    async def invoke_workbench_tts(cls, text: str) -> bytes:
        """
        调用工作台的tts模型 将文字转为语音
        :param text:
        :return:
        """

        workbench_llm = await cls.get_workbench_llm()
        if not workbench_llm.tts_model or not workbench_llm.tts_model.id:
            raise NoTtsModelConfigError.http_exception()
        model_info = await cls.get_bisheng_tts(model_id=int(workbench_llm.tts_model.id))
        if not model_info:
            raise TtsModelConfigDeletedError.http_exception()
        tts_client = await cls.get_bisheng_tts(model_id=int(workbench_llm.tts_model.id))
        return await tts_client.ainvoke(text)
