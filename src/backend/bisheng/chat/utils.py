import json
from typing import Dict, List
from urllib.parse import unquote, urlparse

from bisheng.api.services.llm import LLMService
from bisheng.api.v1.schemas import ChatMessage
from bisheng.database.base import session_getter
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.interface.utils import try_setting_streaming_options
from bisheng.processing.base import get_result_and_steps
from bisheng.utils.logger import logger
from fastapi import WebSocket
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema.document import Document


async def process_graph(langchain_object,
                        chat_inputs: ChatMessage,
                        websocket: WebSocket,
                        flow_id: str = None,
                        chat_id: str = None,
                        **kwargs):
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
            langchain_object,
            chat_inputs.message,
            websocket=websocket,
            flow_id=flow_id,
            chat_id=chat_id,
            **kwargs)
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


def extract_answer_keys(answer, llm):
    """
    提取answer中的关键词
    """
    llm_chain = None
    if llm:
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords = eval(keywords_str[9:])
    except Exception:
        import jieba.analyse
        logger.warning(f'llm {llm} extract_not_support, change to jieba')
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
        extra.update({
            'qa': f'本答案来源于已有问答库: {question}',
            'url': json.loads(metadata.get('extra', '{}')).get('url')
        })
    elif source_document and chat_id:
        if any(not doc.metadata.get('right', True) for doc in source_document):
            source = 2
        elif all(
                doc.metadata.get('extra') and json.loads(doc.metadata.get('extra')).get('url')
                for doc in source_document):
            source = 3
            repeat_doc = {}
            doc = []
            # 来源文档做去重，不能改变原有的顺序
            for one in source_document:
                title = one.metadata.get('source')
                url = json.loads(one.metadata.get('extra', '{}')).get('url')
                repeat_key = (title, url)
                # 重复的丢掉，不返回
                if repeat_doc.get(repeat_key):
                    continue
                doc.append({'title': title, 'url': url})
                repeat_doc[repeat_key] = 1
            extra.update({'doc': doc})
        else:
            source = 1

    if source == 1:
        for doc in source_document:
            # 确保每个chunk 都可溯源
            if 'bbox' not in doc.metadata or not doc.metadata['bbox'] or not json.loads(
                    doc.metadata['bbox'])['chunk_bboxes']:
                source = 0
                break
    return source, result


async def process_source_document(source_document: List[Document], chat_id, message_id, answer):
    if not source_document:
        return

    # 使用大模型进行关键词抽取，模型配置临时方案
    llm = LLMService.get_knowledge_source_llm()

    answer_keywords = extract_answer_keys(answer, llm)

    batch_insert = []
    for doc in source_document:
        if 'bbox' in doc.metadata:
            # 表示支持溯源
            content = doc.page_content
            recall_chunk = RecallChunk(chat_id=chat_id,
                                       keywords=json.dumps(answer_keywords),
                                       chunk=content,
                                       file_id=doc.metadata.get('file_id'),
                                       meta_data=json.dumps(doc.metadata),
                                       message_id=message_id)
            batch_insert.append(recall_chunk)
    if batch_insert:
        with session_getter() as db_session:
            db_session.add_all(batch_insert)
            db_session.commit()


# 将需要额外输入的节点数据，转为tweak
def process_node_data(node_data: List[Dict]) -> Dict:
    tweak = {}
    for nd in node_data:
        if nd.get('id') not in tweak:
            tweak[nd.get('id')] = {}
        if 'InputFile' in nd.get('id', ''):
            file_path = nd.get('file_path')
            url_path = urlparse(file_path)
            if url_path.netloc:
                file_name = unquote(url_path.path.split('/')[-1])
            else:
                file_name = file_path.split('_', 1)[1] if '_' in file_path else ''
            nd['value'] = file_name
            tweak[nd.get('id')] = {'file_path': file_path, 'value': file_name}
        elif 'VariableNode' in nd.get('id', ''):
            # general key value
            variables = nd.get('name')
            variable_value = nd.get('value')
            # actual key varaialbes & variable_value
            variables_list = tweak[nd.get('id')].get('variables', [])
            if not variables_list:
                tweak[nd.get('id')]['variables'] = variables_list
                tweak[nd.get('id')]['variable_value'] = []
            variables_list.append(variables)
            # value
            variables_value_list = tweak[nd.get('id')].get('variable_value', [])
            variables_value_list.append(variable_value)
    return tweak
