import json
import os
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge_imp import text_knowledge
from bisheng.api.v1.schemas import ChunkInput, ExcelRule, KnowledgeFileOne, KnowledgeFileProcess, resp_200, resp_500
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import NotFoundError, ServerError
from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import async_file_download, save_download_file
from bisheng.core.logger import trace_id_var
from bisheng.knowledge.api.dependencies import (
    get_knowledge_document_repository,
    get_knowledge_document_version_repository,
)
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    KnowledgeCreate,
    KnowledgeDao,
    KnowledgeTypeEnum,
    KnowledgeUpdate,
)
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao, QAKnowledgeUpsert
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import KnowledgeDocumentRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.schemas.filelib import (
    APIAddQAParam,
    APIAppendQAParam,
    QueryQAParam,
    RetrieveChunk,
    RetrieveReq,
    RetrieveResp,
)
from bisheng.open_endpoints.domain.utils import get_default_operator, get_default_operator_async, resolve_operator
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.utils.util import sync_func_to_async

# build router
router = APIRouter(prefix='/filelib', tags=['OpenAPI', 'Knowledge'])


_KB_TYPES = (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value)


def _build_space_service(
        request: Request,
        login_user,
        version_repo: KnowledgeDocumentVersionRepository | None = None,
        doc_repo: KnowledgeDocumentRepository | None = None,
) -> KnowledgeSpaceService:
    """Build a KnowledgeSpaceService bound to the resolved acting identity.

    Mirrors the v1 DI factory but uses the F030 resolved operator (default
    operator or 代用户) instead of a JWT login. Repos are request-scoped Depends.
    """
    svc = KnowledgeSpaceService(request=request, login_user=login_user)
    svc.version_repo = version_repo
    svc.doc_repo = doc_repo
    return svc


