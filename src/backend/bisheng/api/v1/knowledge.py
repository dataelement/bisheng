import os
import re
import time
from typing import List, Optional
from uuid import uuid4

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.utils import get_request_ip
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge_imp import (addEmbedding, decide_vectorstores,
                                                delete_knowledge_file_vectors, retry_files)
from bisheng.api.services.user_service import UserPayload, get_login_user
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
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Request, Path
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


@router.post('/process',
             response_model=UnifiedResponseModel[List[KnowledgeFileRead]],
             status_code=201)
async def process_knowledge(*,
                            request: Request,
                            data: dict,
                            background_tasks: BackgroundTasks,
                            login_user: UserPayload = Depends(get_login_user)):
    """上传文件到知识库.
    使用flowchain来处理embeding的流程
        """

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
    if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
        return UnAuthorizedError.return_resp()

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
                                    user_id=login_user.user_id)
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

    upload_knowledge_file_hook(request, login_user, knowledge_id, files)
    return resp_200(result)


def upload_knowledge_file_hook(request: Request, login_user: UserPayload, knowledge_id: int,
                               file_list: List[KnowledgeFile]):
    logger.info(f'act=upload_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge_id}')
    # 记录审计日志
    file_name = ""
    for one in file_list:
        file_name += "\n\n" + one.file_name
    AuditLogService.upload_knowledge_file(login_user, get_request_ip(request), knowledge_id, file_name)


@router.post('/create', response_model=UnifiedResponseModel[KnowledgeRead], status_code=201)
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge: KnowledgeCreate):
    """ 创建知识库. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.get('/', status_code=200)
def get_knowledge(*,
                  request: Request,
                  login_user: UserPayload = Depends(get_login_user),
                  name: str = None,
                  page_size: Optional[int] = 1,
                  page_num: Optional[int] = 10):
    """ 读取所有知识库信息. """
    res, total = KnowledgeService.get_knowledge(request, login_user, name, page_num, page_size)
    return resp_200(data={
        'data': res,
        'total': total
    })


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 file_name: str = None,
                 knowledge_id: int,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: Optional[int] = None,
                 login_user: UserPayload = Depends(get_login_user)):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge = session.get(Knowledge, knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE):
        return UnAuthorizedError.return_resp()

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
        'writeable': login_user.access_check(db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE)
    })


@router.post('/retry', status_code=200)
def retry(data: dict, background_tasks: BackgroundTasks, login_user: UserPayload = Depends(get_login_user)):
    """失败重试"""
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
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge_id: int = Path(...)):
    """ 删除知识库信息. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='删除成功')


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """

    knowledge_file = KnowledgeFileDao.select_list([file_id])
    if knowledge_file:
        knowledge_file = knowledge_file[0]
    knowledge = KnowledgeDao.query_by_id(knowledge_file.knowledge_id)
    if not login_user.access_check(knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    # 处理vectordb
    delete_knowledge_file_vectors([file_id])
    KnowledgeFileDao.delete_batch([file_id])

    # 删除知识库文件的审计日志
    delete_knowledge_file_hook(request, login_user, knowledge.id, [knowledge_file])

    return resp_200(message='删除成功')


def delete_knowledge_file_hook(request: Request, login_user: UserPayload, knowledge_id: int,
                               file_list: List[KnowledgeFile]):
    logger.info(f'act=delete_knowledge_file_hook user={login_user.user_name} knowledge_id={knowledge_id}')
    # 记录审计日志
    # 记录审计日志
    file_name = ""
    for one in file_list:
        file_name += "\n\n" + one.file_name
    AuditLogService.delete_knowledge_file(login_user, get_request_ip(request), knowledge_id, file_name)
