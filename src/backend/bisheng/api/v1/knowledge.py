import base64
import json
import re
import time
from typing import List, Optional
from uuid import uuid4

import requests
from bisheng.api.utils import access_check
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200
from bisheng.cache.utils import file_download, save_uploaded_file
from bisheng.database.base import session_getter
from bisheng.database.models.knowledge import Knowledge, KnowledgeCreate, KnowledgeRead
from bisheng.database.models.knowledge_file import KnowledgeFile, KnowledgeFileRead
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.document_loaders import ElemUnstructuredLoader
from bisheng_langchain.embeddings import HostEmbeddings
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
from bisheng_langchain.vectorstores import ElasticKeywordsSearch, Milvus
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from langchain.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                        UnstructuredMarkdownLoader, UnstructuredPowerPointLoader,
                                        UnstructuredWordDocumentLoader)
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores.base import VectorStore
from pymilvus import Collection
from sqlalchemy import delete, func, or_
from sqlmodel import select

# build router
router = APIRouter(prefix='/knowledge', tags=['Skills'])
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


@router.post('/upload', response_model=UnifiedResponseModel[UploadFileResponse], status_code=201)
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename
        # 缓存本地
        file_path = save_uploaded_file(file.file, 'bisheng', file_name)
        if not isinstance(file_path, str):
            file_path = str(file_path)
        return resp_200(UploadFileResponse(file_path=file_path))
    except Exception as exc:
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/embedding_param', status_code=201)
async def get_embedding():
    try:
        # 获取本地配置的名字
        model_list = settings.get_knowledge().get('embeddings')
        if model_list:
            models = list(model_list.keys())
        else:
            models = list()
        return resp_200({'models': models})
    except Exception as exc:
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/process',
             response_model=UnifiedResponseModel[List[KnowledgeFileRead]],
             status_code=201)
async def process_knowledge(*,
                            data: dict,
                            background_tasks: BackgroundTasks,
                            Authorize: AuthJWT = Depends()):
    """上传文件到知识库.
    使用flowchain来处理embeding的流程
        """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    knowledge_id = data.get('knowledge_id')
    chunk_size = data.get('chunck_size')
    file_path = data.get('file_path')
    auto_p = data.get('auto')
    separator = data.get('separator')
    chunk_overlap = data.get('chunk_overlap')
    callback_url = data.get('callback_url')

    if auto_p:
        separator = ['\n\n', '\n', ' ', '']
        chunk_size = 500
        chunk_overlap = 50
    with session_getter() as session:
        knowledge = session.exec(select(Knowledge).where(Knowledge.id == knowledge_id)).one()

    if not access_check(payload=payload,
                        owner_user_id=knowledge.user_id,
                        target_id=knowledge.id,
                        type=AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=500, detail='当前用户无此知识库操作权限')

    collection_name = knowledge.collection_name
    files = []
    file_paths = []
    result = []
    for path in file_path:
        filepath, file_name = file_download(path)
        md5_ = filepath.rsplit('/', 1)[1].split('.')[0].split('_')[0]
        # 是否包含重复文件
        with session_getter() as session:
            repeat = session.exec(
                select(KnowledgeFile).where(KnowledgeFile.md5 == md5_, KnowledgeFile.status == 2,
                                            KnowledgeFile.knowledge_id == knowledge_id)).all()
        status = 3 if repeat else 1
        remark = 'file repeat' if repeat else ''
        db_file = KnowledgeFile(knowledge_id=knowledge_id,
                                file_name=file_name,
                                status=status,
                                md5=md5_,
                                remark=remark,
                                user_id=payload.get('user_id'))
        with session_getter() as session:
            session.add(db_file)
            session.commit()
            session.refresh(db_file)
        if not repeat:
            files.append(db_file.copy())
            file_paths.append(filepath)
        logger.info(f'fileName={file_name} col={collection_name} file_id={db_file.id}')
        result.append(db_file.copy())

    if files:
        background_tasks.add_task(
            addEmbedding,
            collection_name=collection_name,
            index_name=knowledge.index_name or knowledge.collection_name,
            knowledge_id=knowledge_id,
            model=knowledge.model,
            chunk_size=chunk_size,
            separator=separator,
            chunk_overlap=chunk_overlap,
            file_paths=file_paths,
            knowledge_files=files,
            callback=callback_url,
        )

    knowledge.update_time = db_file.create_time
    with session_getter() as session:
        session.add(knowledge)
        session.commit()
    return resp_200(result)


@router.post('/create', response_model=UnifiedResponseModel[KnowledgeRead], status_code=201)
def create_knowledge(*, knowledge: KnowledgeCreate, Authorize: AuthJWT = Depends()):
    """ 创建知识库. """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    user_id = payload.get('user_id')
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
    return resp_200(db_knowldge.copy())


