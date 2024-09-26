import urllib.parse
import json
import os
import re
import time
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, Request, Body, Query

from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import retry_files
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500, PreviewFileChunk, \
    UpdatePreviewFileChunk, KnowledgeFileProcess
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.models.knowledge import KnowledgeCreate, KnowledgeRead, KnowledgeUpdate, KnowledgeDao
from bisheng.database.models.knowledge_file import KnowledgeFile, KnowledgeFileDao
from bisheng.utils.logger import logger
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.services import knowledge_imp
from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.services.knowledge_imp import (add_qa, addEmbedding, decide_vectorstores,
                                                delete_knowledge_file_vectors, retry_files)
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.utils import get_request_ip
from bisheng.api.v1.schemas import UnifiedResponseModel, UploadFileResponse, resp_200, resp_500
from bisheng.cache.utils import file_download, save_uploaded_file
from bisheng.database.base import session_getter
from bisheng.database.models.group_resource import GroupResource, GroupResourceDao, ResourceTypeEnum
from bisheng.database.models.knowledge import (Knowledge, KnowledgeCreate, KnowledgeDao,
                                               KnowledgeRead, KnowledgeTypeEnum)
from bisheng.database.models.knowledge_file import (KnowledgeFile, KnowledgeFileDao,
                                                    KnowledgeFileRead, QAKnoweldgeDao,
                                                    QAKnowledgeUpsert)
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.settings import settings
from bisheng.utils.logger import logger
from bisheng.utils.minio_client import MinioClient
from bisheng_langchain.vectorstores import ElasticKeywordsSearch
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Request,
                     UploadFile)
from fastapi.encoders import jsonable_encoder
from pymilvus import Collection
from sqlalchemy import delete, func, or_
from sqlmodel import select

# build router
router = APIRouter(prefix='/knowledge', tags=['Knowledge'])


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
        logger.exception(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/preview')
async def preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                             req_data: PreviewFileChunk):
    """ 获取某个文件的分块预览内容 """
    try:
        parse_type, file_share_url, res, partitions = KnowledgeService.get_preview_file_chunk(request, login_user,
                                                                                              req_data)
        return resp_200(data={
            "parse_type": parse_type,
            "file_url": file_share_url,
            "chunks": res,
            "partitions": partitions
        })
    except Exception as e:
        logger.exception('preview_file_chunk_error')
        return resp_500(data=str(e))


@router.put('/preview')
async def update_preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 更新某个文件的分块预览内容 """

    res = KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 删除某个文件的分块预览内容 """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
async def process_knowledge_file(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                 background_tasks: BackgroundTasks, req_data: KnowledgeFileProcess):
    """ 上传文件到知识库内 """
    res = KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)
    return resp_200(res)


@router.post('/create', response_model=UnifiedResponseModel[KnowledgeRead], status_code=201)
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge: KnowledgeCreate):
    """ 创建知识库. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.get('', status_code=200)
def get_knowledge(*,
                  request: Request,
                  login_user: UserPayload = Depends(get_login_user),
                  name: str = None,
                  page_size: Optional[int] = 10,
                  page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    res, total = KnowledgeService.get_knowledge(request, login_user, name, page_num, page_size)
    return resp_200(data={
        'data': res,
        'total': total
    })


@router.put('/', status_code=200)
async def update_knowledge(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                           knowledge: KnowledgeUpdate):
    res = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(data=res)


@router.delete('/', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge_id: int = Body(..., embed=True)):
    """ 删除知识库信息. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='删除成功')


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 request: Request,
                 login_user: UserPayload = Depends(get_login_user),
                 file_name: str = None,
                 knowledge_id: int = 0,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: Optional[int] = None):
    """ 获取知识库文件信息. """
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id, file_name, status,
                                                             page_num, page_size)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.get('/qa/list/{qa_knowledge_id}', status_code=200)
def get_QA_list(*,
                qa_knowledge_id: int,
                page_size: int = 10,
                page_num: int = 1,
                question: Optional[str] = None,
                answer: Optional[str] = None,
                keyword: Optional[str] = None,
                status: Optional[int] = None,
                login_user: UserPayload = Depends(get_login_user)):
    """ 获取知识库文件信息. """

    # 查询当前知识库，是否有写入权限
    with session_getter() as session:
        db_knowledge: Knowledge = session.get(Knowledge, qa_knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=500, detail='当前知识库不可用，返回上级目录')
    if not login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                   AccessType.KNOWLEDGE):
        return UnAuthorizedError.return_resp()

    if db_knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库为普通知识库')

    if keyword:
        question = keyword

    qa_list, total_count = knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                 page_num, question, answer,
                                                                 status)
    user_list = UserDao.get_user_by_ids([qa.user_id for qa in qa_list])
    user_map = {
        user.user_id: user.user_name
        for user in user_list
    }
    data = [jsonable_encoder(qa) for qa in qa_list]
    for qa in data:
        qa['questions'] = qa['questions'][0]
        qa['answers'] = json.loads(qa['answers'])[0]
        qa['user_name'] = user_map.get(qa['user_id'], qa['user_id'])

    return resp_200({
        'data': data,
        'total': total_count,
        'writeable':
            login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                    AccessType.KNOWLEDGE_WRITE)
    })


