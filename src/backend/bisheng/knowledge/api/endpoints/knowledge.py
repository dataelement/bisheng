import asyncio
import gc
import json
import urllib.parse
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Any, Literal

import pandas as pd
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from fastapi.encoders import jsonable_encoder
from loguru import logger

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import add_qa
from bisheng.api.v1.schemas import (KnowledgeFileProcess, UpdatePreviewFileChunk, UploadFileResponse,
                                    UpdateKnowledgeReq, KnowledgeFileReProcess)
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError, ServerError
from bisheng.common.errcode.knowledge import KnowledgeCPError, KnowledgeQAError, KnowledgeRebuildingError, \
    KnowledgePreviewError, KnowledgeNotQAError, KnowledgeNoEmbeddingError, KnowledgeNotExistError, KnowledgeCPEmptyError
from bisheng.common.errcode.server import NoLlmModelConfigError
from bisheng.common.schemas.api import resp_200, resp_500, UnifiedResponseModel
from bisheng.common.services import telemetry_service
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.core.logger import trace_id_var
from bisheng.database.models.role_access import AccessType
from bisheng.knowledge.api.dependencies import get_knowledge_service, get_knowledge_file_service
from bisheng.knowledge.domain.models.knowledge import (KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum,
                                                       KnowledgeUpdate)
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.models.knowledge_file import (KnowledgeFileDao, KnowledgeFileStatus,
                                                            QAKnoweldgeDao, QAKnowledgeUpsert, QAStatus)
from bisheng.knowledge.domain.schemas.knowledge_schema import AddKnowledgeMetadataFieldsReq, \
    UpdateKnowledgeMetadataFieldsReq, ModifyKnowledgeFileMetaDataReq
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid, calc_data_sha256
from bisheng.worker.knowledge.qa import insert_qa_celery

# build router
router = APIRouter(prefix='/knowledge', tags=['Knowledge'])


@router.post('/upload')
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename

        uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)

        file_path = await save_uploaded_file(file, 'bisheng', uuid_file_name)

        if not isinstance(file_path, str):
            file_path = str(file_path)

        return resp_200(UploadFileResponse(file_path=file_path))

    except Exception as e:
        logger.error(f'File upload failed: {e}')
        raise ServerError(msg=f'File upload failed: {e}')

    finally:
        await file.close()

@router.post('/upload/{knowledge_id}')
async def upload_knowledge_file(*,
                                request: Request,
                                login_user: UserPayload = Depends(UserPayload.get_login_user),
                                knowledge_id: int,
                                file: UploadFile = File(...)):
    """ Knowledge base upload file """

    try:
        file_name = file.filename

        # Save the uploaded file
        uuid_file_name = await KnowledgeService.save_upload_file_original_name(file_name)
        file_path = await save_uploaded_file(file, 'bisheng', uuid_file_name)

        if not isinstance(file_path, str):
            file_path = str(file_path)

        await file.seek(0)

        # Calculate file md5
        file_md5 = await asyncio.to_thread(calc_data_sha256, file.file)

        # Check for duplicate files
        repeat_file = await KnowledgeFileDao.get_repeat_file(
            knowledge_id=knowledge_id, file_name=file_name, md5_=file_md5
        )

        ret = UploadFileResponse(file_path=file_path)
        if repeat_file:
            ret.repeat = True
            ret.repeat_update_time = repeat_file.update_time

        return resp_200(ret)

    except Exception as e:
        raise ServerError(msg=f'File upload failed: {e}')

    finally:
        await file.close()


@router.post('/preview')
async def preview_file_chunk(*,
                             request: Request,
                             login_user: UserPayload = Depends(UserPayload.get_login_user),
                             background_tasks: BackgroundTasks,
                             req_data: KnowledgeFileProcess):
    """ Get a chunked preview of a file """

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
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        preview_file_id: str = Query(..., description='Preview the file returned by the interfaceID')):
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
                                    login_user: UserPayload = Depends(UserPayload.get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ Updating a chunked preview of a file """

    res = await KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(UserPayload.get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ Delete a chunked preview of a file """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
def process_knowledge_file(*,
                           request: Request,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           background_tasks: BackgroundTasks,
                           req_data: KnowledgeFileProcess):
    """ Uploading Files to the Knowledge Base """

    res = KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)
    return resp_200(res)


