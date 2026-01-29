import asyncio
import json
import os
from typing import Dict, List, Optional

from fastapi import (APIRouter, BackgroundTasks, Body, File, Form, HTTPException, Query, Request,
                     UploadFile)
from loguru import logger
from starlette.responses import FileResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import (decide_vectorstores, delete_es, delete_vector,
                                                text_knowledge)
from bisheng.api.v1.schemas import (ChunkInput, KnowledgeFileOne, KnowledgeFileProcess,
                                    resp_200, resp_500, ExcelRule)
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import file_download, save_download_file, async_file_download
from bisheng.core.logger import trace_id_var
from bisheng.database.models.message import ChatMessageDao
from bisheng.interface.embeddings.custom import FakeEmbedding
from bisheng.knowledge.domain.models.knowledge import (KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum,
                                                       KnowledgeUpdate)
from bisheng.knowledge.domain.models.knowledge_file import (QAKnoweldgeDao, QAKnowledgeUpsert)
from bisheng.open_endpoints.domain.schemas.filelib import APIAddQAParam, APIAppendQAParam, QueryQAParam
from bisheng.open_endpoints.domain.utils import get_default_operator, get_default_operator_async
from bisheng.utils.util import sync_func_to_async

# build router
router = APIRouter(prefix='/filelib', tags=['OpenAPI', 'Knowledge'])


@router.post('/', status_code=201)
def create(request: Request, knowledge: KnowledgeCreate):
    """Create Knowledge Base."""
    login_user = get_default_operator()
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.put('/', status_code=201)
def update_knowledge(*, request: Request, knowledge: KnowledgeUpdate):
    """ Update Knowledge Base."""
    login_user = get_default_operator()
    db_knowledge = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.get('/', status_code=200)
