from langchain_core.messages import BaseMessage,HumanMessage

from bisheng.database.models import llm_server
from bisheng.database.models.llm_server import LLMDao, LLMModelType
from bisheng.interface.embeddings.custom import BishengEmbedding
from bisheng.interface.llms.custom import BishengLLM
from bisheng.worker import bisheng_celery
from loguru import logger


@bisheng_celery.task
def check_model_status_task():
    models = LLMDao.get_all_model()
    llm_models = [one for one in models if one.model_type == LLMModelType.LLM.value]
    msg = HumanMessage(content="1+1=?")
    for model in llm_models:
        logger.debug(f'check_model_status_task llm model={model}')
        if model.online and model.check:
            try:
                result = BishengLLM(model_id=model.id).moonshot_generate(messages=[msg])
                logger.debug(f'check_model_status_task llm result={result}')
            except Exception as e:
                logger.debug(f'check_model_status_task llm exception={e}')
    embed_models = [one for one in models if one.model_type == LLMModelType.EMBEDDING.value]
    for model in embed_models:
        logger.debug(f'check_model_status_task embed model={model}')
        if model.online and model.check:
            try:
                result = BishengEmbedding(model_id=model.id).embed_documents(texts=["hello world"])
                logger.debug(f'check_model_status_task embed result={result}')
            except Exception as e:
                logger.debug(f'check_model_status_task embed exception={e}')