# Modify Segment Reprocessing
@router.post("/process/rebuild")
async def rebuild_knowledge_file(*,
                                 request: Request,
                                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                                 req_data: KnowledgeFileReProcess):
    """ Reprocessing Knowledge Base Files """

    res = await KnowledgeService.rebuild_knowledge_file(request, login_user, req_data)
    return resp_200(res)


@router.post('/create')
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(UserPayload.get_login_user),
                     knowledge: KnowledgeCreate):
    """ Create Knowledge Base. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.post('/copy')
async def copy_knowledge(*,
                         request: Request,
                         background_tasks: BackgroundTasks,
                         login_user: UserPayload = Depends(UserPayload.get_login_user),
                         knowledge_id: int = Body(..., embed=True),
                         knowledge_name: str = Body(default=None, embed=True)):
    """ Copy Knowledge Base. """
    knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)

    if not login_user.is_admin and knowledge.user_id != login_user.user_id:
        return UnAuthorizedError.return_resp()

    knowledge_count = await KnowledgeFileDao.async_count_file_by_filters(
        knowledge_id,
        status=[KnowledgeFileStatus.PROCESSING.value, KnowledgeFileStatus.WAITING.value],
    )
    if knowledge.state != KnowledgeState.PUBLISHED.value or knowledge_count > 0:
        return KnowledgeCPError.return_resp()
    knowledge = await KnowledgeService.copy_knowledge(request, background_tasks, login_user, knowledge, knowledge_name)
    return resp_200(knowledge)


@router.post("/qa/copy")
async def copy_qa_knowledge(*,
                            request: Request,
                            login_user: UserPayload = Depends(UserPayload.get_login_user),
                            knowledge_id: int = Body(..., embed=True),
                            knowledge_name: str = Body(default=None, embed=True)):
    """
    SalinQAThe knowledge base upon.
    :param request:
    :param login_user:
    :param knowledge_id:
    :param knowledge_name: new knowledge name
    :return:
    """

    qa_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not login_user.is_admin and qa_knowledge.user_id != login_user.user_id:
        return UnAuthorizedError.return_resp()

    if qa_knowledge.type != KnowledgeTypeEnum.QA.value:
        return KnowledgeNotQAError.return_resp()

    qa_knowledge_count = await QAKnoweldgeDao.async_count_by_id(qa_id=qa_knowledge.id)

    if qa_knowledge.state != KnowledgeState.PUBLISHED.value:
        return KnowledgeCPError.return_resp()
    if qa_knowledge_count == 0:
        return KnowledgeCPEmptyError.return_resp()

    knowledge = await KnowledgeService.copy_qa_knowledge(request, login_user, qa_knowledge, knowledge_name)

    return resp_200(knowledge)


@router.get('', status_code=200)
async def get_knowledge(*,
                        request: Request,
                        login_user: UserPayload = Depends(UserPayload.get_login_user),
                        name: str = None,
                        knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value,
                                                    alias='type'),
                        sort_by: Literal['create_time', 'update_time', 'name'] = Query(default='update_time'),
                        page_size: Optional[int] = 10,
                        page_num: Optional[int] = 1):
    """ Read all knowledge base information. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    res, total = await KnowledgeService.get_knowledge(request, login_user, knowledge_type, name,
                                                      sort_by,
                                                      page_num, page_size)
    return resp_200(data={'data': res, 'total': total})


@router.get('/info', status_code=200)
def get_knowledge_info(*,
                       request: Request,
                       login_user: UserPayload = Depends(UserPayload.get_login_user),
                       knowledge_id: List[int] = Query(...)):
    """ Based on Knowledge BaseIDRead Knowledge Base Information. """
    res = KnowledgeService.get_knowledge_info(request, login_user, knowledge_id)
    return resp_200(data=res)


@router.put('/', status_code=200)
async def update_knowledge(*,
                           request: Request,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           knowledge: KnowledgeUpdate):
    res = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(data=res)


