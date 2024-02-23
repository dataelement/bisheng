import base64
import json
import re
import time
from typing import List
from uuid import uuid4

import requests
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeCreate
from bisheng.database.models.knowledge_file import KnowledgeFile
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.embeddings import HostEmbeddings
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus
from fastapi import HTTPException
from langchain.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                        UnstructuredMarkdownLoader, UnstructuredPowerPointLoader,
                                        UnstructuredWordDocumentLoader)
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema.document import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores.base import VectorStore
from loguru import logger
from pymilvus import Collection
from sqlalchemy import delete
from sqlmodel import select

filetype_load_map = {
    'txt': TextLoader,
    'pdf': PyPDFLoader,
    'html': BSHTMLLoader,
    'md': UnstructuredMarkdownLoader,
    'doc': UnstructuredWordDocumentLoader,
    'docx': UnstructuredWordDocumentLoader,
    'ppt': UnstructuredPowerPointLoader,
    'pptx': UnstructuredPowerPointLoader,
}


def create_knowledge(knowledge: KnowledgeCreate, user_id: int):
    """ 创建知识库. """
    knowledge.is_partition = knowledge.is_partition or settings.get_knowledge().get(
        'vectorstores', {}).get('Milvus', {}).get('is_partition', True)
    db_knowldge = Knowledge.model_validate(knowledge)
    with session_getter() as session:
        know = session.exec(
            select(Knowledge).where(Knowledge.name == knowledge.name,
                                    knowledge.user_id == user_id)).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')
    if not db_knowldge.collection_name:
        if knowledge.is_partition:
            embedding = re.sub(r'[^\w]', '_', knowledge.model)
            suffix_id = settings.get_knowledge().get('vectorstores').get('Milvus', {}).get(
                'partition_suffix', 1)
            db_knowldge.collection_name = f'partition_{embedding}_knowledge_{suffix_id}'
        else:
            # 默认collectionName
            db_knowldge.collection_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.index_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.user_id = user_id
    with session_getter() as session:
        session.add(db_knowldge)
        session.commit()
        session.refresh(db_knowldge)
        return db_knowldge.copy()


