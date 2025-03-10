import json
import re
import time
from typing import Any, Dict, List, Optional

import requests
from bisheng.api.errcode.knowledge import KnowledgeSimilarError
from bisheng.api.services.handler.impl.xls_split_handle import XlsSplitHandle
from bisheng.api.services.handler.impl.xlsx_split_handle import XlsxSplitHandle
from bisheng.api.services.llm import LLMService
from bisheng.api.utils import md5_hash
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import file_download
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileStatus, ParseType, QAKnoweldgeDao,
                                                    QAKnowledge, QAKnowledgeUpsert)
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils.embedding import decide_embeddings
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.rag.extract_info import extract_title
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from langchain.embeddings.base import Embeddings
from langchain.schema.document import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores.base import VectorStore
from langchain_community.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                                  UnstructuredMarkdownLoader,
                                                  UnstructuredPowerPointLoader,
                                                  UnstructuredWordDocumentLoader)
from loguru import logger
from pymilvus import Collection
from sqlalchemy import func, or_
from sqlmodel import select

filetype_load_map = {
    'txt': TextLoader,
    'pdf': PyPDFLoader,
    'html': BSHTMLLoader,
    'md': UnstructuredMarkdownLoader,
    'docx': UnstructuredWordDocumentLoader,
    'pptx': UnstructuredPowerPointLoader,
}

split_handles = [
    XlsxSplitHandle(),
    XlsSplitHandle(),
]


class KnowledgeUtils:
    # 用来区分chunk和自动生产的总结内容  格式如：文件名\n文档总结\n--------\n chunk内容
    chunk_split = '\n----------\n'

    @classmethod
    def get_preview_cache_key(cls, knowledge_id: int, file_path: str) -> str:
        md5_value = md5_hash(file_path)
        return f'preview_file_chunk:{knowledge_id}:{md5_value}'

    @classmethod
    def save_preview_cache(cls,
                           cache_key,
                           mapping: dict = None,
                           chunk_index: int = 0,
                           value: dict = None):
        if mapping:
            for key, val in mapping.items():
                mapping[key] = json.dumps(val)
            redis_client.hset(cache_key, mapping=mapping)
        else:
            redis_client.hset(cache_key, key=chunk_index, value=json.dumps(value))

    @classmethod
    def delete_preview_cache(cls, cache_key, chunk_index: int = None):
        if chunk_index is None:
            redis_client.delete(cache_key)
            redis_client.delete(f'{cache_key}_parse_type')
            redis_client.delete(f'{cache_key}_file_path')
            redis_client.delete(f'{cache_key}_partitions')
        else:
            redis_client.hdel(cache_key, chunk_index)

    @classmethod
    def get_preview_cache(cls, cache_key, chunk_index: int = None) -> dict:
        if chunk_index is None:
            all_chunk_info = redis_client.hgetall(cache_key)
            for key, value in all_chunk_info.items():
                all_chunk_info[key] = json.loads(value)
            return all_chunk_info
        else:
            chunk_info = redis_client.hget(cache_key, chunk_index)
            if chunk_info:
                chunk_info = json.loads(chunk_info)
            return chunk_info


def process_file_task(knowledge: Knowledge,
                      db_files: List[KnowledgeFile],
                      separator: List[str],
                      separator_rule: List[str],
                      chunk_size: int,
                      chunk_overlap: int,
                      callback_url: str = None,
                      extra_metadata: str = None,
                      preview_cache_keys: List[str] = None):
    """ 处理知识文件任务 """
    try:
        index_name = knowledge.index_name or knowledge.collection_name
        addEmbedding(knowledge.collection_name,
                     index_name,
                     knowledge.id,
                     knowledge.model,
                     separator,
                     separator_rule,
                     chunk_size,
                     chunk_overlap,
                     db_files,
                     callback_url,
                     extra_metadata,
                     preview_cache_keys=preview_cache_keys)
    except Exception as e:
        logger.exception('process_file_task error')
        new_files = KnowledgeFileDao.select_list([file.id for file in db_files])
        new_files_map = {file.id: file for file in new_files}
        for file in db_files:
            if new_files_map[file.id].status == KnowledgeFileStatus.PROCESSING.value:
                file.status = KnowledgeFileStatus.FAILED.value
                file.remark = str(e)[:500]
                KnowledgeFileDao.update(file)
        logger.info('update files failed status over')
        raise e


