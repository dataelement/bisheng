import json
import os
from typing import List, Optional, Dict

from fastapi import Request, BackgroundTasks, UploadFile
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, ServerError
from bisheng.common.errcode.llm import ServerExistError, ModelNameRepeatError, ServerAddError, ServerAddAllError
from bisheng.common.errcode.server import NoAsrModelConfigError, AsrModelConfigDeletedError, NoTtsModelConfigError, \
    TtsModelConfigDeletedError
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum, Config
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao, LLMServer, LLMModel
from bisheng.llm.domain.schemas import LLMServerInfo, LLMModelInfo, KnowledgeLLMConfig, AssistantLLMConfig, \
    EvaluationLLMConfig, AssistantLLMItem, LLMServerCreateReq, WorkbenchModelConfig, WSModel
from bisheng.utils import generate_uuid, md5_hash
from bisheng.utils.mask_data import JsonFieldMasker
from ..llm import BishengASR, BishengLLM, BishengTTS, BishengEmbedding
from ..llm.rerank import BishengRerank


class LLMService:

    @classmethod
    async def get_all_llm(cls) -> List[LLMServerInfo]:
        """ Get all the model data, Exclusion:keyand other sensitive information """
        llm_servers = await LLMDao.aget_all_server()
        ret = []
        server_ids = []
        for one in llm_servers:
            server_ids.append(one.id)
            ret.append(LLMServerInfo(**one.model_dump(exclude={'config'})))

        llm_models = await LLMDao.aget_model_by_server_ids(server_ids)
        server_dicts = {}
        for one in llm_models:
            if one.server_id not in server_dicts:
                server_dicts[one.server_id] = []
            server_dicts[one.server_id].append(LLMModelInfo(**one.model_dump(exclude={'config'})))

        for one in ret:
            one.models = server_dicts.get(one.id, [])
        return ret

    @classmethod
    async def get_one_llm(cls, server_id: int) -> LLMServerInfo:
        """ Get a service provider's details Containskeyand other sensitive configuration information """
        llm = await LLMDao.aget_server_by_id(server_id)
        if not llm:
            raise NotFoundError.http_exception()

        models = await LLMDao.aget_model_by_server_ids([server_id])
        models = [LLMModelInfo(**one.model_dump()) for one in models]
        return LLMServerInfo(**llm.model_dump(), models=models)

    @classmethod
    async def add_llm_server(cls, request: Request, login_user: UserPayload,
                             server: LLMServerCreateReq) -> LLMServerInfo:
        """ Add a service provider """
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

        ret = await cls.get_one_llm(db_server.id)
        success_models = []
        success_msg = ''
        failed_models = []
        failed_msg = ''
        # Try to instantiate the corresponding model, delete it if there is an error
        common_params = {
            'app_id': ApplicationTypeEnum.MODEL_TEST.value,
            'app_name': ApplicationTypeEnum.MODEL_TEST.value,
            'app_type': ApplicationTypeEnum.MODEL_TEST,
            'user_id': login_user.user_id,
        }
        for one in ret.models:
            try:
                if one.model_type == LLMModelType.LLM.value:
                    await cls.get_bisheng_llm(model_id=one.id, ignore_online=True, **common_params)
                elif one.model_type == LLMModelType.EMBEDDING.value:
                    await cls.get_bisheng_embedding(model_id=one.id, ignore_online=True, **common_params)
                elif one.model_type == LLMModelType.ASR.value:
                    await cls.get_bisheng_asr(model_id=one.id, ignore_online=True, **common_params)
                elif one.model_type == LLMModelType.TTS.value:
                    await cls.get_bisheng_tts(model_id=one.id, ignore_online=True, **common_params)

                success_msg += f'{one.model_name},'
                success_models.append(one)
            except Exception as e:
                logger.exception("init_model_error")
                # If model initialization fails, do not add to the model list
                failed_msg += f'<{one.model_name}>Add failed, Reason for failure:{str(e)}\n'
                failed_models.append(one)

        # Description Failed to add all models
        if len(success_models) == 0 and failed_msg:
            await LLMDao.adelete_server_by_id(ret.id)
            raise ServerAddAllError.http_exception(failed_msg)
        elif len(success_models) > 0 and failed_msg:
            # Some models added successfully, Delete failed model information
            ret.models = success_models
            await LLMDao.adelete_model_by_ids(model_ids=[one.id for one in failed_models])
            await cls.add_llm_server_hook(request, login_user, ret)
            raise ServerAddError.http_exception(f"<{success_msg.rstrip(',')}>Added{failed_msg}")

        await cls.add_llm_server_hook(request, login_user, ret)
        return ret

    @classmethod
    async def delete_llm_server(cls, request: Request, login_user: UserPayload, server_id: int) -> bool:
        """ Delete a service provider """
        await LLMDao.adelete_server_by_id(server_id)
        return True

    @classmethod
    async def add_llm_server_hook(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> bool:
        """ Add a service provider Next Actions """

        handle_types = []
        for one in server.models:
            # test model status
            await cls.test_model_status(one, login_user)
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = await LLMDao.aget_model_by_type(LLMModelType(one.model_type))
            # Determine if this is the firstllmorembeddingModels
            if model_info.id == one.id:
                await cls.set_default_model(model_info)
        return True

    @classmethod
    async def test_model_status(cls, model: LLMModel | LLMModelInfo, login_user: UserPayload):
        common_params = {
            'app_id': ApplicationTypeEnum.MODEL_TEST.value,
            'app_name': ApplicationTypeEnum.MODEL_TEST.value,
            'app_type': ApplicationTypeEnum.MODEL_TEST,
            'user_id': login_user.user_id,
        }
        try:
            if model.model_type == LLMModelType.LLM.value:
                bisheng_model = await cls.get_bisheng_llm(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_model.ainvoke('hello')
            elif model.model_type == LLMModelType.EMBEDDING.value:
                bisheng_embed = await cls.get_bisheng_embedding(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_embed.aembed_query('hello')
            elif model.model_type == LLMModelType.TTS.value:
                bisheng_tts = await cls.get_bisheng_tts(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_tts.ainvoke('hello')
            elif model.model_type == LLMModelType.ASR.value:
                example_file_path = os.path.join(os.path.dirname(__file__), "./asr_example.wav")
                with open(example_file_path, 'rb') as f:
                    bisheng_asr = await cls.get_bisheng_asr(model_id=model.id, ignore_online=True, **common_params)
                    await bisheng_asr.ainvoke(f)
            elif model.model_type == LLMModelType.RERANK.value:
                bisheng_rerank = await cls.get_bisheng_rerank(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_rerank.acompress_documents(documents=[Document(page_content="hello world")],
                                                         query="hello")
        except Exception as e:
            LLMDao.update_model_status(model.id, 1, str(e))
            logger.exception(f'test model status: {model.id} {model.model_name}')

    @classmethod
    async def set_default_model(cls, model: LLMModel | LLMModelInfo):
        """ Set default model configuration """
        # Set defaultllmmodel config
        if model.model_type == LLMModelType.LLM.value:
            # Set default model configuration for knowledge base
            knowledge_llm = await cls.aget_knowledge_llm()
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
                await cls.update_knowledge_llm(knowledge_llm)

            # Set default model configuration for reviews
            evaluation_llm = await cls.get_evaluation_llm()
            if not evaluation_llm.model_id:
                evaluation_llm.model_id = model.id
                await cls.update_evaluation_llm(evaluation_llm)

            # Setting the default model configuration for the assistant
            assistant_llm = await cls.get_assistant_llm()
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
                await cls.update_assistant_llm(assistant_llm)

        elif model.model_type == LLMModelType.EMBEDDING.value:
            knowledge_llm = cls.get_knowledge_llm()
            if not knowledge_llm.embedding_model_id:
                knowledge_llm.embedding_model_id = model.id
                await cls.update_knowledge_llm(knowledge_llm)

        elif model.model_type == LLMModelType.TTS.value:
            workbench_llm = await cls.get_workbench_llm()
            if not workbench_llm.tts_model or not workbench_llm.tts_model.id:
                workbench_llm.tts_model = WSModel(id=str(model.id), name=model.model_name)
                await cls.update_workbench_llm(0, workbench_llm, BackgroundTasks())
        elif model.model_type == LLMModelType.ASR.value:
            workbench_llm = await cls.get_workbench_llm()
            if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
                workbench_llm.asr_model = WSModel(id=str(model.id), name=model.model_name)
                await cls.update_workbench_llm(0, workbench_llm, BackgroundTasks())

    @classmethod
    async def update_llm_server(cls, request: Request, login_user: UserPayload,
                                server: LLMServerCreateReq) -> LLMServerInfo:
        """ Update Service Provider Information """
        exist_server = await LLMDao.aget_server_by_id(server.id)
        if not exist_server:
            raise NotFoundError.http_exception()

        old_models = await LLMDao.aget_model_by_server_ids([exist_server.id])
        old_model_dict = {
            one.id: one for one in old_models
        }
        if exist_server.name != server.name:
            # If you change your name, determine if it already exists
            name_server = await LLMDao.aget_server_by_name(server.name)
            if name_server and name_server.id != server.id:
                raise ServerExistError.http_exception(f'<{server.name}>already exists')

        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.model_dump())
                # Explanation is to add a model
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
        mask_maker = JsonFieldMasker()
        exist_server.config = mask_maker.update_json_with_masked(exist_server.config, server.config)

        db_server = await LLMDao.update_server_with_models(exist_server, list(model_dict.values()))
        new_server_info = await cls.get_one_llm(db_server.id)

        # Determine if the model status needs to be re-determined
        for one in new_server_info.models:
            if one.id not in old_model_dict:
                await cls.set_default_model(one)
            # The new model, or the model name or type has changed
            if (one.id not in old_model_dict or old_model_dict[one.id].model_name != one.model_name
                    or old_model_dict[one.id].model_type != one.model_type):
                await cls.test_model_status(one, login_user)
        return new_server_info

    @classmethod
    async def update_model_online(cls, model_id: int, online: bool) -> LLMModelInfo:
        """ Update whether the model is online """
        exist_model = await LLMDao.aget_model_by_id(model_id)
        if not exist_model:
            raise NotFoundError.http_exception()
        exist_model.online = online
        await LLMDao.aupdate_model_online(exist_model.id, online)
        return LLMModelInfo(**exist_model.model_dump())

    @classmethod
    def get_knowledge_llm(cls) -> KnowledgeLLMConfig:
        """ Get the default model configuration for the knowledge base """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.KNOWLEDGE_LLM)
        if config:
            ret = json.loads(config.value)
        return KnowledgeLLMConfig(**ret)

    @classmethod
    async def aget_knowledge_llm(cls) -> KnowledgeLLMConfig:
        """ Get the default model configuration for the knowledge base """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.KNOWLEDGE_LLM)
        if config:
            ret = json.loads(config.value)
        return KnowledgeLLMConfig(**ret)

    @classmethod
    def get_knowledge_source_llm(cls, invoke_user_id: int) -> Optional[BaseChatModel]:
        """ Get the default model configuration for Knowledge Base Traceability """
        knowledge_llm = cls.get_knowledge_llm()
        # If no model is configured, usejieba
        if not knowledge_llm.source_model_id:
            return None
        return cls.get_bisheng_llm_sync(model_id=knowledge_llm.source_model_id,
                                        app_id=ApplicationTypeEnum.RAG_TRACEABILITY.value,
                                        app_name=ApplicationTypeEnum.RAG_TRACEABILITY.value,
                                        app_type=ApplicationTypeEnum.RAG_TRACEABILITY,
                                        user_id=invoke_user_id)

    @classmethod
    async def get_knowledge_source_llm_async(cls, invoke_user_id: int) -> Optional[BaseChatModel]:
        """ Get the default model configuration for Knowledge Base Traceability """
        knowledge_llm = await cls.aget_knowledge_llm()
        # If no model is configured, usejieba
        if not knowledge_llm.source_model_id:
            return None
        return await cls.get_bisheng_llm(model_id=knowledge_llm.source_model_id,
                                        app_id=ApplicationTypeEnum.RAG_TRACEABILITY.value,
                                        app_name=ApplicationTypeEnum.RAG_TRACEABILITY.value,
                                        app_type=ApplicationTypeEnum.RAG_TRACEABILITY,
                                        user_id=invoke_user_id)

    @classmethod
    def get_knowledge_similar_llm(cls, invoke_user_id: int) -> Optional[BaseChatModel]:
        """ Get the default model configuration for knowledge base similar questions """
        knowledge_llm = cls.get_knowledge_llm()
        # If no model is configured, usejieba
        if not knowledge_llm.qa_similar_model_id:
            return None
        return cls.get_bisheng_llm_sync(model_id=knowledge_llm.qa_similar_model_id,
                                        app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                        app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                        app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                                        user_id=invoke_user_id)

    @classmethod
    def get_knowledge_default_embedding(cls, invoke_user_id: int) -> Optional[Embeddings]:
        """ Get Knowledge Base DefaultsembeddingModels """
        knowledge_llm = cls.get_knowledge_llm()
        if not knowledge_llm.embedding_model_id:
            return None
        return cls.get_bisheng_knowledge_embedding_sync(model_id=knowledge_llm.embedding_model_id,
                                                        invoke_user_id=invoke_user_id)

    @classmethod
    async def _base_update_llm_config(cls, data: Dict, key: ConfigKeyEnum) -> Dict:
        config = await ConfigDao.aget_config(key)
        if config:
            config.value = json.dumps(data)
        else:
            config = Config(key=key.value, value=json.dumps(data, ensure_ascii=False))
        await ConfigDao.async_insert_config(config)
        return data

    @classmethod
    async def update_knowledge_llm(cls, data: KnowledgeLLMConfig) \
            -> KnowledgeLLMConfig:
        """ Update default model configuration for knowledge base """
        await cls._base_update_llm_config(data=data.model_dump(), key=ConfigKeyEnum.KNOWLEDGE_LLM)
        return data

    @classmethod
    async def get_assistant_llm(cls) -> AssistantLLMConfig:
        """ Get the default model configuration related to the assistant """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.ASSISTANT_LLM)
        if config:
            ret = json.loads(config.value)
        return AssistantLLMConfig(**ret)

    @classmethod
    def sync_get_assistant_llm(cls) -> AssistantLLMConfig:
        """ Get the default model configuration related to the assistant """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.ASSISTANT_LLM)
        if config:
            ret = json.loads(config.value)
        return AssistantLLMConfig(**ret)

    @classmethod
    async def update_assistant_llm(cls, data: AssistantLLMConfig) \
            -> AssistantLLMConfig:
        """ Update default model configurations related to the assistant """
        await cls._base_update_llm_config(data=data.model_dump(), key=ConfigKeyEnum.ASSISTANT_LLM)
        return data

    @classmethod
    async def get_evaluation_llm(cls) -> EvaluationLLMConfig:
        """ Get the default model configuration for the evaluation feature """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.EVALUATION_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    def sync_get_evaluation_llm(cls) -> EvaluationLLMConfig:
        """ Get the default model configuration for the evaluation feature """
        ret = {}
        config = ConfigDao.get_config(ConfigKeyEnum.EVALUATION_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    async def get_evaluation_llm_object(cls, invoke_user_id: int) -> BaseChatModel:
        evaluation_llm = await cls.get_evaluation_llm()
        if not evaluation_llm.model_id:
            raise Exception('Evaluation model is not configured')
        return await cls.get_bisheng_llm(model_id=evaluation_llm.model_id,
                                         app_id=ApplicationTypeEnum.EVALUATION.value,
                                         app_name=ApplicationTypeEnum.EVALUATION.value,
                                         app_type=ApplicationTypeEnum.EVALUATION,
                                         user_id=invoke_user_id)

    @classmethod
    async def get_bisheng_llm(cls, **kwargs) -> BaseChatModel:
        """ Initialize LiftedllmConversation Model """
        return await BishengLLM.get_bisheng_llm(**kwargs)

    @classmethod
    def get_bisheng_llm_sync(cls, **kwargs) -> BaseChatModel:
        """ Initialize LiftedllmConversation Model """
        return BishengLLM(**kwargs)

    @classmethod
    async def get_bisheng_linsight_llm(cls, invoke_user_id: int, **kwargs) -> BaseChatModel:
        return await BishengLLM.get_bisheng_llm(app_id=ApplicationTypeEnum.LINSIGHT.value,
                                                app_name=ApplicationTypeEnum.LINSIGHT.value,
                                                app_type=ApplicationTypeEnum.LINSIGHT,
                                                user_id=invoke_user_id,
                                                **kwargs)

    @classmethod
    async def get_bisheng_rerank(cls, **kwargs) -> BaseDocumentCompressor:
        return await BishengRerank.get_bisheng_rerank(**kwargs)

    @classmethod
    def get_bisheng_rerank_sync(cls, **kwargs) -> BaseDocumentCompressor:
        return BishengRerank(**kwargs)

    @classmethod
    async def get_bisheng_embedding(cls, **kwargs) -> Embeddings:
        """ Initialize LiftedembeddingModels """
        return await BishengEmbedding.get_bisheng_embedding(**kwargs)

    @classmethod
    def get_bisheng_embedding_sync(cls, **kwargs) -> Embeddings:
        """ Initialize LiftedembeddingModels """
        return BishengEmbedding(**kwargs)

    @classmethod
    async def get_bisheng_daily_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """ Get dailyembeddingModels """
        return await cls.get_bisheng_embedding(model_id=model_id,
                                               app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                                               app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                                               app_type=ApplicationTypeEnum.DAILY_CHAT,
                                               user_id=invoke_user_id)

    @classmethod
    async def get_bisheng_linsight_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """ Get Ideas DefaultembeddingModels """
        return await cls.get_bisheng_embedding(model_id=model_id,
                                               app_id=ApplicationTypeEnum.LINSIGHT.value,
                                               app_name=ApplicationTypeEnum.LINSIGHT.value,
                                               app_type=ApplicationTypeEnum.LINSIGHT,
                                               user_id=invoke_user_id)

    @classmethod
    async def get_bisheng_knowledge_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """ Get Knowledge Base DefaultsembeddingModels """
        return await cls.get_bisheng_embedding(model_id=model_id,
                                               app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                               app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                               app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                                               user_id=invoke_user_id)

    @classmethod
    def get_bisheng_knowledge_embedding_sync(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """ Get Knowledge Base DefaultsembeddingModels """
        return cls.get_bisheng_embedding_sync(model_id=model_id,
                                              app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                              app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
                                              app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
                                              user_id=invoke_user_id)

    @classmethod
    async def get_bisheng_asr(cls, **kwargs) -> BishengASR:
        """ Initialize LiftedasrModels """
        return await BishengASR.get_bisheng_asr(**kwargs)

    @classmethod
    async def get_bisheng_tts(cls, **kwargs) -> BishengTTS:
        """ Initialize LiftedttsModels """
        return await BishengTTS.get_bisheng_tts(**kwargs)

    @classmethod
    async def update_evaluation_llm(cls, data: EvaluationLLMConfig) \
            -> EvaluationLLMConfig:
        """ Update default model configuration for review feature """
        await cls._base_update_llm_config(data=data.model_dump(), key=ConfigKeyEnum.EVALUATION_LLM)
        return data

    @classmethod
    async def update_workflow_llm(cls, data: EvaluationLLMConfig) -> EvaluationLLMConfig:
        """ Update workflow Default Model Configuration for """
        await cls._base_update_llm_config(data=data.model_dump(), key=ConfigKeyEnum.WORKFLOW_LLM)
        return data

    @classmethod
    async def get_workflow_llm(cls) -> EvaluationLLMConfig:
        """ Get the default model configuration for the evaluation feature """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.WORKFLOW_LLM)
        if config:
            ret = json.loads(config.value)
        return EvaluationLLMConfig(**ret)

    @classmethod
    async def get_assistant_llm_list(cls, request: Request, login_user: UserPayload) -> List[LLMServerInfo]:
        """ Get a list of optional models for the assistant """
        assistant_llm = await cls.get_assistant_llm()
        if not assistant_llm.llm_list:
            return []
        model_list = await LLMDao.aget_model_by_ids([one.model_id for one in assistant_llm.llm_list])
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
                model_dict[one.server_id].insert(0, LLMModelInfo(**one.model_dump(exclude={'config'})))
                continue
            model_dict[one.server_id].append(LLMModelInfo(**one.model_dump(exclude={'config'})))
        server_list = await LLMDao.aget_server_by_ids(list(model_dict.keys()))

        ret = []
        for one in server_list:
            if one.id == default_server:
                ret.insert(0, LLMServerInfo(**one.model_dump(exclude={'config'}), models=model_dict[one.id]))
                continue
            ret.append(LLMServerInfo(**one.model_dump(exclude={'config'}), models=model_dict[one.id]))

        return ret

    @classmethod
    async def update_workbench_llm(cls, invoke_user_id: int, config_obj: WorkbenchModelConfig,
                                   background_tasks: BackgroundTasks):
        """
        Update Invisible Model Configuration
        :param invoke_user_id:
        :param config_obj:
        :param background_tasks:
        :return:
        """
        # Delay imports to avoid looping imports
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery

        config = await ConfigDao.aget_config(ConfigKeyEnum.LINSIGHT_LLM)
        if not config:
            config = Config(key=ConfigKeyEnum.LINSIGHT_LLM.value, value='{}')

        if config_obj.embedding_model:
            # Determine consistency
            config_old_obj = WorkbenchModelConfig(**json.loads(config.value)) if config else WorkbenchModelConfig()
            if (config_obj.embedding_model.id and config_old_obj.embedding_model is None or
                    config_obj.embedding_model.id != config_old_obj.embedding_model.id):
                embeddings = await cls.get_bisheng_embedding(model_id=config_obj.embedding_model.id,
                                                             app_id=ApplicationTypeEnum.LINSIGHT.value,
                                                             app_name=ApplicationTypeEnum.LINSIGHT.value,
                                                             app_type=ApplicationTypeEnum.LINSIGHT,
                                                             user_id=invoke_user_id)
                try:
                    await embeddings.aembed_query("test")
                except Exception as e:
                    raise Exception(f"EmbeddingModel initialization failed: {str(e)}")
                from bisheng.linsight.domain.services.sop_manage import SOPManageService

                background_tasks.add_task(SOPManageService.rebuild_sop_vector_store_task, embeddings)

                # Update Personal Knowledge Base
                # 1.Upgrading alltypeare2(Private Repository)right of privacyknowledgeStatus and Model
                private_knowledges = await KnowledgeDao.aget_all_knowledge(
                    knowledge_type=KnowledgeTypeEnum.PRIVATE
                )

                updated_count = 0
                for knowledge in private_knowledges:
                    # Update status is rebuilding, model is newmodel_id
                    knowledge.state = KnowledgeState.REBUILDING.value
                    knowledge.model = config_obj.embedding_model.id
                    await KnowledgeDao.aupdate_one(knowledge)
                    updated_count += 1

                    # 3. For eachknowledgeStart asynchronous task
                    rebuild_knowledge_celery.delay(knowledge.id, int(knowledge.model), invoke_user_id)
                    logger.info(
                        f"Started rebuild task for knowledge_id={knowledge.id} with model_id={knowledge.model}")

                logger.info(
                    f"Updated {updated_count} private knowledge bases to use new embedding model {config_obj.embedding_model.id}")

        config.value = json.dumps(config_obj.model_dump(), ensure_ascii=False)

        await ConfigDao.async_insert_config(config)

        return config_obj

    @classmethod
    async def get_workbench_llm(cls) -> WorkbenchModelConfig:
        """
        Get Workbench Model Configuration
        :return:
        """
        ret = {}
        config = await ConfigDao.aget_config(ConfigKeyEnum.LINSIGHT_LLM)
        if config:
            ret = json.loads(config.value)
        return WorkbenchModelConfig(**ret)

    @classmethod
    async def invoke_workbench_asr(cls, login_user: UserPayload, file: UploadFile) -> str:
        """ Call the workbench'sasrModels Convert Voice to Text """
        if not file:
            raise ServerError.http_exception("no file upload")
        workbench_llm = await cls.get_workbench_llm()
        if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
            raise NoAsrModelConfigError.http_exception()
        model_info = await LLMDao.aget_model_by_id(int(workbench_llm.asr_model.id))
        if not model_info:
            raise AsrModelConfigDeletedError.http_exception()
        asr_client = await cls.get_bisheng_asr(model_id=int(workbench_llm.asr_model.id),
                                               app_id=ApplicationTypeEnum.ASR.value,
                                               app_name=ApplicationTypeEnum.ASR.value,
                                               app_type=ApplicationTypeEnum.ASR,
                                               user_id=login_user.user_id)
        return await asr_client.ainvoke(file.file)

    @classmethod
    async def invoke_workbench_tts(cls, login_user: UserPayload, text: str) -> str:
        """
        Call the workbench'sttsModels Convert text to speech
        :return: minioPath to
        """

        workbench_llm = await cls.get_workbench_llm()

        redis_client = await get_redis_client()

        if not workbench_llm.tts_model or not workbench_llm.tts_model.id:
            raise NoTtsModelConfigError.http_exception()
        model_info = await LLMDao.aget_model_by_id(model_id=int(workbench_llm.tts_model.id))
        if not model_info:
            raise TtsModelConfigDeletedError.http_exception()

        # get from cache
        voice = model_info.config.get("voice", "default") if model_info.config else "default"
        cache_key = f"workbench_tts:{model_info.id}:{voice}:{md5_hash(text)}"
        cache_value = await redis_client.aget(cache_key)
        if cache_value:
            return cache_value

        tts_client = await cls.get_bisheng_tts(model_id=int(workbench_llm.tts_model.id),
                                               app_id=ApplicationTypeEnum.TTS.value,
                                               app_name=ApplicationTypeEnum.TTS.value,
                                               app_type=ApplicationTypeEnum.TTS,
                                               user_id=login_user.user_id)
        audio_bytes = await tts_client.ainvoke(text)
        # upload to minio
        object_name = f"tts/{generate_uuid()}.mp3"

        minio_client = await get_minio_storage()
        await minio_client.put_object(object_name=object_name, file=audio_bytes, content_type="audio/mpeg",
                                      bucket_name=minio_client.tmp_bucket)
        cache_value = await minio_client.get_share_link(object_name, bucket=minio_client.tmp_bucket)
        # The tmp bucket automatically clears files older than 7 days, so set the expiration time to 6 days
        await redis_client.aset(cache_key, cache_value, expiration=6 * 24 * 3600)
        return cache_value
