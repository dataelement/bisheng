import asyncio
import json
import urllib.parse
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Any

import pandas as pd
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import add_qa
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import (KnowledgeFileProcess, UpdatePreviewFileChunk, UploadFileResponse,
                                    UpdateKnowledgeReq, KnowledgeFileReProcess)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeCPError, KnowledgeQAError, KnowledgeRebuildingError, \
    KnowledgePreviewError, KnowledgeNotQAError, KnowledgeNoEmbeddingError, KnowledgeNotExistError
from bisheng.common.errcode.server import NoLlmModelConfigError
from bisheng.common.schemas.api import resp_200, resp_500, resp_502, UnifiedResponseModel
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.user import UserDao
from bisheng.knowledge.api.dependencies import get_knowledge_service, get_knowledge_file_service
from bisheng.knowledge.domain.models.knowledge import (KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum,
                                                       KnowledgeUpdate)
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import (KnowledgeFileDao, KnowledgeFileStatus,
                                                            QAKnoweldgeDao, QAKnowledgeUpsert, QAStatus)
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, \
    UpdateKnowledgeMetadataFieldsReq, ModifyKnowledgeFileMetaDataReq
from bisheng.llm.const import LLMModelType
from bisheng.llm.models import LLMDao
from bisheng.utils import generate_uuid, calc_data_sha256
from bisheng.worker.knowledge.qa import insert_qa_celery

# build router
router = APIRouter(prefix='/knowledge', tags=['Knowledge'])


@router.post('/upload')
async def upload_file(*, file: UploadFile = File(...)):
    file_name = file.filename
    # 缓存本地
    uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)
    file_path = await save_uploaded_file(file, 'bisheng', uuid_file_name)
    if not isinstance(file_path, str):
        file_path = str(file_path)
    return resp_200(UploadFileResponse(file_path=file_path))


@router.post('/upload/{knowledge_id}')
async def upload_knowledge_file(*, request: Request, login_user: UserPayload = Depends(get_login_user),
                                knowledge_id: int,
                                file: UploadFile = File(...)):
    """ 知识库上传文件，需要判断文件是否在知识库内重复 """

    file_name = file.filename
    # 缓存本地
    uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)
    file_path = await save_uploaded_file(file, 'bisheng', uuid_file_name)
    if not isinstance(file_path, str):
        file_path = str(file_path)

    # calc file md5 and check
    file_bytes = await file.read()
    file_md5 = await asyncio.to_thread(calc_data_sha256, file_bytes)

    repeat_file = await KnowledgeFileDao.get_repeat_file(
        knowledge_id=knowledge_id, file_name=file_name, md5_=file_md5
    )
    ret = UploadFileResponse(file_path=file_path)
    if repeat_file:
        ret.repeat = True
        ret.repeat_update_time = repeat_file.update_time

    return resp_200(ret)


@router.post('/preview')
async def preview_file_chunk(*,
                             request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             background_tasks: BackgroundTasks,
                             req_data: KnowledgeFileProcess):
    """ 获取某个文件的分块预览内容 """

    preview_file_id = generate_uuid()
    redis_key = f'preview_file:{preview_file_id}'
    redis_client = await get_redis_client()
    await redis_client.aset(redis_key, {"status": "processing"})

    async def exec_task():
        try:
            parse_type, file_share_url, res, partitions = await KnowledgeService.get_preview_file_chunk(request,
                                                                                                        login_user,
                                                                                                        req_data)
            await redis_client.aset(redis_key, {
                "status": "completed",
                "data": {
                    'parse_type': parse_type,
                    'file_url': file_share_url,
                    'chunks': [one.model_dump() for one in res],
                    'partitions': partitions
                }
            })
        except Exception as exc:
            logger.exception(f'Preview file chunk error: {exc}')
            await redis_client.aset(redis_key, {
                "status": "error"
            })

    background_tasks.add_task(exec_task)
    return resp_200(data={'preview_file_id': preview_file_id})


