import json
from typing import Dict, List

from bisheng.api.v1.schemas import ChatMessage
from bisheng.database.base import get_session
from bisheng.database.models.model_deploy import ModelDeploy
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.interface.utils import try_setting_streaming_options
from bisheng.processing.base import get_result_and_steps
from bisheng.utils.logger import logger
from bisheng_langchain.chat_models import HostQwenChat
from fastapi import WebSocket
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema.document import Document
from sqlmodel import select


async def process_graph(
    langchain_object,
    chat_inputs: ChatMessage,
    websocket: WebSocket,
):
    langchain_object = try_setting_streaming_options(langchain_object, websocket)
    logger.debug('Loaded langchain object')

    if langchain_object is None:
        # Raise user facing error
        raise ValueError(
            'There was an error loading the langchain_object. Please, check all the nodes and try again.'
        )

    # Generate result and thought
    try:
        if not chat_inputs.message:
            logger.debug('No message provided')
            raise ValueError('No message provided')

        logger.debug('Generating result and thought')
        result, intermediate_steps, source_document = await get_result_and_steps(
            langchain_object, chat_inputs.message, websocket=websocket)
        logger.debug('Generated result and intermediate_steps')
        return result, intermediate_steps, source_document
    except Exception as e:
        # Log stack trace
        logger.exception(e)
        raise e


prompt_template = '''分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}'''


def extract_answer_keys(answer, extract_model, host_base_url):
    """
    提取answer中的关键词
    """
    if extract_model:
        llm = HostQwenChat(model_name=extract_model,
                           host_base_url=host_base_url,
                           max_tokens=8192,
                           temperature=0,
                           top_p=1,
                           verbose=True)
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords = eval(keywords_str[9:])
    except Exception:
        import jieba.analyse
        logger.warning(f'llm {extract_model} extract_not_support, change to jieba')
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords


async def judge_source(result, source_document, chat_id, extra: Dict):
    source = 0
    if isinstance(result, Document):
        # 返回的是Document
        metadata = result.metadata
        question = result.page_content
        result = json.loads(metadata.get('extra', '{}')).get('answer')
        source = 4
        extra.update({'qa': f'本答案来源于已有问答库: {question}'})
    elif source_document and chat_id:
        if any(not doc.metadata.get('right', True) for doc in source_document):
            source = 2
        elif all(
                doc.metadata.get('extra') and json.loads(doc.metadata.get('extra')).get('url')
                for doc in source_document):
            source = 3
            doc = [{
                'title': doc.metadata.get('source'),
                'url': json.loads(doc.metadata.get('extra', '{}')).get('url')
            } for doc in source_document]
            extra.update({'doc': [dict(s) for s in set(frozenset(d.items()) for d in doc)]})
        else:
            source = 1

    if source:
        for doc in source_document:
            # 确保每个chunk 都可溯源
            if 'bbox' not in doc.metadata or not doc.metadata['bbox']:
                source = False
    return source


async def process_source_document(source_document: List[Document], chat_id, message_id, answer):
    if not source_document:
        return

    from bisheng.settings import settings
    # 使用大模型进行关键词抽取，模型配置临时方案
    keyword_conf = settings.get_default_llm() or {}
    host_base_url = keyword_conf.get('host_base_url')
    model = keyword_conf.get('model')

    if model and not host_base_url:
        db_session = next(get_session())
        model_deploy = db_session.exec(
            select(ModelDeploy).where(ModelDeploy.model == model)).first()
        if model_deploy:
            model = model if model_deploy.status == '已上线' else None
            host_base_url = model_deploy.endpoint
        else:
            logger.error('不能使用配置模型进行关键词抽取，配置不正确')

    answer_keywords = extract_answer_keys(answer, model, host_base_url)
    for doc in source_document:
        if 'bbox' in doc.metadata:
            # 表示支持溯源
            db_session = next(get_session())
            content = doc.page_content
            recall_chunk = RecallChunk(chat_id=chat_id,
                                       keywords=json.dumps(answer_keywords),
                                       chunk=content,
                                       file_id=doc.metadata.get('file_id'),
                                       meta_data=json.dumps(doc.metadata),
                                       message_id=message_id)
            db_session.add(recall_chunk)
            db_session.commit()
            db_session.refresh(recall_chunk)
