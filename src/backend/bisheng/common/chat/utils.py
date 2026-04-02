import ast
import json
import re
from enum import Enum
from typing import Dict, List
from urllib.parse import unquote, urlparse

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.schema.document import Document
from loguru import logger

from bisheng.core.database import get_async_db_session, get_sync_db_session
from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.recall_chunk import RecallChunk
from bisheng.llm.domain.services import LLMService


class SourceType(Enum):
    """
    source type
    """

    NOT_SUPPORT = 0
    FILE = 1
    NO_PERMISSION = 2
    LINK = 3
    QA = 4


prompt_template = """Analyze givenQuestionEkstrakQuestionContained inKeyWords, output list format

Examples:
Question: The current ratios of Damon over the past three years are as follows:2021Year:3.74x2020Year:2.82x2019Year:2.05x
KeyWords: ['Past three years', 'Current ratio', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}"""


def extract_answer_keys(answer, llm):
    """
    EkstrakanswerKeywords in
    """
    llm_chain = None
    if llm:
        llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt_template))
    try:
        keywords_str = llm_chain.run(answer)
        keywords_str = re.sub("<think>.*</think>", "", keywords_str, flags=re.S).strip()
        keywords = ast.literal_eval(keywords_str[9:])
    except Exception:
        import jieba.analyse

        logger.warning("llm extract_not_support, change to jieba")
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
        keywords_str = re.sub("<think>.*</think>", "", keywords_str, flags=re.S).strip()
        keywords = ast.literal_eval(keywords_str[9:])
    except Exception:
        import jieba.analyse

        logger.warning("llm extract_not_support, change to jieba")
        keywords = jieba.analyse.extract_tags(answer, topK=100, withWeight=False)

    return keywords


def sync_judge_source(result, source_document, chat_id, extra: Dict):
    source = SourceType.NOT_SUPPORT.value
    if isinstance(result, Document):
        metadata = result.metadata
        question = result.page_content
        result = json.loads(metadata.get("extra", "{}")).get("answer")
        if result:
            source = SourceType.QA.value
            extra.update({
                "qa": question,
                "url": json.loads(metadata.get("extra", "{}")).get("url"),
            })
            return source, result
        source_document = [source_document]
    if source_document and chat_id:
        if any(not doc.metadata.get("right", True) for doc in source_document):
            source = SourceType.NO_PERMISSION.value
        elif all(
            doc.metadata.get("user_metadata") and doc.metadata.get("user_metadata", {}).get("url")
            for doc in source_document
        ):
            source = SourceType.LINK.value
            repeat_doc = {}
            doc = []
            for one in source_document:
                title = one.metadata.get("source") or one.metadata.get("document_name")
                url = one.metadata.get("user_metadata", {}).get("url")
                repeat_key = (title, url)
                if repeat_doc.get(repeat_key):
                    continue
                doc.append({"title": title, "url": url})
                repeat_doc[repeat_key] = 1
            extra.update({"doc": doc})
        else:
            source = SourceType.FILE.value
            for one in source_document:
                if not one.metadata.get("knowledge_id") or not one.metadata.get("document_id"):
                    source = SourceType.NOT_SUPPORT.value
                    break
                try:
                    int(one.metadata.get("knowledge_id"))
                    int(one.metadata.get("file_id") or one.metadata.get("document_id"))
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
    llm = LLMService.get_knowledge_source_llm(message_info.user_id)

    answer_keywords = extract_answer_keys(answer, llm)

    batch_insert = []
    for doc in source_document:
        if "bbox" in doc.metadata:
            content = doc.page_content
            recall_chunk = RecallChunk(
                chat_id=chat_id,
                keywords=json.dumps(answer_keywords),
                chunk=content,
                file_id=doc.metadata.get("file_id") or doc.metadata.get("document_id"),
                meta_data=json.dumps(doc.metadata),
                message_id=message_id,
            )
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
    llm = await LLMService.get_knowledge_source_llm_async(message_info.user_id)

    answer_keywords = await extract_answer_keys_async(answer, llm)

    batch_insert = []
    for doc in source_document:
        if "bbox" in doc.metadata:
            content = doc.page_content
            recall_chunk = RecallChunk(
                chat_id=chat_id,
                keywords=json.dumps(answer_keywords),
                chunk=content,
                file_id=doc.metadata.get("file_id") or doc.metadata.get("document_id"),
                meta_data=json.dumps(doc.metadata),
                message_id=message_id,
            )
            batch_insert.append(recall_chunk)
    if batch_insert:
        async with get_async_db_session() as db_session:
            db_session.add_all(batch_insert)
            await db_session.commit()


def process_node_data(node_data: List[Dict]) -> Dict:
    tweak = {}
    for nd in node_data:
        if nd.get("id") not in tweak:
            tweak[nd.get("id")] = {}
        if "InputFile" in nd.get("id", ""):
            file_path = nd.get("file_path")
            url_path = urlparse(file_path)
            if url_path.netloc:
                file_name = unquote(url_path.path.split("/")[-1])
            else:
                file_name = file_path.split("_", 1)[1] if "_" in file_path else ""
            nd["value"] = file_name
            tweak[nd.get("id")] = {"file_path": file_path, "value": file_name}
        elif "VariableNode" in nd.get("id", ""):
            variables = nd.get("name")
            variable_value = nd.get("value")
            variables_list = tweak[nd.get("id")].get("variables", [])
            if not variables_list:
                tweak[nd.get("id")]["variables"] = variables_list
                tweak[nd.get("id")]["variable_value"] = []
            variables_list.append(variables)
            variables_value_list = tweak[nd.get("id")].get("variable_value", [])
            variables_value_list.append(variable_value)
    return tweak