@router.get('/preview/status')
async def get_preview_file_status(
        request: Request,
        login_user: UserPayload = Depends(get_login_user),
        preview_file_id: str = Query(..., description='预览接口返回的文件ID')):
    redis_key = f'preview_file:{preview_file_id}'
    redis_client = await get_redis_client()
    file_status = await redis_client.aget(redis_key)
    if not file_status:
        raise KnowledgePreviewError.http_exception()
    if file_status.get('status') == 'error':
        raise KnowledgePreviewError.http_exception()
    if file_status.get('status') == 'completed':
        await redis_client.aexpire_key(redis_key, 10)
    return resp_200(data=file_status)


@router.put('/preview')
async def update_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 更新某个文件的分块预览内容 """

    res = await KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 删除某个文件的分块预览内容 """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
def process_knowledge_file(*,
                           request: Request,
                           login_user: UserPayload = Depends(get_login_user),
                           background_tasks: BackgroundTasks,
                           req_data: KnowledgeFileProcess):
    """ 上传文件到知识库内 """

    res = KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)
    return resp_200(res)


# 修改分段重新处理
@router.post("/process/rebuild")
async def rebuild_knowledge_file(*,
                                 request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 req_data: KnowledgeFileReProcess):
    """ 重新处理知识库文件 """

    res = await KnowledgeService.rebuild_knowledge_file(request, login_user, req_data)
    return resp_200(res)