@router.post('/', status_code=201)
async def create(
        request: Request,
        knowledge: KnowledgeCreate,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """Create a knowledge resource (F030 facade, dispatch by ``type``).

    type 0/1 → 文档 / QA 知识库（KnowledgeService）；type 3 → 知识空间
    （KnowledgeSpaceService，忽略 model，用 workbench embedding）；type 2 / 非法 → 不支持。
    """
    login_user = await get_default_operator_async()
    if knowledge.type in _KB_TYPES:
        # auth_type / is_released only apply to knowledge spaces (AD-07);
        # force defaults so they have no effect on knowledge bases.
        knowledge.auth_type = AuthTypeEnum.PUBLIC
        knowledge.is_released = False
        db_knowledge = await KnowledgeService.acreate_knowledge(request, login_user, knowledge)
        return resp_200(db_knowledge)
    if knowledge.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        space = await space_svc.create_knowledge_space(
            name=knowledge.name,
            description=knowledge.description,
            auth_type=knowledge.auth_type,
            is_released=knowledge.is_released,
        )
        return resp_200(space)
    raise KnowledgeTypeNotSupportedError.http_exception()


@router.put('/', status_code=201)
async def update_knowledge(
        *,
        request: Request,
        knowledge: KnowledgeUpdate,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """Update name/description of a knowledge resource (F030, dispatch by row.type)."""
    login_user = await get_default_operator_async()
    row = await KnowledgeDao.aquery_by_id(knowledge.knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        # Only name/description are mutable here (AD-06). Preserve is_released
        # (update_knowledge_space defaults it to False) and empty description on
        # missing to match KB semantics / doc (AD-09).
        updated = await space_svc.update_knowledge_space(
            space_id=knowledge.knowledge_id,
            name=knowledge.name,
            description=knowledge.description if knowledge.description is not None else "",
            is_released=row.is_released,
        )
        return resp_200(updated)
    if row.type in _KB_TYPES:
        # update_knowledge is sync and uses run_async_safe internally; run it in a
        # threadpool so it is not invoked on the endpoint's running event loop.
        updated = await run_in_threadpool(
            KnowledgeService.update_knowledge, request, login_user, knowledge)
        return resp_200(updated)
    raise KnowledgeTypeNotSupportedError.http_exception()


@router.get('/', status_code=200)
async def get_knowledge(
        *,
        request: Request,
        knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value, alias='type'),
        name: str | None = None,
        sort_by: str = Query(default='update_time'),
        page_size: int | None = 10,
        cursor: str | None = Query(default=None),
        user_id: int | None = None,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """List knowledge resources by ``type`` (F030 cursor pagination, INV-6).

    Params align with v1 ``GET /api/v1/knowledge``. ``user_id`` scopes the list
    to that user's visibility; omit to use the default operator (AD-02).
    Response is ``PageInfiniteCursorData`` (data/page_size/has_more/next_cursor).
    """
    login_user = await resolve_operator(user_id)
    if knowledge_type in _KB_TYPES:
        page = await KnowledgeService.get_knowledge(
            request,
            login_user,
            KnowledgeTypeEnum(knowledge_type),
            name=name,
            sort_by=sort_by,
            page_size=page_size,
            cursor=cursor,
        )
        return resp_200(page)
    if knowledge_type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        page = await space_svc.alist_mine_and_joined_cursor(
            name=name, page_size=page_size, cursor=cursor,
        )
        return resp_200(page)
    raise KnowledgeTypeNotSupportedError.http_exception()


@router.delete('/{knowledge_id}', status_code=200)
async def delete_knowledge_api(
        *,
        request: Request,
        knowledge_id: int,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """Delete a knowledge resource (F030, dispatch by row.type).

    Knowledge space (3) → ``KnowledgeSpaceService.delete_space`` (cascade child
    files/folders + ReBAC tuple cleanup + members). Knowledge base (0/1) →
    ``KnowledgeService.delete_knowledge``.
    """
    login_user = await get_default_operator_async()
    row = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        await space_svc.delete_space(knowledge_id)
        return resp_200(message='knowledge deleted successfully')
    if row.type in _KB_TYPES:
        await run_in_threadpool(
            KnowledgeService.delete_knowledge, request, login_user, knowledge_id)
        return resp_200(message='knowledge deleted successfully')
    raise KnowledgeTypeNotSupportedError.http_exception()


# Empty all knowledge resource contents (keep the resource itself).
@router.delete('/clear/{knowledge_id}', status_code=200)
async def clear_knowledge_files(
        *,
        request: Request,
        knowledge_id: int,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """Clear a knowledge resource's contents (F030, dispatch by row.type).

    Knowledge space (3) → ``KnowledgeSpaceService.clear_space`` (remove child
    files/folders + child tuples, keep the space). Knowledge base (0/1) →
    ``KnowledgeService.delete_knowledge(only_clear=True)``.
    """
    login_user = await get_default_operator_async()
    row = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        await space_svc.clear_space(knowledge_id)
        return resp_200(message='knowledge clear successfully')
    if row.type in _KB_TYPES:
        await run_in_threadpool(
            KnowledgeService.delete_knowledge, request, login_user, knowledge_id, only_clear=True)
        return resp_200(message='knowledge clear successfully')
    raise KnowledgeTypeNotSupportedError.http_exception()


@router.post('/file/{knowledge_id}')
async def upload_file(
        request: Request,
        knowledge_id: int,
        split_mode: Literal['auto', 'custom', 'hierarchical'] | None = Form(default='auto'),
        separator: list[str] | None = Form(default=None,
                                              description='Split text rule, If not passed on, it is the default'),
        separator_rule: list[str] | None = Form(
            default=None, description='Segmentation before or after the segmentation rule;before/after'),
        chunk_size: int | None = Form(default=None, description='Split text length, default if not passed'),
        chunk_overlap: int | None = Form(default=None,
                                            description='Split text overlap length, default if not passed'),
        hierarchy_level: int | None = Form(default=3),
        append_title: bool | None = Form(default=False),
        max_chunk_size: int | None = Form(default=1000),
        callback_url: str | None = Form(default=None, description='Return URL'),
        file_url: str | None = Form(default=None, description='File URL'),
        file: UploadFile | None = File(default=None, description='Upload file'),
        background_tasks: BackgroundTasks = None,
        retain_images: int | None = Form(default=1, description='Keep document image'),
        force_ocr: int | None = Form(default=0, description='EnableOCR'),
        enable_formula: int | None = Form(default=1, description='latexFormula Recognition'),
        filter_page_header_footer: int | None = Form(default=0, description='Filter Header Footer'),
        excel_rule: ExcelRule | None = Form(default={}, description="excel rule"),
        parent_id: int | None = Form(default=None,
                                        description='Target folder id; knowledge-space only, must exist. '
                                                    'Ignored for knowledge bases.'),
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
):
    """Upload a file to a knowledge resource (F030 facade, dispatch by row.type).

    Knowledge base (0/1) → existing parse/split/ingest pipeline (``parent_id``
    ignored). Knowledge space (3) → ``KnowledgeSpaceService.add_file`` which
    natively places the file under ``parent_id`` (must exist, else 18010).
    """
    if file:
        file_name = file.filename
        if not file_name:
            return resp_500(message='file name must be not empty')
        # Cache Local
        file_path = await sync_func_to_async(save_download_file)(file.file, 'bisheng', file_name)
    else:
        file_path, file_name = await async_file_download(file_url)

    loging_user = await get_default_operator_async()

    db_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not db_knowledge:
        raise NotFoundError.http_exception()

    # Knowledge space: delegate to the space file-add path (handles parent_id).
    if db_knowledge.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, loging_user, version_repo, doc_repo)
        res = await space_svc.add_file(
            knowledge_id=knowledge_id,
            file_path=[file_path],
            parent_id=parent_id,
        )
        return resp_200(data=res[0])

    if db_knowledge.type not in _KB_TYPES:
        raise KnowledgeTypeNotSupportedError.http_exception()

    # Knowledge base: unchanged parse/split/ingest pipeline (parent_id ignored).
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
def delete_file_batch_api(request: Request, file_ids: list[int]):
    """ Bulk delete knowledge file information """
    login_user = get_default_operator()
    KnowledgeService.delete_knowledge_file(request, login_user, file_ids)
    return resp_200()


@router.get('/file/list', status_code=200)
async def get_filelist(request: Request,
                       knowledge_id: int,
                       parent_id: int | None = None,
                       keyword: str = None,
                       status: list[int] = Query(default=None),
                       page_size: int = 10,
                       cursor: str | None = Query(default=None),
                       user_id: int | None = None,
                       version_repo: KnowledgeDocumentVersionRepository = Depends(
                           get_knowledge_document_version_repository),
                       doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository)):
    """List files of a knowledge resource (F030 cursor pagination, dispatch by row.type).

    Knowledge base (0/1) → flat cursor list (``aget_knowledge_files_cursor``,
    ``parent_id`` ignored). Knowledge space (3) → hierarchical cursor list
    (``list_space_children``) under ``parent_id`` (root when omitted). ``user_id``
    scopes visibility to that user (AD-02). Returns ``PageInfiniteCursorData`` + ``writeable``.
    """
    login_user = await resolve_operator(user_id)
    db_knowledge = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not db_knowledge:
        raise NotFoundError.http_exception()

    if db_knowledge.type == KnowledgeTypeEnum.SPACE.value:
        space_svc = _build_space_service(request, login_user, version_repo, doc_repo)
        if keyword:
            # Keyword search over the space → offset-based search adapted to cursor.
            page = await space_svc.asearch_space_children_cursor(
                knowledge_id,
                parent_id=parent_id,
                keyword=keyword,
                file_status=status,
                page_size=page_size,
                cursor=cursor,
            )
        else:
            # No keyword → native cursor folder listing under parent_id.
            page = await space_svc.list_space_children(
                knowledge_id,
                parent_id=parent_id,
                file_status=status,
                cursor=cursor,
                page_size=page_size,
            )
        # writeable: whether the acting user can write to the target container.
        writeable = await space_svc.can_write_space_container(knowledge_id, parent_id)
        data = page.model_dump()
        data['writeable'] = writeable
        return resp_200(data=data)

    if db_knowledge.type not in _KB_TYPES:
        raise KnowledgeTypeNotSupportedError.http_exception()

    page, writeable = await KnowledgeService.aget_knowledge_files_cursor(
        request, login_user, knowledge_id,
        file_name=keyword, status=status, page_size=page_size, cursor=cursor,
    )
    data = page.model_dump()
    data['writeable'] = writeable
    return resp_200(data=data)


@router.post('/chunks')
async def post_chunks(request: Request,
                      knowledge_id: int = Form(...),
                      metadata: str = Form(...),
                      split_mode: Literal['auto', 'custom', 'hierarchical'] | None = Form(default='auto'),
                      separator: list[str] | None = Form(default=None),
                      separator_rule: list[str] | None = Form(default=None),
                      chunk_size: int | None = Form(default=None),
                      chunk_overlap: int | None = Form(default=None),
                      hierarchy_level: int | None = Form(default=3),
                      append_title: bool | None = Form(default=False),
                      max_chunk_size: int | None = Form(default=1000),
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
           data: list[APIAddQAParam] = Body(embed=True),
           user_id: int | None = Body(default=None, embed=True)):
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
              user_id: int | None = Body(default=None, embed=True)):
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
def delete_qa_data(*, qa_id: int, question: str | None = None):
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
        return resp_500(message=f'error e={e!s}')


@router.post('/update_qa', status_code=200)
def update_qa(
        *,
        id: int = Body(embed=True),
        question: str | None = Body(default=None, embed=True),
        original_question: str | None = Body(default=None, embed=True),
        answer: list[str] | None = Body(default=None, embed=True),
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
        return resp_500(message=f'error e={e!s}')


@router.get('/detail_qa', status_code=200)
def detail_qa(*, id: int):
    """ Get questions on information """
    qa = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    return resp_200(qa)


@router.post('/retrieve')
async def retrieve_chunks(
        request: Request,
        req: RetrieveReq,
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
):
    """Retrieve top-k chunks across one or more knowledge bases (no LLM generation).

    Designed for external retrieval-tool integrations (e.g. agents that bring
    their own LLM). F030: runs as the configured default operator by default;
    when ``req.user_id`` is set, retrieval is scoped to that user's visible
    resources/files (the "代用户检索" protocol F029 deferred). Per-knowledge-base
    tag filtering keeps the existing ``filters`` structure (no flat tags).
    """
    # F030 AD-02: bind the chat service to the resolved acting identity so the
    # existing per-user view_file/view_space filtering in aretrieve_chunks
    # (INV-7) applies to the target user instead of always the default operator.
    login_user = await resolve_operator(req.user_id)
    chat_svc = KnowledgeSpaceChatService(request=request, login_user=login_user)
    chat_svc.version_repo = version_repo

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

    chunks = [
        RetrieveChunk(
            content=doc.page_content,
            knowledge_id=kb_id,
            document_id=int(doc.metadata.get("document_id", 0)),
            document_name=str(doc.metadata.get("document_name", "")),
            chunk_index=int(doc.metadata.get("chunk_index", 0)),
        )
        for kb_id, doc in results
    ]
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