def delete_knowledge_file_vectors(file_ids: List[int], clear_minio: bool = True):
    """ 删除知识文件信息 """
    knowledge_files = KnowledgeFileDao.select_list(file_ids=file_ids)

    knowledge_ids = [file.knowledge_id for file in knowledge_files]
    knowledges = KnowledgeDao.get_list_by_ids(knowledge_ids)
    knowledgeid_dict = {knowledge.id: knowledge for knowledge in knowledges}
    embeddings = FakeEmbedding()
    collection_ = set([knowledge.collection_name for knowledge in knowledges])

    if len(collection_) > 1:
        raise ValueError('不支持多个collection')
    collection_name = collection_.pop()
    # 处理vectordb
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    try:
        if isinstance(vectore_client.col, Collection):
            pk = vectore_client.col.query(expr=f'file_id in {file_ids}',
                                          output_fields=['pk'],
                                          timeout=10)
        else:
            pk = []
    except Exception:
        # 重试一次
        logger.error('timeout_except')
        vectore_client.close_connection(vectore_client.alias)
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
        pk = vectore_client.col.query(expr=f'file_id in {file_ids}',
                                      output_fields=['pk'],
                                      timeout=10)
    logger.info('query_milvus pk={}', pk)
    if pk:
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}", timeout=10)
        logger.info(f'act=delete_vector file_id={file_ids} res={res}')
    vectore_client.close_connection(vectore_client.alias)

    for file in knowledge_files:
        # mino
        if clear_minio:
            # minio
            minio = MinioClient()
            minio.delete_minio(str(file.id))
            if file.object_name:
                minio.delete_minio(str(file.object_name))

        knowledge = knowledgeid_dict.get(file.knowledge_id)
        # elastic
        index_name = knowledge.index_name or collection_name
        esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

        if esvectore_client:
            res = esvectore_client.client.delete_by_query(
                index=index_name, query={'match': {
                    'metadata.file_id': file.id
                }})
            logger.info(f'act=delete_es file_id={file.id} res={res}')
    return True


def decide_vectorstores(collection_name: str, vector_store: str,
                        embedding: Embeddings) -> VectorStore:
    """vector db"""
    vector_config = settings.get_knowledge().get('vectorstores').get(vector_store)
    if not vector_config:
        # 无相关配置
        return None

    param = {'embedding': embedding}
    if vector_store == 'ElasticKeywordsSearch':
        param['index_name'] = collection_name
        if isinstance(vector_config['ssl_verify'], str):
            vector_config['ssl_verify'] = eval(vector_config['ssl_verify'])
    elif vector_store == 'Milvus':
        param['collection_name'] = collection_name
        vector_config.pop('partition_suffix', '')
        vector_config.pop('is_partition', '')
    else:
        # 适配其他的vector
        collection_name = vector_config.pop('collection_or_index_name', '')
        vector_config[collection_name] = collection_name

    param.update(vector_config)
    class_obj = import_vectorstore(vector_store)
    return instantiate_vectorstore(vector_store, class_object=class_obj, params=param)


def decide_knowledge_llm() -> Any:
    """ 获取用来总结知识库chunk的 llm对象 """
    # 获取llm配置
    knowledge_llm = LLMService.get_knowledge_llm()
    if not knowledge_llm.extract_title_model_id:
        # 无相关配置
        return None

    # 获取llm对象
    return LLMService.get_bisheng_llm(model_id=knowledge_llm.extract_title_model_id)