async def get_knowledge(*,
                        request: Request,
                        knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value,
                                                    alias='type'),
                        name: str = None,
                        page_size: Optional[int] = 10,
                        page_num: Optional[int] = 1):
    """ Read all knowledge base information. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    login_user = get_default_operator()
    res, total = await KnowledgeService.get_knowledge(request, login_user, knowledge_type, name,
                                                      page_num, page_size)
    return resp_200(data={'data': res, 'total': total})


@router.delete('/{knowledge_id}', status_code=200)
def delete_knowledge_api(*, request: Request, knowledge_id: int):
    """ Delete Knowledge Base Information. """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='knowledge deleted successfully')


# Empty all Knowledge Base file contents
@router.delete('/clear/{knowledge_id}', status_code=200)
def clear_knowledge_files(*, request: Request, knowledge_id: int):
    """ Empty Knowledge Base Contents. """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge(request, login_user, knowledge_id, only_clear=True)
    return resp_200(message='knowledge clear successfully')


@router.post('/file/{knowledge_id}')
async def upload_file(
        request: Request,
        knowledge_id: int,
        separator: Optional[List[str]] = Form(default=None,
                                              description='Split text rule, If not passed on, it is the default'),
        separator_rule: Optional[List[str]] = Form(
            default=None, description='Segmentation before or after the segmentation rule;before/after'),
        chunk_size: Optional[int] = Form(default=None, description='Split text length, default if not passed'),
        chunk_overlap: Optional[int] = Form(default=None,
                                            description='Split text overlap length, default if not passed'),
        callback_url: Optional[str] = Form(default=None, description='Return URL'),
        file_url: Optional[str] = Form(default=None, description='File URL'),
        file: Optional[UploadFile] = File(default=None, description='Upload file'),
        background_tasks: BackgroundTasks = None,
        retain_images: Optional[int] = Form(default=1, description='Keep document image'),
        force_ocr: Optional[int] = Form(default=0, description='EnableOCR'),
        enable_formula: Optional[int] = Form(default=1, description='latexFormula Recognition'),
        filter_page_header_footer: Optional[int] = Form(default=0, description='Filter Header Footer'),
        excel_rule: Optional[ExcelRule] = Form(default={}, description="excel rule"),
):
    if file:
        file_name = file.filename
        if not file_name:
            return resp_500(message='file name must be not empty')
        # Cache Local
        file_path = await sync_func_to_async(save_download_file)(save_download_file, file.file, 'bisheng', file_name)
    else:
        file_path, file_name = await async_file_download(file_url)

    loging_user = await get_default_operator_async()
    req_data = KnowledgeFileProcess(knowledge_id=knowledge_id,
                                    separator=separator,
                                    separator_rule=separator_rule,
                                    chunk_size=chunk_size,
                                    chunk_overlap=chunk_overlap,
                                    retain_images=retain_images,
                                    force_ocr=force_ocr,
                                    enable_formula=enable_formula,
                                    filter_page_header_footer=filter_page_header_footer,
                                    callback_url=callback_url,
                                    file_list=[KnowledgeFileOne(file_path=file_path, excel_rule=excel_rule)])

    res = await sync_func_to_async(KnowledgeService.process_knowledge_file)(request=request,
                                                                            login_user=loging_user,
                                                                            background_tasks=background_tasks,
                                                                            req_data=req_data)
    return resp_200(data=res[0])


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(request: Request, file_id: int):
    """ Delete files in the Knowledge Base """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200()


@router.post('/delete_file', status_code=200)
def delete_file_batch_api(request: Request, file_ids: List[int]):
    """ Bulk delete knowledge file information """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge_file(request, login_user, file_ids)
    return resp_200()


@router.get('/file/list', status_code=200)
def get_filelist(request: Request,
                 knowledge_id: int,
                 keyword: str = None,
                 status: List[int] = Query(default=None),
                 page_size: int = 10,
                 page_num: int = 1):
    """ Get knowledge base file information. """
    login_user = get_default_operator()
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id,
                                                             keyword, status, page_num, page_size)
    return resp_200(data={'data': data, 'total': total, 'writeable': flag})


@router.post('/chunks')
async def post_chunks(request: Request,
                      knowledge_id: int = Form(...),
                      metadata: str = Form(...),
                      separator: Optional[List[str]] = Form(default=None),
                      separator_rule: Optional[List[str]] = Form(default=None),
                      chunk_size: Optional[int] = Form(default=None),
                      chunk_overlap: Optional[int] = Form(default=None),
                      file: UploadFile = File(...)):
    """ Upload files to the knowledge base and sync the interface """
    file_name = file.filename
    if not file_name:
        return resp_500(message='file name must be not empty')
    file_path = await sync_func_to_async(save_download_file)(file.file, 'bisheng', file_name)

    login_user = await get_default_operator_async()

    req_data = KnowledgeFileProcess(knowledge_id=knowledge_id,
                                    separator=separator,
                                    separator_rule=separator_rule,
                                    chunk_size=chunk_size,
                                    chunk_overlap=chunk_overlap,
                                    file_list=[KnowledgeFileOne(file_path=file_path)],
                                    extra=metadata)

    res = await sync_func_to_async(KnowledgeService.sync_process_knowledge_file)(request, login_user, req_data)
    return resp_200(data=res[0])


@router.post('/chunks_string')
async def post_string_chunks(request: Request, document: ChunkInput):
    """ Get knowledge base file information. """

    # String saved to file
    content = '\n\n'.join([doc.page_content for doc in document.documents])
    content_bytes = bytes(content, encoding='utf-8')
    file_name = document.documents[0].metadata.get('source')
    file_path = await sync_func_to_async(save_download_file)(content_bytes, 'bisheng', file_name)

    login_user = await get_default_operator_async()

    req_data = KnowledgeFileProcess(knowledge_id=document.knowledge_id,
                                    separator=['\n\n'],
                                    separator_rule=['after'],
                                    file_list=[KnowledgeFileOne(file_path=file_path)],
                                    extra=json.dumps(document.documents[0].metadata,
                                                     ensure_ascii=False))

    knowledge, failed_files, process_files, _ = await sync_func_to_async(KnowledgeService.save_knowledge_file)(
        login_user, req_data)
    if failed_files:
        return resp_200(data=failed_files[0])

    res = await sync_func_to_async(text_knowledge)(knowledge, process_files[0], document.documents)

    return resp_200(data=res)


@router.post('/chunk_clear', status_code=200)
async def clear_tmp_chunks_data(body: Dict):
    # Delete via Interfacemilvus、es DATA
    flow_id = body.get('flow_id')
    chat_id = body.get('chat_id')

    if flow_id and not chat_id:
        # Clean temporary files under the skill
        flow_id = flow_id.replace('-', '')
        collection_name = f'tmp_{flow_id}_1'
        delete_es(collection_name)
        delete_vector(collection_name, None)
    if chat_id:
        #  Query auto-generated
        message = ChatMessageDao.get_latest_message_by_chatid(chat_id)
        if message:
            collection_name = f'tmp_{message.flow_id}_{chat_id}'
            delete_es(collection_name)
            delete_vector(collection_name, None)

    return resp_200()


@router.get('/dump_vector', status_code=200)
def dump_vector_knowledge(collection_name: str, expr: str = None, store: str = 'Milvus'):
    # dump vector db
    embedding_tmp = FakeEmbedding()
    vector_store = decide_vectorstores(collection_name, store, embedding_tmp)

    if vector_store and vector_store.col:
        fields = [
            s.name for s in vector_store.col.schema.fields
            if s.name not in ['pk', 'bbox', 'vector']
        ]
        res_list = vector_store.col.query('file_id>1', output_fields=fields)
        return resp_200(res_list)
    else:
        return resp_500('Parameter salah')


@router.get('/download_statistic')
def download_statistic_file(file_path: str):
    suffix = file_path.split('.')[-1]
    if suffix != 'log':
        raise ServerError.http_exception(msg='only .log file supported download')
    dir_path = file_path.replace('.log', '')
    if dir_path.find(".") != -1 or not dir_path.startswith("/app/data"):
        raise ServerError.http_exception(msg='invalid file path, file path must not contain .')

    file_name = os.path.basename(file_path)
    return FileResponse(file_path, filename=file_name)


@router.post('/add_qa')
def add_qa(*,
           knowledge_id: int = Body(embed=True),
           data: List[APIAddQAParam] = Body(embed=True),
           user_id: Optional[int] = Body(default=None, embed=True)):
    user_id = user_id if user_id else settings.get_from_db('default_operator').get('user')
    knowledge = KnowledgeDao.query_by_id(knowledge_id)
    logger.info('add_qa_data knowledge_id={} size={}', knowledge_id, len(data))
    res = []
    for item in data:
        qa_insert = QAKnowledgeUpsert(knowledge_id=knowledge_id,
                                      questions=[item.question],
                                      answers=item.answer,
                                      user_id=user_id,
                                      extra_meta=json.dumps(item.extra),
                                      source=3)

        res.append(knowledge_imp.add_qa(knowledge, qa_insert))

    return resp_200(res)


@router.post('/add_relative_qa')
def append_qa(*,
              knowledge_id: int = Body(embed=True),
              data: APIAppendQAParam = Body(embed=True),
              user_id: Optional[int] = Body(default=None, embed=True)):
    user_id = user_id if user_id else settings.get_from_db('default_operator').get('user')
    knowledge = KnowledgeDao.query_by_id(knowledge_id)
    qa_db = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(data.id)
    if not qa_db:
        return HTTPException(404, detail='qa Right, nothing found.')

    t = qa_db.dict()
    t['answers'] = json.loads(t['answers'])
    qa_insert = QAKnowledgeUpsert.validate(t)
    qa_insert.questions.extend(data.relative_questions)

    return resp_200(knowledge_imp.add_qa(knowledge, qa_insert))


@router.delete('/qa/{qa_id}', status_code=200)
def delete_qa_data(*, qa_id: int, question: Optional[str] = None):
    """ Deleteqa Question to Information """
    qa = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(qa_id)
    login_user = get_default_operator()
    if not qa:
        raise HTTPException(status_code=404, detail='qa Does not exist')

    if question:
        qa.questions = [q for q in qa.questions if q != question]
        QAKnoweldgeDao.update(qa)
    else:
        QAKnoweldgeDao.delete_batch([qa_id])
        telemetry_service.log_event_sync(user_id=login_user.user_id,
                                         event_type=BaseTelemetryTypeEnum.DELETE_KNOWLEDGE_FILE,
                                         trace_id=trace_id_var.get())
    try:
        knowledge = KnowledgeDao.query_by_id(qa.knowledge_id)
        knowledge_imp.delete_vector_data(knowledge, file_ids=[qa_id])
        if question:
            knowledge_imp.QA_save_knowledge(knowledge, qa)
        return resp_200()
    except Exception as e:
        return resp_500(message=f'error e={str(e)}')


@router.post('/update_qa', status_code=200)
def update_qa(
        *,
        id: int = Body(embed=True),
        question: Optional[str] = Body(default=None, embed=True),
        original_question: Optional[str] = Body(default=None, embed=True),
        answer: Optional[List[str]] = Body(default=None, embed=True),
):
    """ Deleteqa Question to Information """
    qa = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)

    if not qa:
        raise HTTPException(status_code=404, detail='qa Does not exist')

    if original_question:
        qa.questions = [q if q != question else question for q in qa.questions]
    else:
        qa.questions = [question]
    if answer:
        qa.answers = json.dumps(answer, ensure_ascii=False)
    QAKnoweldgeDao.update(qa)

    try:
        knowledge = KnowledgeDao.query_by_id(qa.knowledge_id)
        if question:
            knowledge_imp.delete_vector_data(knowledge, file_ids=[id])
            knowledge_imp.QA_save_knowledge(knowledge, qa)
        return resp_200()
    except Exception as e:
        return resp_500(message=f'error e={str(e)}')


@router.get('/detail_qa', status_code=200)
def detail_qa(*, id: int):
    """ Get questions on information """
    qa = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    return resp_200(qa)


@router.post('/query_qa', status_code=200)
def query_qa(QueryQAParam: QueryQAParam):
    """ Deleteqa Question to Information """
    sources = [1, 2]  # 3 Yes apiInverted
    qa_list = QAKnoweldgeDao.query_by_condition_v1(source=sources,
                                                   create_start=QueryQAParam.timeRange[0],
                                                   create_end=QueryQAParam.timeRange[1])
    if qa_list:
        for q in qa_list:
            q.answers = json.loads(q.answers)

    return resp_200(qa_list)
