import json
import os
from datetime import datetime
from typing import Any, List, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from loguru import logger
from sqlmodel import col, select
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge_imp import text_knowledge
from bisheng.api.v1.schemas import ChunkInput, ExcelRule, KnowledgeFileOne, KnowledgeFileProcess, resp_200, resp_500
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError, UnAuthorizedError
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import async_file_download, save_download_file
from bisheng.core.database import get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.developer_token.api.dependencies import get_developer_token_user
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum, KnowledgeUpdate
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
    QAKnoweldgeDao,
    QAKnowledgeUpsert,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.open_endpoints.api.dependencies import get_knowledge_space_chat_service_for_openapi
from bisheng.open_endpoints.domain.schemas.filelib import (
    APIAddQAParam,
    APIAppendQAParam,
    FileDetailFile,
    FileDetailResp,
    QueryQAParam,
    RetrieveChunk,
    RetrieveReq,
    RetrieveResp,
)
from bisheng.open_endpoints.domain.utils import get_default_operator, get_default_operator_async
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.utils.util import sync_func_to_async

# build router
router = APIRouter(prefix='/filelib', tags=['OpenAPI', 'Knowledge'])
PORTAL_KNOWLEDGE_SPACES_PATH = '/knowledge-spaces'
OPENAPI_FILE_CATEGORY_ID = '入库分类测试'
OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE = '分类编码测试'
OPENAPI_FILE_DOC_TYPE_CODE = '分类赋码测试'
OPENAPI_TEXT_OBJECT_SUFFIXES = ('.md', '.markdown', '.txt')
OPENAPI_FILE_CONTENT_PAGE_SIZE = 1000


def _get_file_item_id(file_item: Any) -> int | None:
    raw_file_id = file_item.get('id') if isinstance(file_item, dict) else getattr(file_item, 'id', None)
    if raw_file_id is None:
        return None
    try:
        return int(raw_file_id)
    except (TypeError, ValueError):
        return None


def _parse_document_type_code(file_encoding: str | None) -> str:
    if not isinstance(file_encoding, str):
        return ''
    parts = [part.strip().upper() for part in file_encoding.split('-') if part.strip()]
    if len(parts) >= 3:
        return parts[1]
    if len(parts) >= 2:
        return parts[0]
    return ''


def _serialize_openapi_file_item(file_item: Any, *, is_primary: bool) -> dict:
    if hasattr(file_item, 'model_dump'):
        item = file_item.model_dump()
    elif isinstance(file_item, dict):
        item = dict(file_item)
    else:
        item = dict(vars(file_item))

    file_encoding = item.get('file_encoding') or ''
    item.update({
        'file_encoding': file_encoding,
        'is_primary': is_primary,
        'document_type': _parse_document_type_code(file_encoding),
        'categoryID': OPENAPI_FILE_CATEGORY_ID,
        'categoryGroupClassCode': OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE,
        'docTypeCode': OPENAPI_FILE_DOC_TYPE_CODE,
    })
    return item