@router.get('/', status_code=200)
def get_knowledge(*,
                  name: str = None,
                  page_size: Optional[int],
                  page_num: Optional[str],
                  Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """ 读取所有知识库信息. """

    try:
        sql = select(Knowledge)
        count_sql = select(func.count(Knowledge.id))
        if 'admin' != payload.get('role'):
            with session_getter() as session:
                role_third_id = session.exec(
                    select(RoleAccess).where(RoleAccess.role_id.in_(payload.get('role')))).all()
            if role_third_id:
                third_ids = [
                    acess.third_id for acess in role_third_id
                    if acess.type == AccessType.KNOWLEDGE.value
                ]
                sql = sql.where(
                    or_(Knowledge.user_id == payload.get('user_id'), Knowledge.id.in_(third_ids)))
                count_sql = count_sql.where(
                    or_(Knowledge.user_id == payload.get('user_id'), Knowledge.id.in_(third_ids)))
            else:
                sql = sql.where(Knowledge.user_id == payload.get('user_id'))
                count_sql = count_sql.where(Knowledge.user_id == payload.get('user_id'))
        if name:
            name = name.strip()
            sql = sql.where(Knowledge.name.like(f'%{name}%'))
            count_sql = count_sql.where(Knowledge.name.like(f'%{name}%'))

        sql = sql.order_by(Knowledge.update_time.desc())
        # get total count
        with session_getter() as session:
            total_count = session.scalar(count_sql)

        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            sql = sql.offset((page_num - 1) * page_size).limit(page_size)

        # get flow id
        with session_getter() as session:
            knowledges = session.exec(sql).all()
        res = [jsonable_encoder(flow) for flow in knowledges]
        if knowledges:
            db_user_ids = {flow.user_id for flow in knowledges}
            with session_getter() as session:
                db_user = session.exec(select(User).where(User.user_id.in_(db_user_ids))).all()
            userMap = {user.user_id: user.user_name for user in db_user}
            for r in res:
                r['user_name'] = userMap[r['user_id']]
        return resp_200({'data': res, 'total': total_count})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 file_name: str = None,
                 knowledge_id: int,
                 page_size: int = 10,
                 page_num: int = 1,
                 Authorize: AuthJWT = Depends()):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    with session_getter() as session:
        db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not access_check(payload=payload,
                        owner_user_id=db_knowledge.user_id,
                        target_id=knowledge_id,
                        type=AccessType.KNOWLEDGE):
        raise HTTPException(status_code=500, detail='没有访问权限')

    writable = access_check(payload=payload,
                            owner_user_id=db_knowledge.user_id,
                            target_id=knowledge_id,
                            type=AccessType.KNOWLEDGE_WRITE)

    # 查找上传的文件信息
    with session_getter() as session:
        if file_name:
            file_name = file_name.strip()
            total_count = session.scalar(
                select(func.count(KnowledgeFile.id)).where(
                    KnowledgeFile.knowledge_id == knowledge_id,
                    KnowledgeFile.file_name.like(f'%{file_name}%')))
            files = session.exec(
                select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id,
                                            KnowledgeFile.file_name.like(f'%{file_name}%'))).all()
        else:
            total_count = session.scalar(
                select(func.count(
                    KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id))
            files = session.exec(
                select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id).order_by(
                    KnowledgeFile.update_time.desc()).offset(
                        page_size * (page_num - 1)).limit(page_size)).all()
    return resp_200({
        'data': [jsonable_encoder(knowledgefile) for knowledgefile in files],
        'total': total_count,
        'writeable': writable
    })


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge(*, knowledge_id: int, Authorize: AuthJWT = Depends()):
    """ 删除知识库信息. """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    with session_getter() as session:
        knowledge = session.get(Knowledge, knowledge_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')
    if not access_check(payload, knowledge.user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    # 处理knowledgefile
    with session_getter() as session:
        session.exec(delete(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id))
        session.commit()
    # 处理vector
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

    with session_getter() as session:
        session.delete(knowledge)
        session.commit()
    return resp_200(message='删除成功')


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*, file_id: int, Authorize: AuthJWT = Depends()):
    """ 删除知识文件信息 """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    with session_getter() as session:
        knowledge_file = session.get(KnowledgeFile, file_id)
        if not knowledge_file:
            raise HTTPException(status_code=404, detail='文件不存在')

        knowledge = session.get(Knowledge, knowledge_file.knowledge_id)
        if not access_check(payload, knowledge.user_id, knowledge.id, AccessType.KNOWLEDGE_WRITE):
            raise HTTPException(status_code=404, detail='没有权限执行操作')
    # 处理vectordb
    collection_name = knowledge.collection_name
    embeddings = FakeEmbedding()
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    if isinstance(vectore_client, Milvus) and vectore_client.col:
        pk = vectore_client.col.query(expr=f'file_id == {file_id}', output_fields=['pk'])
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
        logger.info(f'act=delete_vector file_id={file_id} res={res}')

    # minio
    minio_client = MinioClient()
    minio_client.delete_minio(str(knowledge_file.id))
    if knowledge_file.object_name:
        minio_client.delete_minio(str(knowledge_file.object_name))
    # elastic
    index_name = knowledge.index_name or collection_name
    esvectore_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)

    if esvectore_client:
        res = esvectore_client.client.delete_by_query(
            index=index_name, query={'match': {
                'metadata.file_id': file_id
            }})
        logger.info(f'act=delete_es file_id={file_id} res={res}')

    with session_getter() as session:
        session.delete(knowledge_file)
        session.commit()
    return resp_200(message='删除成功')