def addEmbedding(collection_name: str,
                 index_name: str,
                 knowledge_id: int,
                 model: str,
                 separator: List[str],
                 separator_rule: List[str],
                 chunk_size: int,
                 chunk_overlap: int,
                 knowledge_files: List[KnowledgeFile],
                 callback: str = None,
                 extra_meta: str = None,
                 preview_cache_keys: List[str] = None):
    """  将文件加入到向量和es库内  """

    logger.info('start process files')
    minio_client = MinioClient()
    embeddings = decide_embeddings(model)

    logger.info('start init Milvus')
    vector_client = decide_vectorstores(collection_name, 'Milvus', embeddings)

    logger.info('start init ElasticKeywordsSearch')
    es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

    for index, db_file in enumerate(knowledge_files):
        # 尝试从缓存中获取文件的分块
        preview_cache_key = None
        if preview_cache_keys:
            preview_cache_key = preview_cache_keys[index] if index < len(
                preview_cache_keys) else None
        try:
            logger.info(f'process_file_begin file_id={db_file.id} file_name={db_file.file_name}')
            add_file_embedding(vector_client,
                               es_client,
                               minio_client,
                               db_file,
                               separator,
                               separator_rule,
                               chunk_size,
                               chunk_overlap,
                               extra_meta=extra_meta,
                               preview_cache_key=preview_cache_key)
            db_file.status = KnowledgeFileStatus.SUCCESS.value
        except Exception as e:
            logger.exception(
                f'process_file_fail file_id={db_file.id} file_name={db_file.file_name}')
            db_file.status = KnowledgeFileStatus.FAILED.value
            db_file.remark = str(e)[:500]
        finally:
            logger.info(f'process_file_end file_id={db_file.id} file_name={db_file.file_name}')
            KnowledgeFileDao.update(db_file)
            if callback:
                inp = {
                    'file_name': db_file.file_name,
                    'file_status': db_file.status,
                    'file_id': db_file.id,
                    'error_msg': db_file.remark
                }
                requests.post(url=callback, json=inp, timeout=3)


def add_file_embedding(vector_client,
                       es_client,
                       minio_client,
                       db_file: KnowledgeFile,
                       separator: List[str],
                       separator_rule: List[str],
                       chunk_size: int,
                       chunk_overlap: int,
                       extra_meta: str = None,
                       preview_cache_key: str = None):
    # download original file
    logger.info(f'start download original file={db_file.id} file_name={db_file.file_name}')
    if db_file.object_name.startswith('tmp'):
        file_url = minio_client.get_share_link(db_file.object_name, minio_client.tmp_bucket)
        filepath, _ = file_download(file_url)

        # 如果是tmp开头的bucket需要重新保存原始文件到minio的正式bucket
        file_type = db_file.file_name.rsplit('.', 1)[-1]
        db_file.object_name = f'original/{db_file.id}.{file_type}'
        res = minio_client.upload_minio(db_file.object_name, filepath)
        logger.info(f'upload original file {db_file.id} file_name={db_file.file_name} res={res}')
    # 如果是tmp开头的bucket需要重新保存原始文件到minio的正式bucket
    else:
        file_url = minio_client.get_share_link(db_file.object_name)
        filepath, _ = file_download(file_url)

    if not vector_client:
        raise ValueError('vector db not found, please check your milvus config')
    if not es_client:
        raise ValueError('es not found, please check your es config')

    # extract text from file
    texts, metadatas, parse_type, partitions = read_chunk_text(filepath, db_file.file_name,
                                                               separator, separator_rule,
                                                               chunk_size, chunk_overlap)
    if len(texts) == 0:
        raise ValueError('文件解析为空')
    # 缓存中有数据则用缓存中的数据去入库，因为是用户在界面编辑过的
    if preview_cache_key:
        all_chunk_info = KnowledgeUtils.get_preview_cache(preview_cache_key)
        if all_chunk_info:
            logger.info(f'get_preview_cache file={db_file.id} file_name={db_file.file_name}')
            texts, metadatas = [], []
            for key, val in all_chunk_info.items():
                texts.append(val['text'])
                metadatas.append(val['metadata'])
    for index, one in enumerate(texts):
        if len(one) > 10000:
            raise ValueError('分段结果超长，请尝试在自定义策略中使用更多切分符（例如 \n）进行切分')
        # 入库时 拼接文件名和文档摘要
        texts[
            index] = f"{metadatas[index]['source']}\n{metadatas[index]['title']}{KnowledgeUtils.chunk_split}{one}"

    db_file.parse_type = parse_type
    # 存储ocr识别后的partitions结果
    if partitions:
        partition_data = json.dumps(partitions, ensure_ascii=False).encode('utf-8')
        minio_client.upload_minio_data(f'partitions/{db_file.id}.json', partition_data,
                                       len(partition_data), 'application/json')
        db_file.bbox_object_name = f'partitions/{db_file.id}.json'

    # 溯源必须依赖minio, 后期替换更通用的oss, 将转换为pdf的文件传到minio
    minio_client.upload_minio(str(db_file.id), filepath)

    logger.info(f'chunk_split file={db_file.id} file_name={db_file.file_name} size={len(texts)}')
    for metadata in metadatas:
        metadata.update({
            'file_id': db_file.id,
            'knowledge_id': f'{db_file.knowledge_id}',
            'extra': extra_meta or ''
        })

    logger.info(f'add_vectordb file={db_file.id} file_name={db_file.file_name}')
    # 存入milvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f'add_es file={db_file.id} file_name={db_file.file_name}')
    # 存入es
    es_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f'add_complete file={db_file.id} file_name={db_file.file_name}')
    if preview_cache_key:
        KnowledgeUtils.delete_preview_cache(preview_cache_key)