def _format_openapi_datetime(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    return str(value)


def _serialize_openapi_file_detail(file_item: KnowledgeFile, *, is_primary: bool) -> FileDetailFile:
    file_encoding = file_item.file_encoding or ''
    return FileDetailFile(
        id=int(file_item.id),
        knowledge_id=int(file_item.knowledge_id),
        file_encoding=file_encoding,
        file_name=file_item.file_name,
        file_size=file_item.file_size,
        status=file_item.status,
        update_time=_format_openapi_datetime(file_item.update_time),
        is_primary=is_primary,
        document_type=_parse_document_type_code(file_encoding),
        categoryID=OPENAPI_FILE_CATEGORY_ID,
        categoryGroupClassCode=OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE,
        docTypeCode=OPENAPI_FILE_DOC_TYPE_CODE,
    )


def _unique_text_object_candidates(
        file_item: KnowledgeFile,
        content_format: Literal['text', 'markdown'],
) -> list[str]:
    if content_format == 'markdown':
        generated_candidates = [
            f'preview/{file_item.id}.md',
            f'markdown/{file_item.id}.md',
            f'preview/{file_item.id}.txt',
            f'text/{file_item.id}.txt',
        ]
    else:
        generated_candidates = [
            f'preview/{file_item.id}.txt',
            f'text/{file_item.id}.txt',
            f'preview/{file_item.id}.md',
            f'markdown/{file_item.id}.md',
        ]
    candidates = [
        getattr(file_item, 'preview_file_object_name', None),
        KnowledgeService.resolve_preview_object_name(
            file_item.id,
            file_item.file_name,
            getattr(file_item, 'preview_file_object_name', None),
        ),
        *generated_candidates,
    ]
    seen = set()
    result = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if str(candidate).lower().endswith(OPENAPI_TEXT_OBJECT_SUFFIXES):
            result.append(candidate)
    return result


async def _load_file_content_from_text_object(
        file_item: KnowledgeFile,
        content_format: Literal['text', 'markdown'],
) -> str | None:
    candidates = _unique_text_object_candidates(file_item, content_format)
    if not candidates:
        return None

    minio_client = await get_minio_storage()
    for object_name in candidates:
        try:
            if not await minio_client.object_exists(minio_client.bucket, object_name):
                continue
            content = await minio_client.get_object(minio_client.bucket, object_name)
            if content is None:
                continue
            return content.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning('openapi file detail text object is not utf-8 object_name={}', object_name)
        except Exception as exc:
            logger.warning('openapi file detail read text object failed object_name={} error={}', object_name, exc)
    return None


async def _load_file_content_from_es(db_knowledge: Any, file_id: int) -> tuple[str, int]:
    es_client = await KnowledgeRag.init_knowledge_es_vectorstore(knowledge=db_knowledge)
    chunks = []
    search_after = None
    while True:
        search_data = {
            'size': OPENAPI_FILE_CONTENT_PAGE_SIZE,
            'sort': [
                {
                    'metadata.chunk_index': {
                        'order': 'asc',
                        'missing': 0,
                        'unmapped_type': 'long',
                    },
                },
            ],
            'query': {
                'bool': {
                    'filter': [
                        {'term': {'metadata.document_id': file_id}},
                    ],
                },
            },
        }
        if search_after:
            search_data['search_after'] = search_after
        try:
            es_res = await es_client.client.search(index=db_knowledge.index_name, body=search_data)
        except Exception as exc:
            logger.warning('openapi file detail read es chunks failed file_id={} error={}', file_id, exc)
            raise
        hits = es_res.get('hits', {}).get('hits', [])
        if not hits:
            break
        for hit in hits:
            source = hit.get('_source', {})
            chunks.append(KnowledgeService.split_chunk_metadata(source.get('text') or ''))
        if len(hits) < OPENAPI_FILE_CONTENT_PAGE_SIZE:
            break
        search_after = hits[-1].get('sort')
        if not search_after:
            break
    return '\n'.join(chunks), len(chunks)


async def _load_file_primary_flags(file_ids: list[int | None]) -> dict[int, bool]:
    unique_file_ids = list(dict.fromkeys(file_id for file_id in file_ids if file_id is not None))
    if not unique_file_ids:
        return {}

    statement = select(
        KnowledgeDocumentVersion.knowledge_file_id,
        KnowledgeDocumentVersion.is_primary,
    ).where(col(KnowledgeDocumentVersion.knowledge_file_id).in_(unique_file_ids))
    async with get_async_db_session() as session:
        result = await session.execute(statement)
        return {
            int(knowledge_file_id): bool(is_primary)
            for knowledge_file_id, is_primary in result.all()
            if knowledge_file_id is not None
        }


def _build_portal_knowledge_spaces_path(base_path: str) -> str:
    base_path = (base_path or '').strip().rstrip('/')
    if not base_path or base_path == '/':
        return PORTAL_KNOWLEDGE_SPACES_PATH
    if base_path.endswith(PORTAL_KNOWLEDGE_SPACES_PATH):
        return base_path
    return f'{base_path}{PORTAL_KNOWLEDGE_SPACES_PATH}'


def _build_portal_source_urls(
        portal_base_url: Optional[str],
        knowledge_id: int,
        document_id: int,
) -> tuple[str, str]:
    query_params = {
        'spaceId': str(knowledge_id),
        'fileId': str(document_id),
    }
    base_url = (portal_base_url or '').strip()
    if not base_url:
        return f'{PORTAL_KNOWLEDGE_SPACES_PATH}?{urlencode(query_params)}', ''

    parsed_base_url = urlsplit(base_url)
    source_path = _build_portal_knowledge_spaces_path(parsed_base_url.path)
    merged_query_params = dict(parse_qsl(parsed_base_url.query, keep_blank_values=True))
    merged_query_params.update(query_params)
    source_query = urlencode(merged_query_params)
    source_url = urlunsplit(('', '', source_path, source_query, parsed_base_url.fragment))
    source_full_url = urlunsplit((
        parsed_base_url.scheme,
        parsed_base_url.netloc,
        source_path,
        source_query,
        parsed_base_url.fragment,
    ))
    return source_url, source_full_url


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
                        cursor: Optional[str] = None,
                        login_user: UserPayload = Depends(get_developer_token_user)):
    """ Read all knowledge base information. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    result = await KnowledgeService.get_knowledge(
        request,
        login_user,
        knowledge_type,
        name=name,
        cursor=cursor,
        page_size=page_size,
    )
    return resp_200(data=result)


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
        split_mode: Optional[Literal['auto', 'custom', 'hierarchical']] = Form(default='auto'),
        separator: Optional[List[str]] = Form(default=None,
                                              description='Split text rule, If not passed on, it is the default'),
        separator_rule: Optional[List[str]] = Form(
            default=None, description='Segmentation before or after the segmentation rule;before/after'),
        chunk_size: Optional[int] = Form(default=None, description='Split text length, default if not passed'),
        chunk_overlap: Optional[int] = Form(default=None,
                                            description='Split text overlap length, default if not passed'),
        hierarchy_level: Optional[int] = Form(default=3),
        append_title: Optional[bool] = Form(default=False),
        max_chunk_size: Optional[int] = Form(default=1000),
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
        file_path = await sync_func_to_async(save_download_file)(file.file, 'bisheng', file_name)
    else:
        file_path, file_name = await async_file_download(file_url)

    loging_user = await get_default_operator_async()
    req_data = KnowledgeFileProcess(knowledge_id=knowledge_id,
                                    split_mode=split_mode,
                                    separator=separator,
                                    separator_rule=separator_rule,
                                    chunk_size=chunk_size,
                                    chunk_overlap=chunk_overlap,
                                    hierarchy_level=hierarchy_level,
                                    append_title=append_title,
                                    max_chunk_size=max_chunk_size,
                                    retain_images=retain_images,
                                    force_ocr=force_ocr,
                                    enable_formula=enable_formula,
                                    filter_page_header_footer=filter_page_header_footer,
                                    callback_url=callback_url,
                                    file_list=[KnowledgeFileOne(file_path=file_path, excel_rule=excel_rule)])

    upload_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(loging_user)
    res = await KnowledgeService.aprocess_knowledge_file(request=request,
                                                         login_user=loging_user,
                                                         background_tasks=background_tasks,
                                                         req_data=req_data,
                                                         upload_limit_bytes=upload_limit_bytes)
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
async def get_filelist(request: Request,
                       knowledge_id: int,
                       login_user: UserPayload = Depends(get_developer_token_user),
                       keyword: str = None,
                       status: List[int] = Query(default=None),
                       page_size: int = 10,
                       page_num: int = 1):
    """ Get knowledge base file information. """
    data, total, flag = await KnowledgeService.aget_knowledge_files(
        request, login_user, knowledge_id,
        keyword, status, page_num, page_size,
        file_type=FileType.FILE.value,
    )
    file_ids = [_get_file_item_id(item) for item in data]
    primary_flags = await _load_file_primary_flags(file_ids)
    data = [
        _serialize_openapi_file_item(
            item,
            is_primary=primary_flags.get(file_id, True),
        )
        for item, file_id in zip(data, file_ids, strict=True)
    ]
    return resp_200(data={'data': data, 'total': total, 'writeable': flag})


@router.get('/file/detail', status_code=200)
async def get_file_detail(
        request: Request,
        file_encoding: str = Query(..., description='File encoding'),
        knowledge_id: Optional[int] = Query(default=None, description='Knowledge resource id'),
        content_format: Literal['text', 'markdown'] = Query(default='text', description='Content format'),
        login_user: UserPayload = Depends(get_developer_token_user),
):
    """Query one file by file encoding and return metadata plus full parsed content."""
    cleaned_file_encoding = file_encoding.strip()
    if not cleaned_file_encoding:
        raise HTTPException(status_code=400, detail='file_encoding must not be empty')

    files = await KnowledgeFileDao.aget_files_by_file_encoding(
        cleaned_file_encoding,
        knowledge_id=knowledge_id,
    )
    if not files:
        raise HTTPException(status_code=404, detail='file not found')
    if len(files) > 1:
        raise HTTPException(status_code=409, detail='duplicate file_encoding found')

    file_record = files[0]
    db_knowledge = await KnowledgeDao.aquery_by_id(file_record.knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=404, detail='knowledge not found')

    try:
        await KnowledgeService.permission_service.ensure_knowledge_read_async(
            login_user=login_user,
            owner_user_id=db_knowledge.user_id,
            knowledge_id=db_knowledge.id,
        )
    except UnAuthorizedError:
        raise UnAuthorizedError.http_exception()

    if file_record.status != KnowledgeFileStatus.SUCCESS.value:
        return resp_200(data=FileDetailResp())

    primary_flags = await _load_file_primary_flags([file_record.id])
    content = await _load_file_content_from_text_object(file_record, content_format)
    if content is None:
        content, chunk_count = await _load_file_content_from_es(db_knowledge, int(file_record.id))
    else:
        chunk_count = 1 if content else 0

    data = FileDetailResp(
        file=_serialize_openapi_file_detail(
            file_record,
            is_primary=primary_flags.get(int(file_record.id), True),
        ),
        content=content,
        chunk_count=chunk_count,
    )
    return resp_200(data=data)


@router.post('/chunks')
async def post_chunks(request: Request,
                      knowledge_id: int = Form(...),
                      metadata: str = Form(...),
                      split_mode: Optional[Literal['auto', 'custom', 'hierarchical']] = Form(default='auto'),
                      separator: Optional[List[str]] = Form(default=None),
                      separator_rule: Optional[List[str]] = Form(default=None),
                      chunk_size: Optional[int] = Form(default=None),
                      chunk_overlap: Optional[int] = Form(default=None),
                      hierarchy_level: Optional[int] = Form(default=3),
                      append_title: Optional[bool] = Form(default=False),
                      max_chunk_size: Optional[int] = Form(default=1000),
                      file: UploadFile = File(...)):
    """ Upload files to the knowledge base and sync the interface """
    file_name = file.filename
    if not file_name:
        return resp_500(message='file name must be not empty')
    file_path = await sync_func_to_async(save_download_file)(file.file, 'bisheng', file_name)

    login_user = await get_default_operator_async()

    req_data = KnowledgeFileProcess(knowledge_id=knowledge_id,
                                    split_mode=split_mode,
                                    separator=separator,
                                    separator_rule=separator_rule,
                                    chunk_size=chunk_size,
                                    chunk_overlap=chunk_overlap,
                                    hierarchy_level=hierarchy_level,
                                    append_title=append_title,
                                    max_chunk_size=max_chunk_size,
                                    file_list=[KnowledgeFileOne(file_path=file_path)])

    upload_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
    res = await run_in_threadpool(
        KnowledgeService.sync_process_knowledge_file,
        request, login_user, req_data, upload_limit_bytes=upload_limit_bytes,
    )
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

    upload_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
    knowledge, failed_files, process_files, _ = await KnowledgeService.asave_knowledge_file(
        login_user, req_data, upload_limit_bytes=upload_limit_bytes,
    )
    if failed_files:
        return resp_200(data=failed_files[0])

    res = await run_in_threadpool(text_knowledge, knowledge, process_files[0], document.documents)

    return resp_200(data=res)


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


@router.post('/retrieve')
async def retrieve_chunks(
        req: RetrieveReq,
        chat_svc: KnowledgeSpaceChatService = Depends(get_knowledge_space_chat_service_for_openapi),
):
    """Retrieve top-k chunks across one or more knowledge bases (no LLM generation).

    Designed for external retrieval-tool integrations (e.g. agents that bring
    their own LLM). Authentication runs as the configured default operator.
    """
    kb_filters = None
    if req.filters and req.filters.knowledge_base_filters:
        kb_filters = {
            f.knowledge_base_id: {"tags": f.tags, "tag_match_mode": f.tag_match_mode}
            for f in req.filters.knowledge_base_filters
        }

    try:
        results = await chat_svc.aretrieve_chunks(
            query=req.query,
            knowledge_base_ids=req.knowledge_base_ids,
            kb_filters=kb_filters,
            top_k=req.top_k,
            max_content=req.max_content,
        )
    except BaseErrorCode as e:
        return e.return_resp_instance()

    shougang_conf = await settings.aget_shougang_conf()
    portal_base_url = shougang_conf.portal_base_url
    chunks = []
    for kb_id, doc in results:
        document_id = int(doc.metadata.get("document_id", 0))
        document_name = str(doc.metadata.get("document_name", ""))
        source_url, source_full_url = _build_portal_source_urls(
            portal_base_url=portal_base_url,
            knowledge_id=kb_id,
            document_id=document_id,
        )
        chunks.append(RetrieveChunk(
            content=doc.page_content,
            knowledge_id=kb_id,
            document_id=document_id,
            document_name=document_name,
            chunk_index=int(doc.metadata.get("chunk_index", 0)),
            source_url=source_url,
            source_full_url=source_full_url,
        ))
    return resp_200(data=RetrieveResp(chunks=chunks, total=len(chunks)))


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