def decide_embeddings(model: str) -> Embeddings:
    model_list = settings.get_knowledge().get('embeddings')
    if model == 'text-embedding-ada-002':
        return OpenAIEmbeddings(**model_list.get(model))
    else:
        return HostEmbeddings(**model_list.get(model))


def decide_vectorstores(collection_name: str, vector_store: str,
                        embedding: Embeddings) -> VectorStore:
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


def addEmbedding(collection_name, index_name, knowledge_id: int, model: str, chunk_size: int,
                 separator: str, chunk_overlap: int, file_paths: List[str],
                 knowledge_files: List[KnowledgeFile], callback: str):
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
        knowledge_file = knowledge_files[index]
        logger.info('process_file_begin knowledge_id={} file_name={} file_size={} ',
                    knowledge_files[0].knowledge_id, knowledge_file.file_name, len(file_paths))

        if not vectore_client and not es_client:
            # 设置错误
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
            # 存储 mysql
            with session_getter() as session:
                db_file = session.get(KnowledgeFile, knowledge_file.id)
                setattr(db_file, 'status', 2)
                # 原文件
                object_name_original = f'original/{db_file.id}'
                setattr(db_file, 'object_name', object_name_original)
                session.add(db_file)
                session.commit()
                session.refresh(db_file)

            minio_client.upload_minio(object_name_original, path)
            texts, metadatas = _read_chunk_text(path, knowledge_file.file_name, chunk_size,
                                                chunk_overlap, separator)

            if len(texts) == 0:
                raise ValueError('文件解析为空')
            # 溯源必须依赖minio, 后期替换更通用的oss
            minio_client.upload_minio(str(db_file.id), path)

            logger.info(f'chunk_split file_name={knowledge_file.file_name} size={len(texts)}')
            for metadata in metadatas:
                metadata.update({'file_id': knowledge_file.id, 'knowledge_id': f'{knowledge_id}'})

            if vectore_client:
                vectore_client.add_texts(texts=texts, metadatas=metadatas)

            # 存储es
            if es_client:
                es_client.add_texts(texts=texts, metadatas=metadatas)

            callback_obj = db_file.copy()
            logger.info('process_file_done file_name={} file_id={} time_cost={}',
                        knowledge_file.file_name, knowledge_file.id,
                        time.time() - ts1)

        except Exception as e:
            logger.error('insert_metadata={} ', metadatas, e)
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


def _read_chunk_text(input_file, file_name, size, chunk_overlap, separator):
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


def file_knowledge(db_knowledge: Knowledge, file_path: str, file_name: str, metadata: str):
    try:
        embeddings = decide_embeddings(db_knowledge.model)
        vectore_client = decide_vectorstores(db_knowledge.collection_name, 'Milvus', embeddings)
        index_name = db_knowledge.index_name or db_knowledge.collection_name
        es_client = decide_vectorstores(index_name, 'ElasticKeywordsSearch', embeddings)
    except Exception as e:
        logger.exception(e)
    separator = ['\n\n', '\n', ' ', '']
    chunk_size = 500
    chunk_overlap = 50
    raw_texts, metadatas = _read_chunk_text(file_path, file_name, chunk_size, chunk_overlap,
                                            separator)
    logger.info(f'chunk_split file_name={file_name} size={len(raw_texts)}')
    metadata_extra = json.loads(metadata)
    # 存储 mysql
    db_file = KnowledgeFile(knowledge_id=db_knowledge.id,
                            file_name=file_name,
                            status=1,
                            object_name=metadata_extra.get('url'))
    with session_getter() as session:
        session.add(db_file)
        session.commit()
        session.refresh(db_file)
    result = db_file.model_dump()

    try:
        metadata = [{
            'file_id': db_file.id,
            'knowledge_id': f'{db_knowledge.id}',
            'page': metadata.get('page'),
            'source': file_name,
            'bbox': metadata.get('bbox'),
            'extra': json.dumps(metadata_extra)
        } for metadata in metadatas]
        vectore_client.add_texts(texts=raw_texts, metadatas=metadata)

        # 存储es
        if es_client:
            es_client.add_texts(texts=raw_texts, metadatas=metadata)
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


def text_knowledge(db_knowledge: Knowledge, documents: List[Document]):
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
    db_file = KnowledgeFile(knowledge_id=db_knowledge.id,
                            file_name=file_name,
                            status=1,
                            object_name=documents[0].metadata.get('url'))
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