@router.post('/create')
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge: KnowledgeCreate):
    """ 创建知识库. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.post('/copy')
async def copy_knowledge(*,
                         request: Request,
                         background_tasks: BackgroundTasks,
                         login_user: UserPayload = Depends(get_login_user),
                         knowledge_id: int = Body(..., embed=True)):
    """ 复制知识库. """
    knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)

    if not login_user.is_admin and knowledge.user_id != login_user.user_id:
        return UnAuthorizedError.return_resp()

    knowledge_count = await KnowledgeFileDao.async_count_file_by_filters(
        knowledge_id,
        status=[KnowledgeFileStatus.PROCESSING.value],
    )
    if knowledge.state != KnowledgeState.PUBLISHED.value or knowledge_count > 0:
        return KnowledgeCPError.return_resp()
    knowledge = await KnowledgeService.copy_knowledge(request, background_tasks, login_user, knowledge)
    return resp_200(knowledge)


@router.post("/qa/copy")
async def copy_qa_knowledge(*,
                            request: Request,
                            login_user: UserPayload = Depends(get_login_user),
                            knowledge_id: int = Body(..., embed=True)):
    """
    复制QA知识库.
    :param request:
    :param login_user:
    :param knowledge_id:
    :return:
    """

    qa_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not login_user.is_admin and qa_knowledge.user_id != login_user.user_id:
        return UnAuthorizedError.return_resp()

    if qa_knowledge.type != KnowledgeTypeEnum.QA.value:
        return KnowledgeNotQAError.return_resp()

    qa_knowledge_count = await QAKnoweldgeDao.async_count_by_id(qa_id=qa_knowledge.id)

    if qa_knowledge.state != KnowledgeState.PUBLISHED.value or qa_knowledge_count == 0:
        return KnowledgeCPError.return_resp()

    knowledge = await KnowledgeService.copy_qa_knowledge(request, login_user, qa_knowledge)

    return resp_200(knowledge)


@router.get('', status_code=200)
async def get_knowledge(*,
                        request: Request,
                        login_user: UserPayload = Depends(get_login_user),
                        name: str = None,
                        knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value,
                                                    alias='type'),
                        page_size: Optional[int] = 10,
                        page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    res, total = await KnowledgeService.get_knowledge(request, login_user, knowledge_type, name,
                                                      page_num, page_size)
    return resp_200(data={'data': res, 'total': total})


@router.get('/info', status_code=200)
def get_knowledge_info(*,
                       request: Request,
                       login_user: UserPayload = Depends(get_login_user),
                       knowledge_id: List[int] = Query(...)):
    """ 根据知识库ID读取知识库信息. """
    res = KnowledgeService.get_knowledge_info(request, login_user, knowledge_id)
    return resp_200(data=res)


@router.put('/', status_code=200)
async def update_knowledge(*,
                           request: Request,
                           login_user: UserPayload = Depends(get_login_user),
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


# 个人知识库信息获取
@router.get('/personal_knowledge_info', status_code=200)
def get_personal_knowledge_info(
        login_user: UserPayload = Depends(get_login_user)):
    """ 获取个人知识库信息. """
    knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                KnowledgeTypeEnum.PRIVATE)

    return resp_200(data=knowledge)


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 request: Request,
                 login_user: UserPayload = Depends(get_login_user),
                 file_name: str = None,
                 file_ids: list[int] = None,
                 knowledge_id: int = 0,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: List[int] = Query(default=None)):
    """ 获取知识库文件信息. """
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id,
                                                             file_name, status, page_num,
                                                             page_size, file_ids)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.get('/qa/list/{qa_knowledge_id}', status_code=200)
async def get_QA_list(*,
                      qa_knowledge_id: int,
                      page_size: int = 10,
                      page_num: int = 1,
                      question: Optional[str] = None,
                      answer: Optional[str] = None,
                      keyword: Optional[str] = None,
                      status: Optional[int] = None,
                      login_user: UserPayload = Depends(get_login_user)):
    """ 获取知识库文件信息. """
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    qa_list, total_count = await knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                       page_num, question, answer,
                                                                       keyword, status)
    user_list = UserDao.get_user_by_ids([qa.user_id for qa in qa_list])
    user_map = {user.user_id: user.user_name for user in user_list}
    data = [jsonable_encoder(qa) for qa in qa_list]
    for qa in data:
        qa['questions'] = qa['questions'][0]
        qa['answers'] = json.loads(qa['answers'])[0]
        qa['user_name'] = user_map.get(qa['user_id'], qa['user_id'])

    return resp_200({
        'data':
            data,
        'total':
            total_count,
        'writeable':
            login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                    AccessType.KNOWLEDGE_WRITE)
    })


@router.post('/retry', status_code=200)
def retry(*,
          request: Request,
          login_user: UserPayload = Depends(get_login_user),
          background_tasks: BackgroundTasks,
          req_data: dict):
    """失败重试"""
    KnowledgeService.retry_files(request, login_user, background_tasks, req_data)
    return resp_200()


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(message='删除成功')


@router.get('/chunk', status_code=200)
async def get_knowledge_chunk(request: Request,
                              login_user: UserPayload = Depends(get_login_user),
                              knowledge_id: int = Query(..., description='知识库ID'),
                              file_ids: List[int] = Query(default=[], description='文件ID'),
                              keyword: str = Query(default='', description='关键字'),
                              page: int = Query(default=1, description='页数'),
                              limit: int = Query(default=10, description='每页条数条数')):
    """ 获取知识库分块内容 """
    # 为了解决keyword参数有时候没有进行urldecode的bug
    if keyword.startswith('%'):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids,
                                                       keyword, page, limit)
    return resp_200(data={'data': res, 'total': total})


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号'),
                                 text: str = Body(..., embed=True, description='分块内容'),
                                 bbox: str = Body(default='', embed=True, description='分块框选位置')):
    """ 更新知识库分块内容 """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号')):
    """ 删除知识库分块内容 """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             file_id: int = Query(description='文件唯一ID')):
    original_url, preview_url = KnowledgeService.get_file_share_url(file_id)
    return resp_200(data={
        'original_url': original_url,
        'preview_url': preview_url
    })


@router.get('/file_bbox')
async def get_file_bbox(request: Request,
                        login_user: UserPayload = Depends(get_login_user),
                        file_id: int = Query(description='文件唯一ID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)


@router.post('/qa/add', status_code=200)
async def qa_add(*, QACreate: QAKnowledgeUpsert,
                 login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    QACreate.user_id = login_user.user_id
    db_knowledge = KnowledgeDao.query_by_id(QACreate.knowledge_id)
    if db_knowledge.type != KnowledgeTypeEnum.QA.value:
        raise HTTPException(status_code=404, detail='知识库类型错误')
    if not login_user.access_check(
            db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()

    db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id, exclude_id=QACreate.id)
    # create repeat question or update
    if (db_q and not QACreate.id) or (db_q and QACreate.id and db_q.id != QACreate.id):
        raise KnowledgeQAError.http_exception()

    add_qa(db_knowledge=db_knowledge, data=QACreate)
    return resp_200()


@router.post('/qa/status_switch', status_code=200)
def qa_status_switch(*,
                     status: int = Body(embed=True),
                     id: int = Body(embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    """ 修改知识库信息. """
    qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    if qa_db.status == status:
        return resp_200()
    db_knowledge = KnowledgeDao.query_by_id(qa_db.knowledge_id)
    if not login_user.access_check(
            db_knowledge.user_id, str(db_knowledge.id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()

    new_qa_db = knowledge_imp.qa_status_change(qa_db, status, db_knowledge)
    if not new_qa_db:
        return resp_200()
    if new_qa_db.status != status:
        # 说明状态切换失败
        return resp_500(message=f'状态切换失败: {new_qa_db.remark}')
    return resp_200()


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
    # check knowledge access
    if not login_user.access_check(
            knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()

    for q in QA_list:
        if question in q.questions:
            raise KnowledgeQAError.http_exception()
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

    knowledge_imp.delete_vector_data(knowledge, ids)
    QAKnoweldgeDao.delete_batch(ids)
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


@router.get('/qa/export/template', status_code=200)
async def get_export_url():
    data = [{"问题": "", "答案": "", "相似问题1": "", "相似问题2": ""}]
    df = pd.DataFrame(data)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
    file_name = f"QA知识库导入模板.xlsx"
    bio.seek(0)
    file = UploadFile(filename=file_name, file=bio)
    file_path = await save_uploaded_file(file, 'bisheng', file_name)
    return resp_200({"url": file_path})


@router.get('/qa/export/{qa_knowledge_id}', status_code=200)
async def get_export_url(*,
                         qa_knowledge_id: int,
                         question: Optional[str] = None,
                         answer: Optional[str] = None,
                         keyword: Optional[str] = None,
                         status: Optional[int] = None,
                         max_lines: Optional[int] = 10000,
                         login_user: UserPayload = Depends(get_login_user)):
    # 查询当前知识库，是否有写入权限
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    if keyword:
        question = keyword

    def get_qa_source(source):
        '0: 未知 1: 手动；2: 审计, 3: api'
        if int(source) == 1:
            return "手动创建"
        elif int(source) == 2:
            return "审计创建"
        elif int(source) == 3:
            return "api创建"
        return "未知"

    def get_status(statu):
        if int(statu) == 1:
            return "开启"
        return "关闭"

    page_num = 1
    total_num = 0
    page_size = max_lines
    user_list = UserDao.get_all_users()
    user_map = {user.user_id: user.user_name for user in user_list}
    file_list = []
    file_pr = datetime.now().strftime('%Y%m%d%H%M%S')
    file_index = 1
    while True:
        qa_list, total_count = await knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                           page_num, question, answer,
                                                                           status)

        data = [jsonable_encoder(qa) for qa in qa_list]
        qa_dict_list = []
        all_title = ["问题", "答案"]
        for qa in data:
            qa_dict_list.append({
                "问题": qa['questions'][0],
                "答案": json.loads(qa['answers'])[0],
                # "类型":get_qa_source(qa['source']),
                # "创建时间":qa['create_time'],
                # "更新时间":qa['update_time'],
                # "创建者":user_map.get(qa['user_id'], qa['user_id']),
                # "状态":get_status(qa['status']),
            })
            for index, question in enumerate(qa['questions']):
                if index == 0:
                    continue
                key = f"相似问题{index}"
                if key not in all_title:
                    all_title.append(key)
                qa_dict_list[-1][key] = question
        if len(qa_dict_list) != 0:
            df = pd.DataFrame(qa_dict_list)
        else:
            df = pd.DataFrame([{"问题": "", "答案": "", "相似问题1": "", "相似问题2": ""}])
        df = df[all_title]
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        file_name = f"{file_pr}_{file_index}.xlsx"
        file_index = file_index + 1
        bio.seek(0)
        file_io = UploadFile(filename=file_name, file=bio)
        file_path = await save_uploaded_file(file_io, 'bisheng', file_name)
        file_list.append(file_path)
        total_num += len(qa_list)
        if len(qa_list) < page_size or total_num >= total_count:
            break

    return resp_200({"file_list": file_list})


def convert_excel_value(value: Any):
    if value is None or value == "":
        return ''
    if str(value) == 'nan' or str(value) == 'null':
        return ''
    return str(value)


@router.post('/qa/preview/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_url: str = Body(..., embed=True),
                     size: Optional[int] = Body(default=0, embed=True),
                     offset: Optional[int] = Body(default=0, embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    df = pd.read_excel(file_url)
    columns = df.columns.to_list()
    if '答案' not in columns or '问题' not in columns:
        raise HTTPException(status_code=500, detail='文件格式错误，没有 ‘问题’ 或 ‘答案’ 列')
    data = df.T.to_dict().values()
    insert_data = []
    for dd in data:
        d = QAKnowledgeUpsert(
            user_id=login_user.user_id,
            knowledge_id=qa_knowledge_id,
            answers=[convert_excel_value(dd['答案'])],
            questions=[convert_excel_value(dd['问题'])],
            source=4,
            create_time=datetime.now(),
            update_time=datetime.now())
        for key, value in dd.items():
            if key.startswith('相似问题') and convert_excel_value(value):
                d.questions.append(convert_excel_value(value))
        insert_data.append(d)
    try:
        if size > 0 and offset >= 0:
            if offset >= len(insert_data):
                insert_data = []
            else:
                insert_data = insert_data[offset:size]
    except Exception as e:
        raise HTTPException(status_code=500, detail=e)
    return resp_200({"result": insert_data})


@router.post('/qa/import/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_list: list[str] = Body(..., embed=True),
                     background_tasks: BackgroundTasks,
                     login_user: UserPayload = Depends(get_login_user)):
    # 查询当前知识库，是否有写入权限
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    insert_result = []
    error_result = []
    have_question = []
    for file_url in file_list:
        df = pd.read_excel(file_url)
        columns = df.columns.to_list()
        if '答案' not in columns or '问题' not in columns:
            insert_result.append(0)
            continue
        data = df.T.to_dict().values()
        insert_data = []
        have_data = []
        all_questions = set()
        for index, dd in enumerate(data):
            tmp_questions = set()
            dd_question = convert_excel_value(dd['问题'])
            dd_answer = convert_excel_value(dd['答案'])
            QACreate = QAKnowledgeUpsert(
                user_id=login_user.user_id,
                knowledge_id=qa_knowledge_id,
                answers=[dd_answer],
                questions=[dd_question],
                source=4,
                status=QAStatus.PROCESSING.value)
            tmp_questions.add(QACreate.questions[0])
            for key, value in dd.items():
                if key.startswith('相似问题'):
                    if tmp_value := convert_excel_value(value):
                        if tmp_value not in tmp_questions:
                            QACreate.questions.append(tmp_value)
                            tmp_questions.add(tmp_value)

            db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id)
            if (db_q and not QACreate.id) or len(tmp_questions & all_questions) > 0 or not dd_question or not dd_answer:
                have_data.append(index)
            else:
                insert_data.append(QACreate)
                all_questions = all_questions | tmp_questions
        result = QAKnoweldgeDao.batch_insert_qa(insert_data)

        # async task add qa into milvus and es
        for one in result:
            insert_qa_celery.delay(one.id)

        error_result.append(have_data)

    return resp_200({"errors": error_result})


@router.get('/status', status_code=200)
def get_knowledge_status(*, login_user: UserPayload = Depends(get_login_user)):
    """
    查看知识库状态接口
    流程：
    1. 根据用户id先判断用户有没有个人知识库，没有直接返回200
    2. 如果拥有知识库，根据用户id查看所在知识库状态，如果个人知识库的状态处于REBUILDING 3 或者 FAILED 4 时，
       返回 "个人知识库embedding模型已更换，正在重建知识库，请稍后再试" 状态码 502
    """
    # 查询用户的个人知识库
    user_private_knowledge = KnowledgeDao.get_user_knowledge(
        login_user.user_id,
        None,
        KnowledgeTypeEnum.PRIVATE
    )

    # 如果用户没有个人知识库，直接返回200
    if not user_private_knowledge:
        return resp_200({"status": "success"})

    # 获取第一个个人知识库（通常用户只有一个个人知识库）
    private_knowledge = user_private_knowledge[0]

    # 检查知识库状态

    if private_knowledge.state == KnowledgeState.REBUILDING.value:
        # 返回502状态码和相应提示信息
        return resp_502(
            message="个人知识库embedding模型已更换，正在重建知识库，请稍后再试"
        )
    if private_knowledge.state == KnowledgeState.FAILED.value:
        # 延迟导入以避免循环导入
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
        rebuild_knowledge_celery.delay(private_knowledge.id, str(private_knowledge.model))
        # 返回502状态码和相应提示信息
        return resp_502(
            message="个人知识库embedding模型已更换，正在重建知识库，请稍后再试"
        )

    # 知识库状态正常，返回200
    return resp_200({"status": "success"})


@router.post('/update_knowledge', status_code=200)
def update_knowledge_model(*,
                           login_user: UserPayload = Depends(get_login_user),
                           req_data: UpdateKnowledgeReq):
    """
    更新知识库接口
    更新embedding模型时重建知识库
    流程：
    1. 根据前端传进来的model_id, model_type，先判断是不是embedding模型
    2. 如果不是则返回resp501("不是embedding模型") 如果是则把knowledge表中所有type为2的数据status改成3，model改成传入的model_id
    3. 每一个knowledge_id都发起异步任务进行知识库重建
    """
    try:
        # 1. 验证是否为embedding模型
        model_info = LLMDao.get_model_by_id(req_data.model_id)
        if not model_info:
            return NoLlmModelConfigError.return_resp()

        # 如果前端没有传model_type，使用数据库中的model_type
        model_type = req_data.model_type if req_data.model_type else model_info.model_type

        if model_type != LLMModelType.EMBEDDING.value:
            return KnowledgeNoEmbeddingError.return_resp()

        # 处理指定的知识库
        knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
        if not knowledge:
            return KnowledgeNotExistError.return_resp()

        if not login_user.access_check(
                knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
        ):
            return UnAuthorizedError.return_resp()

        old_model_id = knowledge.model

        # 更新知识库状态和模型
        knowledge.model = str(req_data.model_id)
        knowledge.name = req_data.knowledge_name
        knowledge.description = req_data.description

        if int(old_model_id) == int(req_data.model_id):
            # 如果模型没有变化，不需要重建
            KnowledgeDao.update_one(knowledge)
            return resp_200(
                message="知识库模型未更改，无需重建"
            )
        if knowledge.state == KnowledgeState.REBUILDING.value:
            return KnowledgeRebuildingError.return_resp()

        knowledge.state = KnowledgeState.REBUILDING.value
        KnowledgeDao.update_one(knowledge)

        # 发起异步任务

        if knowledge.type == KnowledgeTypeEnum.NORMAL.value:

            # 延迟导入以避免循环导入
            from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
            rebuild_knowledge_celery.delay(knowledge.id, str(req_data.model_id))

        elif knowledge.type == KnowledgeTypeEnum.QA.value:

            # 延迟导入以避免循环导入
            from bisheng.worker.knowledge.qa import rebuild_qa_knowledge_celery
            rebuild_qa_knowledge_celery.delay(knowledge.id, str(req_data.model_id))

        logger.info(f"Started rebuild task for knowledge_id={knowledge.id} with model_id={req_data.model_id}")

        return resp_200(
            message="已开始重建知识库"
        )

    except Exception as e:
        logger.exception(f"rebuilding knowledge error: {str(e)}")
        return resp_500(message=f"重建知识库失败: {str(e)}")


@router.get("/file/info/{file_id}", description="获取知识库文件信息", response_model=UnifiedResponseModel)
async def get_knowledge_file_info(*,
                                    login_user: UserPayload = Depends(get_login_user),
                                    file_id: int,
                                    knowledge_file_service=Depends(get_knowledge_file_service)):
    """
    获取知识库文件信息
    Args:
        login_user:
        file_id:
        knowledge_file_service:

    Returns:

    """

    knowledge_file_model = await knowledge_file_service.get_knowledge_file_info(login_user, file_id)
    return resp_200(data=knowledge_file_model)

# 为知识库添加元数据字段
@router.post('/add_metadata_fields', description="为知识库添加元数据字段", response_model=UnifiedResponseModel)
async def add_metadata_fields(*,
                              login_user: UserPayload = Depends(get_login_user),
                              req_data: AddKnowledgeMetadataFieldsReq,
                              knowledge_service=Depends(get_knowledge_service)):
    """
    为知识库添加元数据字段
    """

    knowledge_model = await knowledge_service.add_metadata_fields(login_user, req_data)

    return resp_200(data=knowledge_model)


# 修改知识库元数据字段
@router.put('/update_metadata_fields', description="修改知识库元数据字段", response_model=UnifiedResponseModel)
async def update_metadata_fields(*,
                                 login_user: UserPayload = Depends(get_login_user),
                                 req_data: UpdateKnowledgeMetadataFieldsReq,
                                 knowledge_service=Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks
                                 ):
    """
    修改知识库元数据字段
    Args:
        login_user:
        req_data:
        knowledge_service:
        background_tasks:

    Returns:
        UnifiedResponseModel
    """

    knowledge_model = await knowledge_service.update_metadata_fields(login_user, req_data, background_tasks)

    return resp_200(data=knowledge_model)


# 删除知识库元数据字段
@router.delete('/delete_metadata_fields', description="删除知识库元数据字段", response_model=UnifiedResponseModel)
async def delete_metadata_fields(*,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description="知识库ID"),
                                 field_names: List[str] = Body(..., embed=True, description="要删除的字段名称列表"),
                                 knowledge_service=Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks):
    """
    删除知识库元数据字段
    Args:
        login_user:
        knowledge_id:
        field_names:
        knowledge_service:
        background_tasks:

    Returns:
        UnifiedResponseModel
    """

    knowledge_model = await knowledge_service.delete_metadata_fields(login_user, knowledge_id, field_names,
                                                                     background_tasks)

    return resp_200(data=knowledge_model)


# 修改知识库文件用户自定义元数据
@router.put('/file/user_metadata', description="修改知识库文件用户自定义元数据", response_model=UnifiedResponseModel)
async def modify_file_user_metadata(*,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: ModifyKnowledgeFileMetaDataReq,
                                    knowledge_file_service=Depends(get_knowledge_file_service)):
    """
    修改知识库文件用户自定义元数据
    Args:
        login_user:
        req_data:
        knowledge_file_service:

    Returns:
        UnifiedResponseModel
    """

    knowledge_file_model = await knowledge_file_service.modify_file_user_metadata(login_user, req_data)

    return resp_200(data=knowledge_file_model)