@router.delete('/', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(UserPayload.get_login_user),
                     knowledge_id: int = Body(..., embed=True)):
    """ Delete Knowledge Base Information. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='Delete successful')


# Personal Knowledge Base Information Acquisition
@router.get('/personal_knowledge_info', status_code=200)
def get_personal_knowledge_info(
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get personal knowledge base information. """
    knowledge = KnowledgeDao.get_user_knowledge(login_user.user_id, None,
                                                KnowledgeTypeEnum.PRIVATE)

    return resp_200(data=knowledge)


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 request: Request,
                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                 file_name: str = None,
                 file_ids: List[int] = None,
                 knowledge_id: int = 0,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: List[int] = Query(default=None)):
    """ Get knowledge base file information. """
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
                      login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get knowledge base file information. """
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
          login_user: UserPayload = Depends(UserPayload.get_login_user),
          background_tasks: BackgroundTasks,
          req_data: dict):
    """Failed Retry"""
    KnowledgeService.retry_files(request, login_user, background_tasks, req_data)
    return resp_200()


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Delete Knowledge File Information """
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(message='Delete successful')


@router.get('/chunk', status_code=200)
async def get_knowledge_chunk(request: Request,
                              login_user: UserPayload = Depends(UserPayload.get_login_user),
                              knowledge_id: int = Query(..., description='The knowledge base uponID'),
                              file_ids: List[int] = Query(default=[], description='Doc.ID'),
                              keyword: str = Query(default='', description='Keywords'),
                              page: int = Query(default=1, description='Page'),
                              limit: int = Query(default=10,
                                                 description='Number of bars per page Number of bars per page')):
    """ Get Knowledge Base Block Content """
    # In order to resolvekeywordParameters are sometimes not carried outurldecoderight of privacybug
    if keyword.startswith('%'):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids,
                                                       keyword, page, limit)
    return resp_200(data={'data': res, 'total': total})


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='The knowledge base uponID'),
                                 file_id: int = Body(..., embed=True, description='Doc.ID'),
                                 chunk_index: int = Body(..., embed=True, description='Chunked index number'),
                                 text: str = Body(..., embed=True, description='Chunked content'),
                                 bbox: str = Body(default='', embed=True, description='Block box selection position')):
    """ Update Knowledge Base Chunk Content """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='The knowledge base uponID'),
                                 file_id: int = Body(..., embed=True, description='Doc.ID'),
                                 chunk_index: int = Body(..., embed=True, description='Chunked index number')):
    """ Delete Knowledge Base Chunk Content """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request,
                             login_user: UserPayload = Depends(UserPayload.get_login_user),
                             file_id: int = Query(description='File UniqueID')):
    original_url, preview_url = KnowledgeService.get_file_share_url(file_id)
    return resp_200(data={
        'original_url': original_url,
        'preview_url': preview_url
    })


