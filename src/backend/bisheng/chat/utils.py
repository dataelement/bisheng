import ast
import json
import re
from enum import Enum
from typing import Dict, List
from urllib.parse import unquote, urlparse

from fastapi import WebSocket
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema.document import Document
from loguru import logger

from bisheng.api.v1.schemas import ChatMessage
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.interface.utils import try_setting_streaming_options
from bisheng.llm.domain.services import LLMService
from bisheng.processing.base import get_result_and_steps


class SourceType(Enum):
    """
    source type
    """
    NOT_SUPPORT = 0  # Traceability is not supported
    FILE = 1  # Trace back to the source file to supportbboxin that form.
    NO_PERMISSION = 2  # No permission to access traceability information
    LINK = 3  # LinkedchunkContents
    QA = 4  # HitsQAThe knowledge base upon


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


prompt_template = '''Analyze givenQuestionEkstrakQuestionContained inKeyWords, output list format

Examples:
Question: The current ratios of Damon over the past three years are as follows:2021Year:3.74x2020Year:2.82x2019Year:2.05x
KeyWords: ['Past three years', 'Current ratio', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}'''


def extract_answer_keys(answer, llm):
    """
    EkstrakanswerKeywords in
    """
    llm_chain = None
    if llm:
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords_str = re.sub('<think>.*</think>', '', keywords_str, flags=re.S).strip()
        keywords = ast.literal_eval(keywords_str[9:])
    except Exception:
        import jieba.analyse
        logger.warning(f'llm extract_not_support, change to jieba')
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords


async def extract_answer_keys_async(answer, llm):
    """
    EkstrakanswerKeywords in
    """
    llm_chain = None
    if llm:
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = await llm_chain.arun(answer)
        keywords_str = re.sub('<think>.*</think>', '', keywords_str, flags=re.S).strip()
        keywords = ast.literal_eval(keywords_str[9:])
    except Exception:
        import jieba.analyse
        logger.warning(f'llm extract_not_support, change to jieba')
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords


def sync_judge_source(result, source_document, chat_id, extra: Dict):
    source = SourceType.NOT_SUPPORT.value
    if isinstance(result, Document):
        # ReturnsDocument
        metadata = result.metadata
        question = result.page_content
        result = json.loads(metadata.get('extra', '{}')).get('answer')
        if result:
            source = SourceType.QA.value
            extra.update({
                'qa': question,
                'url': json.loads(metadata.get('extra', '{}')).get('url')
            })
            return source, result
        source_document = [source_document]
    if source_document and chat_id:
        if any(not doc.metadata.get('right', True) for doc in source_document):
            source = SourceType.NO_PERMISSION.value
        elif all(
                doc.metadata.get('user_metadata') and doc.metadata.get('user_metadata', {}).get('url')
                for doc in source_document):
            source = SourceType.LINK.value
            repeat_doc = {}
            doc = []
            # The source document should be de-emphasized and the original order cannot be changed.
            for one in source_document:
                title = one.metadata.get('source') or one.metadata.get('document_name')
                url = one.metadata.get('user_metadata', {}).get('url')
                repeat_key = (title, url)
                # Repeatedly discarded, do not return
                if repeat_doc.get(repeat_key):
                    continue
                doc.append({'title': title, 'url': url})
                repeat_doc[repeat_key] = 1
            extra.update({'doc': doc})
        else:
            source = SourceType.FILE.value

            # Determine if all files are in the Knowledge Base, If one is not, traceability is not supported
            for one in source_document:
                # If there is no knowledge baseidand documentsiddoes not support traceability
                if not one.metadata.get('knowledge_id') or not one.metadata.get('document_id'):
                    source = SourceType.NOT_SUPPORT.value
                    break
                # Knowledge Base Under Judgmentidand documentsidWhether it is in numeric format, because temporary documents uploaded by the workflow are alsoknowledge_idand documentsid
                try:
                    int(one.metadata.get('knowledge_id'))
                    int(one.metadata.get('file_id') or one.metadata.get('document_id'))
                except Exception:
                    source = SourceType.NOT_SUPPORT.value
                    break

    return source, result


async def judge_source(result, source_document, chat_id, extra: Dict):
    return sync_judge_source(result, source_document, chat_id, extra)


def sync_process_source_document(source_document: List[Document], chat_id, message_id, answer):
    if not source_document or not message_id:
        return

    message_info = ChatMessageDao.get_message_by_id(message_id)
    if not message_info:
        return
    # Use a large model for keyword extraction, and configure a temporary solution for the model
    llm = LLMService.get_knowledge_source_llm(message_info.user_id)

    answer_keywords = extract_answer_keys(answer, llm)

    batch_insert = []
    for doc in source_document:
        if 'bbox' in doc.metadata:
            # Indicates support for traceability
            content = doc.page_content
            recall_chunk = RecallChunk(chat_id=chat_id,
                                       keywords=json.dumps(answer_keywords),
                                       chunk=content,
                                       file_id=doc.metadata.get('file_id') or doc.metadata.get('document_id'),
                                       meta_data=json.dumps(doc.metadata),
                                       message_id=message_id)
            batch_insert.append(recall_chunk)
    if batch_insert:
        with get_sync_db_session() as db_session:
            db_session.add_all(batch_insert)
            db_session.commit()


async def process_source_document(source_document: List[Document], chat_id, message_id, answer):
    if not source_document or not message_id:
        return

    message_info = await ChatMessageDao.aget_message_by_id(message_id)
    if not message_info:
        return
    # Use a large model for keyword extraction, and configure a temporary solution for the model
    llm = await LLMService.get_knowledge_source_llm_async(message_info.user_id)

    answer_keywords = await extract_answer_keys_async(answer, llm)

    batch_insert = []
    for doc in source_document:
        if 'bbox' in doc.metadata:
            # Indicates support for traceability
            content = doc.page_content
            recall_chunk = RecallChunk(chat_id=chat_id,
                                       keywords=json.dumps(answer_keywords),
                                       chunk=content,
                                       file_id=doc.metadata.get('file_id') or doc.metadata.get('document_id'),
                                       meta_data=json.dumps(doc.metadata),
                                       message_id=message_id)
            batch_insert.append(recall_chunk)
    if batch_insert:
        async with get_async_db_session() as db_session:
            db_session.add_all(batch_insert)
            await db_session.commit()


# Convert node data that requires additional input totweak
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
