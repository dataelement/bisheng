import json
import os
import re
import time
from typing import List, Optional
from uuid import uuid4

from bisheng.api.services.knowledge_imp import (addEmbedding, decide_vectorstores,
                                                delete_knowledge_file_vectors, retry_files)
from bisheng.api.services.user_service import UserPayload
from bisheng.api.utils import access_check
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500
from bisheng.cache.utils import file_download, save_uploaded_file
from bisheng.database.base import session_getter
from bisheng.database.models.group_resource import GroupResource, ResourceTypeEnum, GroupResourceDao
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeDao,
                                               KnowledgeRead)
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileRead)
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User
from bisheng.database.models.user_group import UserGroupDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi_jwt_auth import AuthJWT
from langchain_community.document_loaders import (BSHTMLLoader, PyPDFLoader, TextLoader,
                                                  UnstructuredMarkdownLoader,
                                                  UnstructuredPowerPointLoader,
                                                  UnstructuredWordDocumentLoader)
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
        separator = ['\n\n']
        chunk_size = 1000
        chunk_overlap = 100

    knowledge = KnowledgeDao.query_by_id(knowledge_id)
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
        md5_ = os.path.splitext(os.path.basename(filepath))[0].split('_')[0]
        # 是否包含重复文件
        content_repeat = KnowledgeFileDao.get_file_by_condition(md5_=md5_,
                                                                knowledge_id=knowledge_id)
        name_repeat = KnowledgeFileDao.get_file_by_condition(file_name=file_name,
                                                             knowledge_id=knowledge_id)
        if content_repeat or name_repeat:
            db_file = content_repeat[0] if content_repeat else name_repeat[0]
            old_name = db_file.file_name
            file_type = file_name.rsplit('.', 1)[-1]
            obj_name = f'tmp/{db_file.id}.{file_type}'
            db_file.object_name = obj_name
            db_file.remark = f'{file_name} 对应已存在文件 {old_name}'
            with open(filepath, 'rb') as file:
                MinioClient().upload_tmp(db_file.object_name, file.read())
            db_file.status = 3
        else:
            status = 1
            remark = ''
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
            files.append(db_file.copy())
            file_paths.append(filepath)

        logger.info(f'col={collection_name} repeat={db_file} file_id={db_file.id}')
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
    user_payload = UserPayload(**payload)
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
    create_knowledge_hook(db_knowldge, user_payload)
    return resp_200(db_knowldge.copy())


def create_knowledge_hook(knowledge: Knowledge, user_payload: UserPayload):
    # 查询下用户所在的用户组
    user_group = UserGroupDao.get_user_group(user_payload.user_id)
    if user_group:
        # 批量将助手资源插入到关联表里
        batch_resource = []
        for one in user_group:
            batch_resource.append(GroupResource(
                group_id=one.group_id,
                third_id=knowledge.id,
                type=ResourceTypeEnum.KNOWLEDGE.value))
        GroupResourceDao.insert_group_batch(batch_resource)
    return True


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
        logger.exception("get_knowledge error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 file_name: str = None,
                 knowledge_id: int,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: Optional[int] = None,
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
    count_sql = select(func.count(
        KnowledgeFile.id)).where(KnowledgeFile.knowledge_id == knowledge_id)
    list_sql = select(KnowledgeFile).where(KnowledgeFile.knowledge_id == knowledge_id)

    if file_name:
        file_name = file_name.strip()
        count_sql = count_sql.where(KnowledgeFile.file_name.like(f'%{file_name}%'))
        list_sql = list_sql.where(KnowledgeFile.file_name.like(f'%{file_name}%'))

    if status:
        count_sql = count_sql.where(KnowledgeFile.status == status)
        list_sql = list_sql.where(KnowledgeFile.status == status)

    with session_getter() as session:
        total_count = session.scalar(count_sql)
        files = session.exec(
            list_sql.order_by(KnowledgeFile.update_time.desc()).offset(
                page_size * (page_num - 1)).limit(page_size)).all()
    return resp_200({
        'data': [jsonable_encoder(knowledgefile) for knowledgefile in files],
        'total': total_count,
        'writeable': writable
    })


@router.post('/retry', status_code=200)
def retry(data: dict, background_tasks: BackgroundTasks, Authorize: AuthJWT = Depends()):
    """失败重试"""
    Authorize.jwt_required()
    db_file_retry = data.get('file_objs')
    if db_file_retry:
        id2input = {file.get('id'): KnowledgeFile.validate(file) for file in db_file_retry}
    else:
        return resp_500('参数错误')
    file_ids = list(id2input.keys())
    db_files = KnowledgeFileDao.select_list(file_ids=file_ids)
    for file in db_files:
        # file exist
        input_file = id2input.get(file.id)
        if input_file.remark and '对应已存在文件' in input_file.remark:
            file.file_name = input_file.remark.split(' 对应已存在文件 ')[0]
            file.remark = ''
        file.status = 1  # 解析中
        file = KnowledgeFileDao.update(file)
    background_tasks.add_task(retry_files, db_files, id2input)
    return resp_200()


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


def delete_knowledge_hook(knowledge: Knowledge, user_payload: UserPayload):
    logger.info(f'delete_knowledge_hook id={knowledge.id}, user: {user_payload.user_id}')
    GroupResourceDao.delete_group_resource_by_third_id(str(knowledge.id), ResourceTypeEnum.KNOWLEDGE)


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*, file_id: int, Authorize: AuthJWT = Depends()):
    """ 删除知识文件信息 """
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())

    knowledge_file = KnowledgeFileDao.select_list([file_id])
    if knowledge_file:
        knowledge_file = knowledge_file[0]
    knowledge = KnowledgeDao.query_by_id(knowledge_file.knowledge_id)
    if not access_check(payload, knowledge.user_id, knowledge.id, AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    # 处理vectordb
    delete_knowledge_file_vectors([file_id])
    KnowledgeFileDao.delete_batch([file_id])

    return resp_200(message='删除成功')