@router.get('/file_bbox')
async def get_file_bbox(request: Request,
                        login_user: UserPayload = Depends(UserPayload.get_login_user),
                        file_id: int = Query(description='File UniqueID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)


@router.post('/qa/add', status_code=200)
async def qa_add(*, QACreate: QAKnowledgeUpsert,
                 login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Add knowledge base information. """
    QACreate.user_id = login_user.user_id
    db_knowledge = KnowledgeDao.query_by_id(QACreate.knowledge_id)
    if db_knowledge.type != KnowledgeTypeEnum.QA.value:
        raise NotFoundError()
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
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Modify Knowledge Base Information. """
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
        # Description state switch failed
        return resp_500(message=new_qa_db.remark)
    return resp_200()


@router.get('/qa/detail', status_code=200)
def qa_detail(*, id: int, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Add knowledge base information. """
    qa_knowledge = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    qa_knowledge.answers = json.loads(qa_knowledge.answers)[0]
    return resp_200(data=qa_knowledge)


@router.post('/qa/append', status_code=200)
def qa_append(
        *,
        ids: list[int] = Body(..., embed=True),
        question: str = Body(..., embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """ Add knowledge base information. """
    qa_list = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(qa_list[0].knowledge_id)
    # check knowledge access
    if not login_user.access_check(
            knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()

    for q in qa_list:
        if question in q.questions:
            raise KnowledgeQAError.http_exception()
    for qa in qa_list:
        qa.questions.append(question)
        knowledge_imp.add_qa(knowledge, qa)
    return resp_200()


@router.delete('/qa/delete', status_code=200)
def qa_delete(*,
              ids: list[int] = Body(embed=True),
              login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Delete Knowledge File Information """
    qa_list = QAKnoweldgeDao.select_list(ids)

    knowledge = KnowledgeDao.query_by_id(qa_list[0].knowledge_id)
    if not login_user.access_check(knowledge.user_id, str(knowledge.id),
                                   AccessType.KNOWLEDGE_WRITE):
        raise UnAuthorizedError()
    if knowledge.type != KnowledgeTypeEnum.QA.value:
        raise KnowledgeNotQAError()

    knowledge_imp.delete_vector_data(knowledge, ids)
    QAKnoweldgeDao.delete_batch(ids)
    telemetry_service.log_event_sync(user_id=login_user.user_id,
                                     event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_FILE,
                                     trace_id=trace_id_var.get())
    return resp_200()


@router.post('/qa/auto_question')
def qa_auto_question(
        *,
        number: int = Body(default=3, embed=True),
        ori_question: str = Body(default='', embed=True),
        answer: str = Body(default='', embed=True),
        login_user: UserPayload = Depends(UserPayload.get_login_user)
):
    """Automatically generate questions from large models"""
    questions = knowledge_imp.recommend_question(login_user.user_id, ori_question, number=number, answer=answer)
    return resp_200(data={'questions': questions})


@router.get('/qa/export/template', status_code=200)
async def get_export_url():
    data = [{"Question": "", "Answer": "", "Similar question 1": "", "Similar question 2": ""}]
    df = pd.DataFrame(data)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
    file_name = f"qa_export_template.xlsx"
    bio.seek(0)
    file = UploadFile(filename=file_name, file=bio)
    file_path = await save_uploaded_file(file, 'bisheng', file_name)
    await file.close()
    return resp_200({"url": file_path})


@router.get('/qa/export/{qa_knowledge_id}', status_code=200)
async def get_export_url(*,
                         qa_knowledge_id: int,
                         question: Optional[str] = None,
                         answer: Optional[str] = None,
                         keyword: Optional[str] = None,
                         status: Optional[int] = None,
                         max_lines: Optional[int] = 10000,
                         login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # Query the current knowledge base, whether there are write permissions
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    if keyword:
        question = keyword

    page_num = 1
    total_num = 0
    page_size = max_lines
    file_list = []
    file_pr = datetime.now().strftime('%Y%m%d%H%M%S')
    file_index = 1
    while True:
        qa_list, total_count = await knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                           page_num, question, answer,
                                                                           status)

        data = [jsonable_encoder(qa) for qa in qa_list]
        qa_dict_list = []
        all_title = ["Question", "Answer"]
        for qa in data:
            qa_dict_list.append({
                "Question": qa['questions'][0],
                "Answer": json.loads(qa['answers'])[0]
            })
            for index, question in enumerate(qa['questions']):
                if index == 0:
                    continue
                key = f"Similar question {index}"
                if key not in all_title:
                    all_title.append(key)
                qa_dict_list[-1][key] = question
        if len(qa_dict_list) != 0:
            df = pd.DataFrame(qa_dict_list)
        else:
            df = pd.DataFrame([{"Question": "", "Answer": "", "Similar question 1": "", "Similar question 2": ""}])
        df = df[all_title]
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        file_name = f"{file_pr}_{file_index}.xlsx"
        file_index = file_index + 1
        bio.seek(0)
        file_io = UploadFile(filename=file_name, file=bio)
        file_path = await save_uploaded_file(file_io, 'bisheng', file_name)
        await file_io.close()
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
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    df = pd.read_excel(file_url)
    columns = df.columns.to_list()
    if 'Question' not in columns or 'Answer' not in columns:
        raise HTTPException(status_code=500, detail='file must have ‘Question’ Or ‘Answer’ column')
    data = df.T.to_dict().values()
    insert_data = []
    for dd in data:
        d = QAKnowledgeUpsert(
            user_id=login_user.user_id,
            knowledge_id=qa_knowledge_id,
            answers=[convert_excel_value(dd['Question'])],
            questions=[convert_excel_value(dd['Answer'])],
            source=4,
            create_time=datetime.now(),
            update_time=datetime.now())
        for key, value in dd.items():
            if key.startswith('Similar question') and convert_excel_value(value):
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
                     login_user: UserPayload = Depends(UserPayload.get_login_user)):
    # Query the current knowledge base, whether there are write permissions
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    insert_result = []
    error_result = []
    have_question = []
    for file_url in file_list:
        df = pd.read_excel(file_url)
        columns = df.columns.to_list()
        if 'Question' not in columns or 'Answer' not in columns:
            insert_result.append(0)
            continue
        data = df.T.to_dict().values()
        insert_data = []
        have_data = []
        all_questions = set()
        for index, dd in enumerate(data):
            tmp_questions = set()
            dd_question = convert_excel_value(dd['Question'])
            dd_answer = convert_excel_value(dd['Answer'])
            QACreate = QAKnowledgeUpsert(
                user_id=login_user.user_id,
                knowledge_id=qa_knowledge_id,
                answers=[dd_answer],
                questions=[dd_question],
                source=4,
                status=QAStatus.PROCESSING.value)
            tmp_questions.add(QACreate.questions[0])
            for key, value in dd.items():
                if key.startswith('Similar question'):
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

        telemetry_service.log_event_sync(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_KNOWLEDGE_FILE,
            trace_id=trace_id_var.get()
        )

        # async task add qa into milvus and es
        for one in result:
            insert_qa_celery.delay(one.id)

        error_result.append(have_data)

    return resp_200({"errors": error_result})


@router.get('/status', status_code=200)
def get_knowledge_status(*, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """
    View Knowledge Base Status Interface
    Receive:
    1. According UsersidFirst determine if the user has a personal knowledge base and does not return directly200
    2. If you have a knowledge base, depending on the useridView the state of your knowledge base, if the state of your personal knowledge base isREBUILDING 3 or FAILED 4 Jam
       Return "Personal Knowledge BaseembeddingThe model has been replaced, rebuilding the knowledge base, please try again later" State Code 502
    """
    # Query a user's personal knowledge base
    user_private_knowledge = KnowledgeDao.get_user_knowledge(
        login_user.user_id,
        None,
        KnowledgeTypeEnum.PRIVATE
    )

    # If the user does not have a personal knowledge base, go directly back to200
    if not user_private_knowledge:
        return resp_200({"status": "success"})

    # Get the first personal knowledge base (usually users have only one personal knowledge base)
    private_knowledge = user_private_knowledge[0]

    # Check Knowledge Base Status

    if private_knowledge.state == KnowledgeState.REBUILDING.value:
        # Return502Status codes and corresponding prompts
        raise KnowledgeRebuildingError()
    if private_knowledge.state == KnowledgeState.FAILED.value:
        # Delay imports to avoid looping imports
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
        rebuild_knowledge_celery.delay(private_knowledge.id, int(private_knowledge.model), login_user.user_id)
        # Return502Status codes and corresponding prompts
        raise KnowledgeRebuildingError()

    # Knowledge base status is OK, go back200
    return resp_200({"status": "success"})


@router.post('/update_knowledge', status_code=200)
def update_knowledge_model(*,
                           login_user: UserPayload = Depends(UserPayload.get_login_user),
                           req_data: UpdateKnowledgeReq):
    """
    Update Knowledge Base Interface
    Update embedding Rebuild Knowledge Base on Model
    Receive:
    1. According to the incoming from the front-endmodel_id, model_type, let's first determine ifembeddingModels
    2. If not, go backresp501("Is notembeddingModels") If so, place theknowledgeAll in the tabletypeare2DatastatusChange to...3，modelChange to Incomingmodel_id
    3. everyknowledge_idBoth initiate asynchronous tasks to rebuild the knowledge base
    """
    # 1. Verify that isembeddingModels
    model_info = LLMDao.get_model_by_id(req_data.model_id)
    if not model_info:
        return NoLlmModelConfigError.return_resp()

    # If the front-end does not passmodel_type, using themodel_type
    model_type = req_data.model_type if req_data.model_type else model_info.model_type

    if model_type != LLMModelType.EMBEDDING.value:
        return KnowledgeNoEmbeddingError.return_resp()

    # Process the specified knowledge base
    knowledge = KnowledgeDao.query_by_id(req_data.knowledge_id)
    if not knowledge:
        return KnowledgeNotExistError.return_resp()

    if not login_user.access_check(
            knowledge.user_id, str(knowledge.id), AccessType.KNOWLEDGE_WRITE
    ):
        return UnAuthorizedError.return_resp()

    old_model_id = knowledge.model

    # Update Knowledge Base Status and Models
    knowledge.model = str(req_data.model_id)
    knowledge.name = req_data.knowledge_name
    knowledge.description = req_data.description

    if int(old_model_id) == int(req_data.model_id):
        # If the model does not change, there is no need to rebuild
        KnowledgeDao.update_one(knowledge)
        return resp_200()
    if knowledge.state == KnowledgeState.REBUILDING.value:
        return KnowledgeRebuildingError.return_resp()

    knowledge.state = KnowledgeState.REBUILDING.value
    KnowledgeDao.update_one(knowledge)

    # Start asynchronous task

    if knowledge.type == KnowledgeTypeEnum.NORMAL.value:

        # Delay imports to avoid looping imports
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
        rebuild_knowledge_celery.delay(knowledge.id, req_data.model_id, login_user.user_id)

    elif knowledge.type == KnowledgeTypeEnum.QA.value:

        # Delay imports to avoid looping imports
        from bisheng.worker.knowledge.qa import rebuild_qa_knowledge_celery
        rebuild_qa_knowledge_celery.delay(knowledge.id, req_data.model_id, login_user.user_id)

    logger.info(f"Started rebuild task for knowledge_id={knowledge.id} with model_id={req_data.model_id}")

    return resp_200()


@router.get("/file/info/{file_id}", description="Get knowledge base file information",
            response_model=UnifiedResponseModel)
async def get_knowledge_file_info(*,
                                  login_user: UserPayload = Depends(UserPayload.get_login_user),
                                  file_id: int,
                                  knowledge_file_service=Depends(get_knowledge_file_service)):
    """
    Get knowledge base file information
    Args:
        login_user:
        file_id:
        knowledge_file_service:

    Returns:

    """

    knowledge_file_info_res = await knowledge_file_service.get_knowledge_file_info(login_user, file_id)
    return resp_200(data=knowledge_file_info_res)


# Adding Metadata Fields to the Knowledge Base
@router.post('/add_metadata_fields', description="Adding Metadata Fields to the Knowledge Base",
             response_model=UnifiedResponseModel)
async def add_metadata_fields(*,
                              login_user: UserPayload = Depends(UserPayload.get_login_user),
                              req_data: AddKnowledgeMetadataFieldsReq,
                              knowledge_service=Depends(get_knowledge_service)):
    """
    Adding Metadata Fields to the Knowledge Base
    """

    knowledge_model = await knowledge_service.add_metadata_fields(login_user, req_data)

    return resp_200(data=knowledge_model)


# Modify Knowledge Base Metadata Fields
@router.put('/update_metadata_fields', description="Modify Knowledge Base Metadata Fields",
            response_model=UnifiedResponseModel)
async def update_metadata_fields(*,
                                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                                 req_data: UpdateKnowledgeMetadataFieldsReq,
                                 knowledge_service=Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks
                                 ):
    """
    Modify Knowledge Base Metadata Fields
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


# Delete Knowledge Base Metadata Field
@router.delete('/delete_metadata_fields', description="Delete Knowledge Base Metadata Field",
               response_model=UnifiedResponseModel)
async def delete_metadata_fields(*,
                                 login_user: UserPayload = Depends(UserPayload.get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description="The knowledge base uponID"),
                                 field_names: List[str] = Body(..., embed=True,
                                                               description="List of field names to delete"),
                                 knowledge_service=Depends(get_knowledge_service),
                                 background_tasks: BackgroundTasks):
    """
    Delete Knowledge Base Metadata Field
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


# Modify Knowledge Base File User Custom Metadata
@router.put('/file/user_metadata', description="Modify Knowledge Base File User Custom Metadata",
            response_model=UnifiedResponseModel)
async def modify_file_user_metadata(*,
                                    login_user: UserPayload = Depends(UserPayload.get_login_user),
                                    req_data: ModifyKnowledgeFileMetaDataReq,
                                    knowledge_file_service=Depends(get_knowledge_file_service)):
    """
    Modify Knowledge Base File User Custom Metadata
    Args:
        login_user:
        req_data:
        knowledge_file_service:

    Returns:
        UnifiedResponseModel
    """

    knowledge_file_model = await knowledge_file_service.modify_file_user_metadata(login_user, req_data)

    return resp_200(data=knowledge_file_model)