def delete_knowledge_by(knowledge: Knowledge):
    # 处理vector
    knowledge_id = knowledge.id
    embeddings = FakeEmbedding()
    vectore_client = decide_vectorstores(knowledge.collection_name, 'Milvus', embeddings)
    if isinstance(vectore_client.col, Collection):
        logger.info(f'delete_vectore col={knowledge.collection_name}')
        if knowledge.collection_name.startswith('col'):
            vectore_client.col.drop()
        else:
            pk = vectore_client.col.query(expr=f'knowledge_id=="{knowledge.id}"',
                                          output_fields=['pk'])
            vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
            # 判断milvus 是否还有entity
            if vectore_client.col.is_empty:
                vectore_client.col.drop()

    # 处理 es
    # elastic
    esvectore_client: 'ElasticKeywordsSearch' = decide_vectorstores(knowledge.index_name,
                                                                    'ElasticKeywordsSearch',
                                                                    embeddings)
    if esvectore_client:
        index_name = knowledge.index_name or knowledge.collection_name  # 兼容老版本
        res = esvectore_client.client.indices.delete(index=index_name, ignore=[400, 404])
        logger.info(f'act=delete_es index={index_name} res={res}')
    # 处理knowledgefile
    with session_getter() as session:
        session.exec(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
        session.delete(knowledge)
        session.commit()
    return True


def delete_knowledge_file_batch(file_ids: List[int]):
    """ 删除知识文件信息 """
    with session_getter() as session:
        knowledge_files = session.exec(
            select(KnowledgeFile).where(KnowledgeFile.id.in_(file_ids))).all()
        if not knowledge_files:
            raise ValueError('文件ID不存在')

    knowledge_ids = [file.knowledge_id for file in knowledge_files]
    with session_getter() as session:
        knowledges = session.exec(select(Knowledge).where(Knowledge.id.in_(knowledge_ids))).all()
    knowledgeid_dict = {knowledge.id: knowledge for knowledge in knowledges}
    # 处理vectordb
    for file in knowledge_files:
        knowledge = knowledgeid_dict.get(file.knowledge_id)
        collection_name = knowledge.collection_name
        embeddings = FakeEmbedding()
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
        if isinstance(vectore_client, Milvus) and vectore_client.col:
            pk = vectore_client.col.query(expr=f'file_id == {file.id}', output_fields=['pk'])
            res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
            logger.info(f'act=delete_vector file_id={file.id} res={res}')

            # minio
            minio_client = MinioClient()
            minio_client.delete_minio(str(file.id))
            if file.object_name:
                minio_client.delete_minio(str(file.object_name))
            # elastic
            index_name = knowledge.index_name or collection_name
            esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

            if esvectore_client:
                res = esvectore_client.client.delete_by_query(
                    index=index_name, query={'match': {
                        'metadata.file_id': file.id
                    }})
                logger.info(f'act=delete_es file_id={file.id} res={res}')

        with session_getter() as session:
            session.delete(file)
            session.commit()
    return True


def decide_embeddings(model: str) -> Embeddings:
    """embed method"""
    model_list = settings.get_knowledge().get('embeddings')
    if model == 'text-embedding-ada-002':
        return OpenAIEmbeddings(**model_list.get(model))
    else:
        return HostEmbeddings(**model_list.get(model))


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
    return instantiate_vectorstore(class_object=class_obj, params=param)


def addEmbedding(collection_name,
                 index_name,
                 knowledge_id: int,
                 model: str,
                 chunk_size: int,
                 separator: str,
                 chunk_overlap: int,
                 file_paths: List[str],
                 knowledge_files: List[KnowledgeFile],
                 callback: str,
                 extra_meta: str = None):
    error_msg = ''
    try:
        vectore_client, es_client = None, None
        minio_client = MinioClient()
        embeddings = decide_embeddings(model)
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    except Exception as e:
        error_msg = 'MilvusExcept:' + str(e)
        logger.exception(e)

    try:
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
    except Exception as e:
        error_msg = error_msg + 'ESException:' + str(e)
        logger.exception(e)

    callback_obj = {}
    for index, path in enumerate(file_paths):
        ts1 = time.time()
        with session_getter() as session:
            knowledge_file = session.get(KnowledgeFile, knowledge_files[index].id)
        logger.info('process_file_begin knowledge_id={} file_name={} file_size={} ',
                    knowledge_files[0].knowledge_id, knowledge_file.file_name, len(file_paths))
        # 原始文件保存
        file_type = knowledge_file.file_name.rsplit('.', 1)[-1]
        knowledge_file.object_name = f'original/{knowledge_file.id}.{file_type}'
        with session_getter() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
        if not vectore_client and not es_client:
            # 设置错误
            logger.error(f'no_vector_db_found err={error_msg}')
            with session_getter() as session:
                db_file = session.get(KnowledgeFile, knowledge_file.id)
                setattr(db_file, 'status', 3)
                setattr(db_file, 'remark', error_msg[:500])
                session.add(db_file)
                callback_obj = db_file.copy()
                session.commit()
            if callback:
                inp = {
                    'file_name': knowledge_file.file_name,
                    'file_status': knowledge_file.status,
                    'file_id': callback_obj.id,
                    'error_msg': callback_obj.remark
                }
                logger.error('add_fail callback={} file_name={} status={}', callback,
                             callback_obj.file_name, callback_obj.status)
                requests.post(url=callback, json=inp, timeout=3)
            continue
        try:
            res = minio_client.upload_minio(knowledge_file.object_name, path)
            logger.info('upload_original_file path={} res={}', knowledge_file.object_name, res)
            texts, metadatas = read_chunk_text(path, knowledge_file.file_name, chunk_size,
                                               chunk_overlap, separator)

            if len(texts) == 0:
                raise ValueError('文件解析为空')
            # 溯源必须依赖minio, 后期替换更通用的oss
            minio_client.upload_minio(str(knowledge_file.id), path)

            logger.info(f'chunk_split file_name={knowledge_file.file_name} size={len(texts)}')
            for metadata in metadatas:
                metadata.update({
                    'file_id': knowledge_file.id,
                    'knowledge_id': f'{knowledge_id}',
                    'extra': extra_meta or ''
                })

            if vectore_client:
                vectore_client.add_texts(texts=texts, metadatas=metadatas)

            # 存储es
            if es_client:
                es_client.add_texts(texts=texts, metadatas=metadatas)

            # 存储 mysql
            with session_getter() as session:
                knowledge_file.status = 2
                session.add(knowledge_file)
                session.commit()
                session.refresh(knowledge_file)
            callback_obj = knowledge_file.copy()
            logger.info('process_file_done file_name={} file_id={} time_cost={}',
                        knowledge_file.file_name, knowledge_file.id,
                        time.time() - ts1)

        except Exception as e:
            logger.error('add_vectordb {}', e)
            with session_getter() as session:
                db_file = session.get(KnowledgeFile, knowledge_file.id)
                setattr(db_file, 'status', 3)
                setattr(db_file, 'remark', str(e)[:500])
                session.add(db_file)
                callback_obj = db_file.copy()
                session.commit()
        if callback:
            # asyn
            inp = {
                'file_name': callback_obj.file_name,
                'file_status': callback_obj.status,
                'file_id': callback_obj.id,
                'error_msg': callback_obj.remark
            }
            logger.info(
                f'add_complete callback={callback} file_name={callback_obj.file_name} status={callback_obj.status}'
            )
            requests.post(url=callback, json=inp, timeout=3)


def read_chunk_text(input_file, file_name, size, chunk_overlap, separator):
    if not settings.get_knowledge().get('unstructured_api_url'):
        file_type = file_name.split('.')[-1]
        if file_type not in filetype_load_map:
            raise Exception('Unsupport file type')
        loader = filetype_load_map[file_type](file_path=input_file)
        separator = separator[0] if separator and isinstance(separator, list) else separator
        text_splitter = CharacterTextSplitter(separator=separator,
                                              chunk_size=size,
                                              chunk_overlap=chunk_overlap,
                                              add_start_index=True)
        documents = loader.load()
        texts = text_splitter.split_documents(documents)
        raw_texts = [t.page_content for t in texts]
        metadatas = [{
            'bbox': json.dumps({'chunk_bboxes': t.metadata.get('chunk_bboxes', '')}),
            'page': t.metadata.get('page') or 0,
            'source': file_name,
            'extra': ''
        } for t in texts]
    else:
        # 如果文件不是pdf 需要内部转pdf
        if file_name.rsplit('.', 1)[-1] != 'pdf':
            b64_data = base64.b64encode(open(input_file, 'rb').read()).decode()
            inp = dict(filename=file_name, b64_data=[b64_data], mode='topdf')
            resp = requests.post(settings.get_knowledge().get('unstructured_api_url'), json=inp)
            if not resp or resp.status_code != 200:
                logger.error(f'file_pdf=not_success resp={resp.text}')
                raise Exception(f"当前文件无法解析， {resp['status_message']}")
            if len(resp.text) < 300:
                logger.error(f'file_pdf=not_success resp={resp.text}')
            b64_data = resp.json()['b64_pdf']
            # 替换历史文件
            with open(input_file, 'wb') as fout:
                fout.write(base64.b64decode(b64_data))
            file_name = file_name.rsplit('.', 1)[0] + '.pdf'

        loader = ElemUnstructuredLoader(
            file_name,
            input_file,
            unstructured_api_url=settings.get_knowledge().get('unstructured_api_url'))
        documents = loader.load()
        text_splitter = ElemCharacterTextSplitter(separators=separator,
                                                  chunk_size=size,
                                                  chunk_overlap=chunk_overlap)
        texts = text_splitter.split_documents(documents)
        raw_texts = [t.page_content for t in texts]
        metadatas = [{
            'bbox': json.dumps({'chunk_bboxes': t.metadata.get('chunk_bboxes', '')}),
            'page': t.metadata.get('chunk_bboxes')[0].get('page'),
            'source': t.metadata.get('source', ''),
            'extra': '',
        } for t in texts]
    return (raw_texts, metadatas)


def text_knowledge(db_knowledge: Knowledge, db_file: KnowledgeFile, documents: List[Document]):
    """使用text 导入knowledge"""
    try:
        embeddings = decide_embeddings(db_knowledge.model)
        vectore_client = decide_vectorstores(db_knowledge.collection_name, 'Milvus', embeddings)
        index_name = db_knowledge.index_name or db_knowledge.collection_name
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
    except Exception as e:
        logger.exception(e)

    separator = '\n\n'
    chunk_size = 500
    chunk_overlap = 50

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
            'extra': json.dumps(doc.metadata)
        } for doc in documents]
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