@router.post('/retry', status_code=200)
def retry(*, request: Request, login_user: UserPayload = Depends(get_login_user),
          background_tasks: BackgroundTasks,
          req_data: dict):
    """失败重试"""
    KnowledgeService.retry_files(request, login_user, background_tasks, req_data)
    return resp_200()


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     knowledge_id: int,
                     login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识库信息. """

    with session_getter() as session:
        knowledge = session.get(Knowledge, knowledge_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')
    if not login_user.access_check(knowledge.user_id, str(knowledge_id),
                                   AccessType.KNOWLEDGE_WRITE):
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
    delete_knowledge_hook(request, knowledge, login_user)
    return resp_200(message='删除成功')


def delete_knowledge_hook(request: Request, knowledge: Knowledge, login_user: UserPayload):
    logger.info(f'delete_knowledge_hook id={knowledge.id}, user: {login_user.user_id}')

    # 删除知识库的审计日志
    AuditLogService.delete_knowledge(login_user, get_request_ip(request), knowledge)

    GroupResourceDao.delete_group_resource_by_third_id(str(knowledge.id),
                                                       ResourceTypeEnum.KNOWLEDGE)


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(message='删除成功')


@router.get('/chunk', status_code=200)
async def get_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                              knowledge_id: int = Query(..., description='知识库ID'),
                              file_ids: List[int] = Query(default=[], description='文件ID'),
                              keyword: str = Query(default='', description='关键字'),
                              page: int = Query(default=1, description='页数'),
                              limit: int = Query(default=10, description='每页条数条数')):
    """ 获取知识库分块内容 """
    # 为了解决keyword参数有时候没有进行urldecode的bug
    if keyword.startswith("%"):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids, keyword, page,
                                                       limit)
    return resp_200(data={
        "data": res,
        "total": total
    })


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号'),
                                 text: str = Body(..., embed=True, description='分块内容'),
                                 bbox: str = Body(default='', embed=True, description='分块框选位置')):
    """ 更新知识库分块内容 """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id, chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request, login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号')):
    """ 删除知识库分块内容 """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id, chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request, login_user: UserPayload = Depends(get_login_user),
                             file_id: int = Query(description='文件唯一ID')):
    url = KnowledgeService.get_file_share_url(request, login_user, file_id)
    return resp_200(data=url)


@router.get('/file_bbox')
async def get_file_bbox(request: Request, login_user: UserPayload = Depends(get_login_user),
                        file_id: int = Query(description='文件唯一ID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)


@router.post('/qa/add', status_code=200)
def qa_add(*, QACreate: QAKnowledgeUpsert, login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    QACreate.user_id = login_user.user_id
    db_knowledge = KnowledgeDao.query_by_id(QACreate.knowledge_id)
    if db_knowledge.type != KnowledgeTypeEnum.QA.value:
        raise HTTPException(status_code=404, detail='知识库类型错误')

    add_qa(db_knowledge=db_knowledge, data=QACreate)
    return resp_200()


@router.post('/qa/status_switch', status_code=200)
def qa_status_switch(*,
                     status: int = Body(embed=True),
                     id: int = Body(embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    """ 修改知识库信息. """

    return resp_200(knowledge_imp.qa_status_change(id, status))


@router.get('/qa/detail', status_code=200)
def qa_list(*, id: int, login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    qa_knowledge = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    qa_knowledge.answers = json.loads(qa_knowledge.answers)[0]
    return resp_200(data=qa_knowledge)


@router.post('/qa/append', status_code=200)
def qa_append(
        *,
        ids: list[int] = Body(..., embed=True),
        question: str = Body(..., embed=True),
        login_user: UserPayload = Depends(get_login_user),
):
    """ 增加知识库信息. """
    QA_list = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(QA_list[0].knowledge_id)
    for qa in QA_list:
        qa.questions.append(question)
        knowledge_imp.add_qa(knowledge, qa)
    return resp_200()


@router.delete('/qa/delete', status_code=200)
def qa_delete(*,
              ids: list[int] = Body(embed=True),
              login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    knowledge_dbs = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(knowledge_dbs[0].knowledge_id)
    if not login_user.access_check(knowledge.user_id, str(knowledge.id),
                                   AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    if knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库类型错误')

    QAKnoweldgeDao.delete_batch(ids)
    # knowledge_imp.delete_vector_data(knowledge.id, ids)
    return resp_200()


@router.post('/qa/auto_question')
def qa_auto_question(
        *,
        number: int = Body(default=3, embed=True),
        ori_question: str = Body(default='', embed=True),
        answer: str = Body(default='', embed=True),
):
    """通过大模型自动生成问题"""
    questions = knowledge_imp.recommend_question(ori_question, number=number, answer=answer)
    return resp_200(data={'questions': questions})