def add_text_into_vector(vector_client, es_client, db_file: KnowledgeFile, texts: List[str],
                         metadatas: List[dict]):
    logger.info(f'add_vectordb file={db_file.id} file_name={db_file.file_name}')
    # 存入milvus
    vector_client.add_texts(texts=texts, metadatas=metadatas)

    logger.info(f'add_es file={db_file.id} file_name={db_file.file_name}')
    # 存入es
    es_client.add_texts(texts=texts, metadatas=metadatas)


def parse_partitions(partitions: List[Any]) -> Dict:
    """ 解析生成bbox和文本的对应关系 """
    if not partitions:
        return {}
    res = {}
    for part_index, part in enumerate(partitions):
        bboxes = part['metadata']['extra_data']['bboxes']
        indexes = part['metadata']['extra_data']['indexes']
        pages = part['metadata']['extra_data']['pages']
        text = part['text']
        for index, bbox in enumerate(bboxes):
            key = f'{pages[index]}-' + '-'.join([str(int(one)) for one in bbox])
            if index == len(bboxes) - 1:
                val = text[indexes[index][0]:]
            else:
                val = text[indexes[index][0]:indexes[index][1] + 1]
            res[key] = {'text': val, 'type': part['type'], 'part_id': part_index}
    return res


def read_chunk_text(input_file, file_name, separator: List[str], separator_rule: List[str],
                    chunk_size: int, chunk_overlap: int) -> (List[str], List[dict], str, Any):
    """
     0：chunks text
     1：chunks metadata
     2：parse_type: uns or local
     3: ocr bbox data: maybe None
    """
    # 获取文档总结标题的llm
    try:
        llm = decide_knowledge_llm()
    except Exception as e:
        logger.exception('knowledge_llm_error:')
        raise Exception(f'文档知识库总结模型已失效，请前往模型管理-系统模型设置中进行配置。{str(e)}')
    text_splitter = ElemCharacterTextSplitter(separators=separator,
                                              separator_rule=separator_rule,
                                              chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap,
                                              is_separator_regex=True)
    # 加载文档内容
    logger.info(f'start_file_loader file_name={file_name}')
    parse_type = ParseType.LOCAL.value
    # excel 文件的处理单独出来
    file_type = file_name.split('.')[-1]
    partitions = []
    texts = []
    if file_type in ['xls', 'xlsx']:
        for handle in split_handles:
            if handle.support(file_name, input_file):
                result = handle.handle(file_name, separator, False, chunk_size, input_file, None)
                for content in result:
                    if content:
                        for paragraph in content:
                            texts.append(
                                Document(page_content=paragraph.get('content'), metadata={}))

    else:
        if not settings.get_knowledge().get('unstructured_api_url'):
            file_type = file_name.split('.')[-1]
            if file_type not in filetype_load_map:
                raise Exception('类型不支持')
            loader = filetype_load_map[file_type](file_path=input_file)
            documents = loader.load()
        else:
            loader = ElemUnstructuredLoader(
                file_name,
                input_file,
                unstructured_api_url=settings.get_knowledge().get('unstructured_api_url'))
            documents = loader.load()
            parse_type = ParseType.UNS.value
            partitions = loader.partitions
            partitions = parse_partitions(partitions)

        logger.info(f'start_extract_title file_name={file_name}')
        if llm:
            t = time.time()
            for one in documents:
                # 配置了相关llm的话，就对文档做总结
                title = extract_title(llm, one.page_content)
                one.metadata['title'] = title
            logger.info('file_extract_title=success timecost={}', time.time() - t)

        logger.info(f'start_split_text file_name={file_name}')
        texts = text_splitter.split_documents(documents)
    raw_texts = [t.page_content for t in texts]
    logger.info(f'start_process_metadata file_name={file_name}')
    metadatas = [{
        'bbox':
        json.dumps({'chunk_bboxes': t.metadata.get('chunk_bboxes', '')}),
        'page':
        t.metadata['chunk_bboxes'][0].get('page')
        if t.metadata.get('chunk_bboxes', None) else t.metadata.get('page', 0),
        'source':
        file_name,
        'title':
        t.metadata.get('title', ''),
        'chunk_index':
        t_index,
        'extra':
        ''
    } for t_index, t in enumerate(texts)]
    logger.info(f'file_chunk_over file_name=={file_name}')
    return raw_texts, metadatas, parse_type, partitions


