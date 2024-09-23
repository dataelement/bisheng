import json
import time
from typing import Any, Dict, List

import requests
from loguru import logger
from pymilvus import Collection
from langchain.embeddings.base import Embeddings
from langchain.schema.document import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores.base import VectorStore
from langchain_community.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                                  UnstructuredMarkdownLoader,
                                                  UnstructuredPowerPointLoader,
                                                  UnstructuredWordDocumentLoader)

from bisheng.api.services.llm import LLMService
from bisheng.api.utils import md5_hash
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.cache.redis import redis_client
from bisheng.cache.utils import file_download
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao
from bisheng.database.models.knowledge_file import KnowledgeFile, KnowledgeFileDao, KnowledgeFileStatus, ParseType
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils.embedding import decide_embeddings
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.rag.extract_info import extract_title
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter

filetype_load_map = {
    'txt': TextLoader,
    'pdf': PyPDFLoader,
    'html': BSHTMLLoader,
    'md': UnstructuredMarkdownLoader,
    'docx': UnstructuredWordDocumentLoader,
    'pptx': UnstructuredPowerPointLoader,
}


class KnowledgeUtils:

    @classmethod
    def get_preview_cache_key(cls, knowledge_id: int, file_path: str) -> str:
        md5_value = md5_hash(file_path)
        return f'preview_file_chunk:{knowledge_id}:{md5_value}'

    @classmethod
    def save_preview_cache(cls, cache_key, mapping: dict = None, chunk_index: int = 0, value: dict = None):
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


def process_file_task(knowledge: Knowledge, db_files: List[KnowledgeFile],
                      separator: List[str], separator_rule: List[str], chunk_size: int, chunk_overlap: int,
                      callback_url: str = None, extra_metadata: str = None, preview_cache_keys: List[str] = None):
    """ 处理知识文件任务 """
    try:
        index_name = knowledge.index_name or knowledge.collection_name
        addEmbedding(knowledge.collection_name, index_name, knowledge.id, knowledge.model,
                     separator, separator_rule, chunk_size, chunk_overlap, db_files,
                     callback_url, extra_metadata, preview_cache_keys=preview_cache_keys)
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

    if vector_store == 'ElasticKeywordsSearch':
        param = {'index_name': collection_name, 'embedding': embedding}
        if isinstance(vector_config['ssl_verify'], str):
            vector_config['ssl_verify'] = eval(vector_config['ssl_verify'])
    else:
        param = {'collection_name': collection_name, 'embedding': embedding}
        vector_config.pop('partition_suffix', '')
        vector_config.pop('is_partition', '')

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

    logger.info(f'start process files')
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
            preview_cache_key = preview_cache_keys[index] if index < len(preview_cache_keys) else None
        try:
            logger.info(f'process_file_begin file_id={db_file.id} file_name={db_file.file_name}')
            add_file_embedding(vector_client, es_client, minio_client,
                               db_file, separator, separator_rule, chunk_size, chunk_overlap,
                               extra_meta=extra_meta, preview_cache_key=preview_cache_key)
            db_file.status = KnowledgeFileStatus.SUCCESS.value
        except Exception as e:
            logger.exception(f'process_file_fail file_id={db_file.id} file_name={db_file.file_name}')
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


def add_file_embedding(vector_client, es_client, minio_client, db_file: KnowledgeFile, separator: List[str],
                       separator_rule: List[str], chunk_size: int, chunk_overlap: int,
                       extra_meta: str = None, preview_cache_key: str = None):
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
    texts, metadatas, parse_type, partitions = read_chunk_text(filepath, db_file.file_name, separator,
                                                               separator_rule, chunk_size, chunk_overlap)
    if len(texts) == 0:
        raise ValueError('文件解析为空')
    for one in texts:
        if len(one) > 10000:
            raise ValueError('分段结果超长，请尝试使用自定义策略进行切分')

    db_file.parse_type = parse_type
    # 存储ocr识别后的partitions结果
    if partitions:
        partition_data = json.dumps(partitions, ensure_ascii=False).encode('utf-8')
        minio_client.upload_minio_data(f'partitions/{db_file.id}.json', partition_data, len(partition_data),
                                       "application/json")
        db_file.bbox_object_name = f'partitions/{db_file.id}.json'

    # 缓存中有数据则用缓存中的数据去入库，因为是用户在界面编辑过的
    if preview_cache_key:
        all_chunk_info = KnowledgeUtils.get_preview_cache(preview_cache_key)
        if all_chunk_info:
            logger.info(f'get_preview_cache file={db_file.id} file_name={db_file.file_name}')
            texts, metadatas = [], []
            for key, val in all_chunk_info.items():
                texts.append(val['text'])
                metadatas.append(val['metadata'])

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


def add_text_into_vector(vector_client, es_client, db_file: KnowledgeFile, texts: List[str], metadatas: List[dict]):
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
        bboxes = part["metadata"]["extra_data"]["bboxes"]
        indexes = part["metadata"]["extra_data"]["indexes"]
        pages = part["metadata"]["extra_data"]["pages"]
        text = part["text"]
        for index, bbox in enumerate(bboxes):
            key = f"{pages[index]}-" + "-".join([str(int(one)) for one in bbox])
            val = text[indexes[index][0]:indexes[index][1] + 1]
            res[key] = {
                "text": val,
                "type": part["type"],
                "part_id": part_index
            }
    return res


def read_chunk_text(input_file, file_name, separator: List[str], separator_rule: List[str], chunk_size: int,
                    chunk_overlap: int) -> (List[str], List[dict], str, Any):
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
        raise Exception(f'知识库总结所需模型配置有误，初始化失败， {str(e)}')
    text_splitter = ElemCharacterTextSplitter(separators=separator,
                                              separator_rule=separator_rule,
                                              chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap,
                                              is_separator_regex=True)
    # 加载文档内容
    logger.info(f'start_file_loader file_name={file_name}')
    parse_type = ParseType.LOCAL.value
    if not settings.get_knowledge().get('unstructured_api_url'):
        file_type = file_name.split('.')[-1]
        if file_type not in filetype_load_map:
            raise Exception('类型不支持')
        loader = filetype_load_map[file_type](file_path=input_file)
        partitions = []
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
        'bbox': json.dumps({'chunk_bboxes': t.metadata.get('chunk_bboxes', '')}),
        'page': t.metadata['chunk_bboxes'][0].get('page') if t.metadata.get('chunk_bboxes', None) else t.metadata.get(
            'page', 0),
        'source': file_name,
        'title': t.metadata.get('title', ''),
        'chunk_index': t_index,
        'extra': ''
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
    fake_req = FileProcessBase(knowledge_id=1)

    for file in db_files:
        try:
            knowledge = KnowledgeDao.query_by_id(file.knowledge_id)
            input_files = new_files.get(file.id)
            file.object_name = input_files.get("object_name", file.object_name)
            file_preview_cache_key = KnowledgeUtils.get_preview_cache_key(file.knowledge_id,
                                                                          input_files.get("file_path", ""))
            process_file_task(knowledge, [file], fake_req.separator, fake_req.separator_rule,
                              fake_req.chunk_size, fake_req.chunk_overlap, extra_metadata=file.extra_meta,
                              preview_cache_keys=[file_preview_cache_key])
        except Exception as e:
            logger.exception(f"retry_file_error file_id={file.id}")
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
