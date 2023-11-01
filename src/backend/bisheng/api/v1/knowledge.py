import asyncio
import base64
import json
import time
from typing import List, Optional
from uuid import uuid4
from bisheng_langchain.vectorstores.elastic_keywords_search import ElasticKeywordsSearch

import requests
from bisheng.api.utils import access_check
from bisheng.api.v1.schemas import UploadFileResponse
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.base import get_session
from bisheng.database.models.knowledge import Knowledge, KnowledgeCreate, KnowledgeRead
from bisheng.database.models.knowledge_file import KnowledgeFile
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.interface.importing.utils import import_vectorstore
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.settings import settings
from bisheng.utils import minio_client
from bisheng.utils.logger import logger
from bisheng_langchain.document_loaders.elem_unstrcutured_loader import ElemUnstructuredLoader
from bisheng_langchain.embeddings.host_embedding import HostEmbeddings
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from langchain.embeddings.base import Embeddings
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores import Milvus
from langchain.vectorstores.base import VectorStore
from sqlalchemy import func, or_
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/knowledge', tags=['Skills'])


@router.post('/upload', response_model=UploadFileResponse, status_code=201)
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename
        # 缓存本地
        file_path = save_uploaded_file(file.file, 'bisheng').as_posix()
        return UploadFileResponse(file_path=file_path + '_' + file_name,)
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
        return {'data': {'models': models}}
    except Exception as exc:
        logger.error(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/process', status_code=201)
async def process_knowledge(*,
                            session: Session = Depends(get_session),
                            data: dict,
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
    chunk_overlap = 0

    if auto_p:
        separator = ['\n\n', '\n', ' ', '']
        chunk_size = 500
        chunk_overlap = 50

    knowledge = session.exec(select(Knowledge).where(Knowledge.id == knowledge_id)).one()

    if not access_check(payload=payload,
                        owner_user_id=knowledge.user_id,
                        target_id=knowledge.id,
                        type=AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=500, detail='当前用户无此知识库操作权限')

    collection_name = knowledge.collection_name
    files = []
    file_paths = []
    for path in file_path:
        filepath, file_name = path.split('_', 1)
        md5_ = filepath.rsplit('/', 1)[1]
        db_file = KnowledgeFile(knowledge_id=knowledge_id,
                                file_name=file_name,
                                status=1,
                                md5=md5_,
                                user_id=payload.get('user_id'))
        session.add(db_file)
        session.commit()
        session.refresh(db_file)
        files.append(db_file)
        file_paths.append(filepath)
        logger.info(f'fileName={file_name} col={collection_name}')

    asyncio.create_task(
        addEmbedding(collection_name=collection_name,
                     model=knowledge.model,
                     chunk_size=chunk_size,
                     separator=separator,
                     chunk_overlap=chunk_overlap,
                     file_paths=file_paths,
                     knowledge_files=files))

    knowledge.update_time = db_file.create_time
    session.add(knowledge)
    session.commit()
    return {'code': 200, 'message': 'success'}


@router.post('/create', response_model=KnowledgeRead, status_code=201)
def create_knowledge(*,
                     session: Session = Depends(get_session),
                     knowledge: KnowledgeCreate,
                     Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """创建知识库."""
    db_knowldge = Knowledge.from_orm(knowledge)
    know = session.exec(
        select(Knowledge).where(Knowledge.name == knowledge.name,
                                knowledge.user_id == payload.get('user_id'))).all()
    if know:
        raise HTTPException(status_code=500, detail='知识库名称重复')
    if not db_knowldge.collection_name:
        # 默认collectionName
        db_knowldge.collection_name = f'col_{int(time.time())}_{str(uuid4())[:8]}'
    db_knowldge.user_id = payload.get('user_id')
    session.add(db_knowldge)
    session.commit()
    session.refresh(db_knowldge)
    return db_knowldge


@router.get('/', status_code=200)
def get_knowledge(*,
                  session: Session = Depends(get_session),
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
            role_third_id = session.exec(
                select(RoleAccess).where(RoleAccess.role_id.in_(payload.get('role')))).all()
            if role_third_id:
                third_ids = [
                    acess.third_id
                    for acess in role_third_id
                    if acess.type == AccessType.KNOWLEDGE.value
                ]
                sql = sql.where(
                    or_(Knowledge.user_id == payload.get('user_id'), Knowledge.id.in_(third_ids)))
                count_sql = count_sql.where(
                    or_(Knowledge.user_id == payload.get('user_id'), Knowledge.id.in_(third_ids)))
            else:
                sql = sql.where(Knowledge.user_id == payload.get('user_id'))
                count_sql = count_sql.where(Knowledge.user_id == payload.get('user_id'))
        sql = sql.order_by(Knowledge.update_time.desc())
        total_count = session.scalar(count_sql)

        if page_num and page_size and page_num != 'undefined':
            page_num = int(page_num)
            sql = sql.offset((page_num - 1) * page_size).limit(page_size)

        knowledges = session.exec(sql).all()
        res = [jsonable_encoder(flow) for flow in knowledges]
        if knowledges:
            db_user_ids = {flow.user_id for flow in knowledges}
            db_user = session.exec(select(User).where(User.user_id.in_(db_user_ids))).all()
            userMap = {user.user_id: user.user_name for user in db_user}
            for r in res:
                r['user_name'] = userMap[r['user_id']]
        return {'data': res, 'total': total_count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 session: Session = Depends(get_session),
                 knowledge_id: int,
                 page_size: int = 10,
                 page_num: int = 1,
                 Authorize: AuthJWT = Depends()):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
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
    total_count = session.scalar(
        select(func.count(KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id))
    files = session.exec(
        select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id).order_by(
            KnowledgeFile.update_time.desc()).offset(page_size *
                                                     (page_num - 1)).limit(page_size)).all()
    return {
        'data': [jsonable_encoder(knowledgefile) for knowledgefile in files],
        'total': total_count,
        'writeable': writable
    }


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge(*,
                     session: Session = Depends(get_session),
                     knowledge_id: int,
                     Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """ 删除知识库信息. """
    knowledge = session.get(Knowledge, knowledge_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')
    if not access_check(payload, knowledge.user_id, knowledge_id, AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')
    session.delete(knowledge)
    session.commit()
    return {'message': 'knowledge deleted successfully'}


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          session: Session = Depends(get_session),
                          file_id: int,
                          Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    """ 删除知识文件信息 """
    knowledge_file = session.get(KnowledgeFile, file_id)
    if not knowledge_file:
        raise HTTPException(status_code=404, detail='文件不存在')

    knowledge = session.get(Knowledge, knowledge_file.knowledge_id)
    if not access_check(payload, knowledge.user_id, knowledge.id, AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')
    # 处理vectordb
    collection_name = knowledge.collection_name
    embeddings = decide_embeddings(knowledge.model)
    vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
    if isinstance(vectore_client, Milvus) and vectore_client.col:
        pk = vectore_client.col.query(expr=f'file_id == {file_id}', output_fields=['pk'])
        res = vectore_client.col.delete(f"pk in {[p['pk'] for p in pk]}")
        logger.info(f'act=delete_vector file_id={file_id} res={res}')

    # minio
    minio_client.MinioClient().delete_minio(str(knowledge_file.id))
    # elastic
    esvectore_client = decide_vectorstores(collection_name, 'ElasticKeywordsSearch', embeddings)
    if esvectore_client:
        esvectore_client.client.delete_by_query(index=collection_name,
                                                query={'match': {
                                                    'metadata.file_id': file_id
                                                }})
        logger.info(f'act=delete_es file_id={file_id} res={res}')

    session.delete(knowledge_file)
    session.commit()
    return {'message': 'knowledge file deleted successfully'}


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
    param.update(vector_config)
    class_obj = import_vectorstore(vector_store)
    return instantiate_vectorstore(class_object=class_obj, params=param)


async def addEmbedding(collection_name, model: str, chunk_size: int, separator: str,
                       chunk_overlap: int, file_paths: List[str],
                       knowledge_files: List[KnowledgeFile]):
    try:
        embeddings = decide_embeddings(model)
        vectore_client = decide_vectorstores(collection_name, 'Milvus', embeddings)
        es_client = decide_vectorstores(collection_name, 'ElasticKeywordsSearch', embeddings)
    except Exception as e:
        logger.exception(e)

    for index, path in enumerate(file_paths):
        knowledge_file = knowledge_files[index]
        try:
            # 存储 mysql
            session = next(get_session())
            db_file = session.get(KnowledgeFile, knowledge_file.id)
            setattr(db_file, 'status', 2)
            setattr(db_file, 'object_name', knowledge_file.file_name)
            session.add(db_file)
            session.flush()
            # 原文件
            minio_client.MinioClient().upload_minio(knowledge_file.file_name, path)

            texts, metadatas = _read_chunk_text(path, knowledge_file.file_name, chunk_size,
                                                chunk_overlap, separator)

            # 溯源必须依赖minio, 后期替换更通用的oss
            minio_client.MinioClient().upload_minio(str(db_file.id), path)

            logger.info(f'chunk_split file_name={knowledge_file.file_name} size={len(texts)}')
            [metadata.update({'file_id': knowledge_file.id}) for metadata in metadatas]
            vectore_client.add_texts(texts=texts, metadatas=metadatas)

            # 存储es
            if es_client:
                es_client.add_texts(texts=texts, metadatas=metadatas)
            session.commit()
            session.refresh(db_file)
        except Exception as e:
            logger.exception(e)
            session = next(get_session())
            db_file = session.get(KnowledgeFile, knowledge_file.id)
            setattr(db_file, 'status', 3)
            setattr(db_file, 'remark', str(e)[:500])
            session.add(db_file)
            session.commit()


def _read_chunk_text(input_file, file_name, size, chunk_overlap, separator):
    from langchain.document_loaders import (PyPDFLoader, BSHTMLLoader, TextLoader,
                                            UnstructuredMarkdownLoader)
    from langchain.text_splitter import CharacterTextSplitter
    from bisheng_langchain.text_splitter import ElemCharacterTextSplitter
    filetype_load_map = {
        'txt': TextLoader,
        'pdf': PyPDFLoader,
        'html': BSHTMLLoader,
        'md': UnstructuredMarkdownLoader,
    }

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
        metadatas = [t.metadata.update({'bbox': ''}) for t in texts]
        metadatas = [t.metadata for t in texts]
    else:
        # 如果文件不是pdf 需要内部转pdf
        if file_name.rsplit('.', 1)[-1] != 'pdf':
            b64_data = base64.b64encode(open(input_file, 'rb').read()).decode()
            inp = dict(filename=file_name, b64_data=[b64_data], mode='topdf')
            resp = requests.post(settings.get_knowledge().get('unstructured_api_url'),
                                 json=inp).json()
            if not resp or resp['status_code'] != 200:
                logger.error(f'file_pdf=not_success resp={resp}')
                raise Exception(f"当前文件无法解析， {resp['status_message']}")
            b64_data = resp['b64_pdf']
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
                                                  chunk_overlap=0)
        texts = text_splitter.split_documents(documents)
        raw_texts = [t.page_content for t in texts]
        metadatas = [{'bbox': json.dumps(t.metadata)} for t in texts]
    return (raw_texts, metadatas)