def text_knowledge(db_knowledge: Knowledge, db_file: KnowledgeFile, documents: List[Document]):
    """使用text 导入knowledge"""
    embeddings = decide_embeddings(db_knowledge.model)
    vectore_client = decide_vectorstores(db_knowledge.collection_name, 'Milvus', embeddings)
    logger.info('vector_init_conn_done milvus={}', db_knowledge.collection_name)
    index_name = db_knowledge.index_name or db_knowledge.collection_name
    es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

    separator = '\n\n'
    chunk_size = 1000
    chunk_overlap = 100

    text_splitter = CharacterTextSplitter(separator=separator,
                                          chunk_size=chunk_size,
                                          chunk_overlap=chunk_overlap,
                                          add_start_index=True)

    texts = text_splitter.split_documents(documents)

    logger.info(f'chunk_split knowledge_id={db_knowledge.id} size={len(texts)}')

    # 存储 mysql
    file_name = documents[0].metadata.get('source')
    db_file.file_name = file_name
    with session_getter() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)
    result = db_file.model_dump()
    try:
        metadata = [{
            'file_id': db_file.id,
            'knowledge_id': f'{db_knowledge.id}',
            'page': doc.metadata.pop('page', 1),
            'source': doc.metadata.pop('source', ''),
            'bbox': doc.metadata.pop('bbox', ''),
            'extra': json.dumps(doc.metadata, ensure_ascii=False),
            'title': '',
            'chunk_index': index
        } for index, doc in enumerate(documents)]
        vectore_client.add_texts(texts=[t.page_content for t in texts], metadatas=metadata)

        # 存储es
        if es_client:
            es_client.add_texts(texts=[t.page_content for t in texts], metadatas=metadata)
        db_file.status = 2
        result['status'] = 2
        with session_getter() as session:
            session.add(db_file)
            session.commit()
    except Exception as e:
        logger.error(e)
        setattr(db_file, 'status', 3)
        setattr(db_file, 'remark', str(e)[:500])
        with session_getter() as session:
            session.add(db_file)
            session.commit()
        result['status'] = 3
        result['remark'] = str(e)[:500]
    return result


def retry_files(db_files: List[KnowledgeFile], new_files: Dict):
    if not db_files:
        return
    try:
        delete_knowledge_file_vectors(file_ids=list(new_files.keys()), clear_minio=False)
    except Exception as e:
        logger.exception(e)
        for file in db_files:
            file.status = 3
            file.remark = str(e)[:500]
            KnowledgeFileDao.update(file)
        return

    for file in db_files:
        fake_req = FileProcessBase(**json.loads(file.split_rule))
        try:
            knowledge = KnowledgeDao.query_by_id(file.knowledge_id)
            input_files = new_files.get(file.id)
            file.object_name = input_files.get('object_name', file.object_name)
            file_preview_cache_key = KnowledgeUtils.get_preview_cache_key(
                file.knowledge_id, input_files.get('file_path', ''))
            process_file_task(knowledge, [file],
                              fake_req.separator,
                              fake_req.separator_rule,
                              fake_req.chunk_size,
                              fake_req.chunk_overlap,
                              extra_metadata=file.extra_meta,
                              preview_cache_keys=[file_preview_cache_key])
        except Exception as e:
            logger.exception(f'retry_file_error file_id={file.id}')
            file.status = 3
            file.remark = str(e)[:500]
            KnowledgeFileDao.update(file)


def delete_vector(collection_name: str, partition_key: str):
    embeddings = FakeEmbedding()
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    if isinstance(vectore_client.col, Collection):
        if partition_key:
            pass
        else:
            res = vectore_client.col.drop(timeout=1)
            logger.info('act=delete_milvus col={} res={}', collection_name, res)


def delete_es(index_name: str):
    embeddings = FakeEmbedding()
    esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

    if esvectore_client:
        res = esvectore_client.client.indices.delete(index=index_name, ignore=[400, 404])
        logger.info(f'act=delete_es index={index_name} res={res}')


def QA_save_knowledge(db_knowledge: Knowledge, QA: QAKnowledge):
    """使用text 导入knowledge"""

    questions = QA.questions
    answer = json.loads(QA.answers)[0]
    extra = {}
    if QA.extra_meta:
        extra = json.loads(QA.extra_meta) or {}
    extra.update({'answer': answer, 'main_question': questions[0]})
    docs = [Document(page_content=question, metadata=extra) for question in questions]
    try:
        embeddings = decide_embeddings(db_knowledge.model)
        vectore_config_dict: dict = settings.get_knowledge().get('vectorstores')
        if not vectore_config_dict:
            raise Exception('向量数据库必须配置')
        vectore_client_list = [
            decide_vectorstores(db_knowledge.index_name or db_knowledge.collection_name, db,
                                embeddings) if db == 'ElasticKeywordsSearch' else
            decide_vectorstores(db_knowledge.collection_name, db, embeddings)
            for db in vectore_config_dict.keys()
        ]
        logger.info('vector_init_conn_done col={} dbs={}', db_knowledge.collection_name,
                    vectore_config_dict.keys())
    except Exception as e:
        logger.exception(e)

    try:
        # 统一document
        metadata = [{
            'file_id': QA.id,
            'knowledge_id': f'{db_knowledge.id}',
            'page': doc.metadata.pop('page', 1),
            'source': doc.metadata.pop('source', ''),
            'bbox': doc.metadata.pop('bbox', ''),
            'title': doc.metadata.pop('title', ''),
            'chunk_index': index,
            'extra': json.dumps(doc.metadata, ensure_ascii=False)
        } for index, doc in enumerate(docs)]

        # 向量存储
        for vectore_client in vectore_client_list:
            vectore_client.add_texts(texts=[t.page_content for t in docs], metadatas=metadata)

        QA.status = 1
        with session_getter() as session:
            session.add(QA)
            session.commit()
            session.refresh(QA)
    except Exception as e:
        logger.error(e)
        setattr(QA, 'status', 0)
        setattr(QA, 'remark', str(e)[:500])
        with session_getter() as session:
            session.add(QA)
            session.commit()
            session.refresh(QA)

    return QA


def add_qa(db_knowledge: Knowledge, data: QAKnowledgeUpsert) -> QAKnowledge:
    """使用text 导入QAknowledge"""
    if db_knowledge.type != 1:
        raise Exception('knowledge type error')
    try:
        # 相似问统一插入
        questions = data.questions
        if questions:
            if data.id:
                qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(data.id)
                qa_db.questions = questions
                qa_db.answers = data.answers
                qa = QAKnoweldgeDao.update(qa_db)
                # 需要先删除再插入
                delete_vector_data(db_knowledge, [data.id])
            else:
                qa = QAKnoweldgeDao.insert_qa(data)

            # 对question进行embedding，然后录入知识库
            qa = QA_save_knowledge(db_knowledge, qa)
            return qa
    except Exception as e:
        logger.exception(e)
        raise e


def qa_status_change(qa_id: int, target_status: int):
    """QA 状态切换"""
    qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(qa_id)

    if qa_db.status == target_status:
        logger.info('qa status is same, skip')
        return

    db_knowledge = KnowledgeDao.query_by_id(qa_db.knowledge_id)
    if target_status == 0:
        delete_vector_data(db_knowledge, [qa_id])
        qa_db.status = target_status
        QAKnoweldgeDao.update(qa_db)
    else:
        qa_db.status = target_status
        QAKnoweldgeDao.update(qa_db)
        QA_save_knowledge(db_knowledge, qa_db)
    return qa_db


def list_qa_by_knowledge_id(knowledge_id: int,
                            page_size: int = 10,
                            page_num: int = 1,
                            question: Optional[str] = None,
                            answer: Optional[str] = None,
                            keyword: Optional[str] = None,
                            status: Optional[int] = None) -> List[QAKnowledge]:
    """获取知识库下的所有qa"""
    if not knowledge_id:
        return []

    count_sql = select(func.count(QAKnowledge.id)).where(QAKnowledge.knowledge_id == knowledge_id)
    list_sql = select(QAKnowledge).where(QAKnowledge.knowledge_id == knowledge_id)

    if status:
        count_sql = count_sql.where(QAKnowledge.status == status)
        list_sql = list_sql.where(QAKnowledge.status == status)

    if question:
        count_sql = count_sql.where(QAKnowledge.questions.like(f'%{question}%'))
        list_sql = list_sql.where(QAKnowledge.questions.like(f'%{question}%'))

    if answer:
        count_sql = count_sql.where(QAKnowledge.answers.like(f'%{answer}%'))
        list_sql = list_sql.where(QAKnowledge.answers.like(f'%{answer}%'))

    if keyword:
        count_sql = count_sql.where(
            or_(QAKnowledge.questions.like(f'%{keyword}%'),
                QAKnowledge.answers.like(f'%{keyword}%')))
        list_sql = list_sql.where(
            or_(QAKnowledge.answers.like(f'%{keyword}%'),
                QAKnowledge.questions.like(f'%{keyword}%')))

    list_sql = list_sql.order_by(QAKnowledge.update_time.desc()).limit(page_size).offset(
        (page_num - 1) * page_size)
    count = QAKnoweldgeDao.total_count(count_sql)
    list_qa = QAKnoweldgeDao.query_by_condition(list_sql)

    return list_qa, count


def delete_vector_data(knowledge: Knowledge, file_ids: List[int]):
    """删除向量数据, 想做一个通用的，可以对接langchain的vectorDB"""
    # embeddings = FakeEmbedding()
    # vectore_config_dict: dict = settings.get_knowledge().get('vectorstores')
    # if not vectore_config_dict:
    #     raise Exception('向量数据库必须配置')
    # elastic_index = knowledge.index_name or knowledge.collection_name
    # vectore_client_list = [
    #     decide_vectorstores(elastic_index, db, embeddings) if db == 'ElasticKeywordsSearch' else
    #     decide_vectorstores(knowledge.collection_name, db, embeddings)
    #     for db in vectore_config_dict.keys()
    # ]
    # logger.info('vector_init_conn_done col={} dbs={}', knowledge.collection_name,
    #             vectore_config_dict.keys())

    # for vectore_client in vectore_client_list:
    # 查询vector primary key
    embeddings = FakeEmbedding()
    collection_name = knowledge.collection_name
    # 处理vectordb
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    try:
        if isinstance(vectore_client.col, Collection):
            pk = vectore_client.col.query(expr=f'file_id in {file_ids}',
                                          output_fields=['pk'],
                                          timeout=10)
        else:
            pk = []
    except Exception:
        # 重试一次
        logger.error('timeout_except')
        vectore_client.close_connection(vectore_client.alias)
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
        pk = vectore_client.col.query(expr=f'file_id in {file_ids}',
                                      output_fields=['pk'],
                                      timeout=10)
    logger.info('query_milvus pk={}', pk)
    if pk:
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}", timeout=10)
        logger.info(f'act=delete_vector file_id={file_ids} res={res}')
    vectore_client.close_connection(vectore_client.alias)

    # elastic
    index_name = knowledge.index_name or collection_name
    esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

    if esvectore_client:
        res = esvectore_client.client.delete_by_query(
            index=index_name, body={'query': {
                'terms': {
                    'metadata.file_id': file_ids
                }
            }})
    logger.info(f'act=delete_es  res={res}')
    return True


def recommend_question(question: str, answer: str, number: int = 3) -> List[str]:
    from langchain.chains.llm import LLMChain
    from langchain_core.prompts.prompt import PromptTemplate
    prompt = """- Role: 问题生成专家
        - Background: 用户希望通过人工智能模型根据给定的问题和答案生成相似的问题，以便于扩展知识库或用于教育和测试目的。
        - Profile: 你是一位专业的数据分析师和语言模型专家，擅长从现有数据中提取模式，并生成新的相关问题。
        - Constrains: 确保生成的问题在语义上与原始问题相似，同时保持多样性，避免重复。
        - Workflow:
        1. 分析用户输入的问题和答案，提取关键词和主题。
        2. 根据提取的关键词和主题创建相似问题。
        3. 验证生成的问题与原始问题在语义上的相似性，并确保多样性。
        - Examples:
        问题："法国的首都是哪里？"
        答案："巴黎"
        生成3个相似问题：
        - "法国的首都叫什么名字？"
        - "哪个城市是法国的首都？"
        - "巴黎是哪个国家的首都？"

        请使用json 返回
        {{"questions": 生成的问题列表}}

        以下是用户提供的问题和答案：
        问题：{question}
        答案：{answer}

        你生成的{number}个相似问题：
    """
    llm = LLMService.get_knowledge_similar_llm()
    if not llm:
        raise KnowledgeSimilarError.http_exception()

    llm_chain = LLMChain(llm=llm, prompt=PromptTemplate.from_template(prompt))
    gen_question = llm_chain.predict(question=question, answer=answer, number=number)
    try:
        code_ret = extract_code_blocks(gen_question)
        if code_ret:
            question_dict = json.loads(code_ret[0])
            return question_dict['questions']
        else:
            logger.info('md_code_extract_error {}', gen_question)
        return []
    except Exception as exc:
        logger.error('recommend_question json.loads error:{}', gen_question)
        raise ValueError(gen_question) from exc


def extract_code_blocks(markdown_code_block: str):
    # 定义正则表达式模式
    pattern = r'```\w*\s*(.*?)```'

    # 使用 re.DOTALL 使 . 能够匹配换行符
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    # 去除每段代码块两端的空白字符
    return [match.strip() for match in matches]
