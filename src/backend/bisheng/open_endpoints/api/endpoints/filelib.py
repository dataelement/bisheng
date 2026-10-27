import asyncio
import json
import os
from typing import Annotated, List, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from loguru import logger
from starlette.responses import FileResponse

from bisheng.api.services import knowledge_imp
from bisheng.api.v1.schemas import ChunkInput, ExcelRule, KnowledgeFileOne, KnowledgeFileProcess, resp_200, resp_500
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.api import UnifiedResponseModel
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import async_file_download, save_download_file
from bisheng.core.logger import trace_id_var
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum, KnowledgeUpdate
from bisheng.knowledge.domain.models.knowledge_file import (
    QAKnoweldgeDao,
    QAKnowledgeUpsert,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.knowledge.rag.async_retrieval_runtime import (
    AsyncRetrievalRuntime,
    get_async_retrieval_runtime,
)
from bisheng.open_endpoints.api.dependencies import (
    build_filelib_space_query_service,
    build_knowledge_space_chat_service_for_openapi,
    get_filelib_developer_token_principal,
    get_filelib_file_source_service,
    get_filelib_knowledge_document_repository,
    get_filelib_knowledge_document_version_repository,
    get_filelib_request_user,
    get_filelib_retrieve_source_service,
    get_filelib_space_command_service,
    get_filelib_space_query_service,
    get_filelib_user_context_service,
    get_knowledge_file_repository,
)
from bisheng.open_endpoints.domain.schemas.filelib import (
    APIAddQAParam,
    APIAppendQAParam,
    FilelibSpaceCreate,
    FileSourceUrlResp,
    QueryQAParam,
    RetrieveReq,
)
from bisheng.open_endpoints.domain.services.filelib_file_source_service import FilelibFileSourceService
from bisheng.open_endpoints.domain.services.filelib_knowledge_list_service import FilelibKnowledgeListService
from bisheng.open_endpoints.domain.services.filelib_retrieve_service import FilelibRetrieveService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import (
    FilelibRetrieveSourceService,
)
from bisheng.open_endpoints.domain.services.filelib_space_command_service import FilelibSpaceCommandService
from bisheng.open_endpoints.domain.services.filelib_space_query_service import (
    FilelibSpaceQueryService,
)
from bisheng.open_endpoints.domain.services.filelib_space_query_service import (
    _parse_document_type_code as _parse_document_type_code,
)
from bisheng.open_endpoints.domain.services.filelib_user_context_service import FilelibUserContextService
from bisheng.open_endpoints.domain.utils import get_default_operator
from bisheng.utils.util import sync_func_to_async

# build router
router = APIRouter(prefix="/filelib", tags=["OpenAPI", "Knowledge"])
OPENAPI_FILE_CATEGORY_ID = "入库分类测试"
OPENAPI_FILE_CATEGORY_GROUP_CLASS_CODE = "分类编码测试"
OPENAPI_FILE_DOC_TYPE_CODE = "分类赋码测试"
OPENAPI_TEXT_OBJECT_SUFFIXES = (".md", ".markdown", ".txt")
OPENAPI_FILE_CONTENT_PAGE_SIZE = 1000


def _resolve_filelib_knowledge_type(
    type_value: int,
    compatibility_value: int | None,
    *,
    type_was_provided: bool,
) -> KnowledgeTypeEnum:
    if type_was_provided and compatibility_value is not None and type_value != compatibility_value:
        raise HTTPException(
            status_code=422,
            detail="type and knowledge_type must be identical when both are provided",
        )
    raw_value = compatibility_value if compatibility_value is not None and not type_was_provided else type_value
    try:
        resolved = KnowledgeTypeEnum(raw_value)
        if resolved is not KnowledgeTypeEnum.SPACE:
            raise HTTPException(status_code=422, detail="filelib file APIs require SPACE knowledge")
        return resolved
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unsupported knowledge resource type") from exc


@router.post("/", status_code=201)
async def create(
    request: Request,
    knowledge: FilelibSpaceCreate,
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    return resp_200(await service.create(knowledge))


@router.put("/", status_code=201)
async def update_knowledge(
    *,
    request: Request,
    knowledge: KnowledgeUpdate,
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    result = await service.update(knowledge.knowledge_id, name=knowledge.name, description=knowledge.description)
    return resp_200(result)


@router.get("/", status_code=200)
async def get_knowledge(
    *,
    request: Request,
    knowledge_type: Annotated[int, Query(alias="type")] = KnowledgeTypeEnum.SPACE.value,
    compatibility_knowledge_type: Annotated[
        int | None,
        Query(alias="knowledge_type"),
    ] = None,
    name: str | None = None,
    page_size: Annotated[int, Query(ge=1)] = 10,
    cursor: str | None = None,
    login_user: UserPayload = Depends(get_filelib_request_user),
):
    """Read all knowledge base information."""
    _resolve_filelib_knowledge_type(
        knowledge_type,
        compatibility_knowledge_type,
        type_was_provided="type" in request.query_params,
    )
    result = await FilelibKnowledgeListService(request=request, login_user=login_user).list_spaces(
        name=name,
        cursor=cursor,
        page_size=page_size,
    )
    return resp_200(data=result)


@router.delete("/{knowledge_id}", status_code=200)
async def delete_knowledge_api(
    *,
    request: Request,
    knowledge_id: int,
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    await service.delete_space(knowledge_id)
    return resp_200(message="knowledge deleted successfully")


# Empty all Knowledge Base file contents
@router.delete("/clear/{knowledge_id}", status_code=200)
async def clear_knowledge_files(
    *,
    request: Request,
    knowledge_id: int,
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    await service.clear(knowledge_id)
    return resp_200(message="knowledge clear successfully")


@router.post("/file/{knowledge_id}")
async def upload_file(
    request: Request,
    knowledge_id: int,
    split_mode: Optional[Literal["auto", "custom", "hierarchical"]] = Form(default="auto"),
    separator: Optional[List[str]] = Form(
        default=None, description="Split text rule, If not passed on, it is the default"
    ),
    separator_rule: Optional[List[str]] = Form(
        default=None, description="Segmentation before or after the segmentation rule;before/after"
    ),
    chunk_size: Optional[int] = Form(default=None, description="Split text length, default if not passed"),
    chunk_overlap: Optional[int] = Form(default=None, description="Split text overlap length, default if not passed"),
    hierarchy_level: Optional[int] = Form(default=3),
    append_title: Optional[bool] = Form(default=False),
    max_chunk_size: Optional[int] = Form(default=1000),
    callback_url: Optional[str] = Form(default=None, description="Return URL"),
    file_url: Optional[str] = Form(default=None, description="File URL"),
    file: Optional[UploadFile] = File(default=None, description="Upload file"),
    background_tasks: BackgroundTasks = None,
    retain_images: Optional[int] = Form(default=1, description="Keep document image"),
    force_ocr: Optional[int] = Form(default=0, description="EnableOCR"),
    enable_formula: Optional[int] = Form(default=1, description="latexFormula Recognition"),
    filter_page_header_footer: Optional[int] = Form(default=0, description="Filter Header Footer"),
    excel_rule: Optional[ExcelRule] = Form(default={}, description="excel rule"),
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    await service.prepare_upload(knowledge_id)
    if file:
        file_name = file.filename
        if not file_name:
            return resp_500(message="file name must be not empty")
        # Cache Local
        file_path = await sync_func_to_async(save_download_file)(file.file, "bisheng", file_name)
    else:
        file_path, file_name = await async_file_download(file_url)

    req_data = KnowledgeFileProcess(
        knowledge_id=knowledge_id,
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
        file_list=[KnowledgeFileOne(file_path=file_path, excel_rule=excel_rule)],
    )

    res = await service.upload(req_data, background_tasks=background_tasks)
    return resp_200(data=res[0])


@router.delete("/file/{file_id}", status_code=200)
async def delete_knowledge_file(
    request: Request, file_id: int, service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service)
):
    await service.delete_files([file_id])
    return resp_200()


@router.post("/delete_file", status_code=200)
async def delete_file_batch_api(
    request: Request,
    file_ids: List[int],
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    await service.delete_files(file_ids)
    return resp_200()


@router.get("/file/list", status_code=200)
async def get_filelist(
    request: Request,
    knowledge_id: int,
    login_user: UserPayload = Depends(get_filelib_request_user),
    keyword: str = None,
    status: List[int] = Query(default=None),
    page_size: int = 10,
    page_num: int = 1,
    service: FilelibSpaceQueryService = Depends(get_filelib_space_query_service),
):
    return resp_200(
        data=await service.list_files(
            knowledge_id, keyword=keyword, status=status, page_num=page_num, page_size=page_size
        )
    )


@router.get("/file/detail", status_code=200)
async def get_file_detail(
    request: Request,
    file_encoding: str = Query(..., description="File encoding"),
    knowledge_id: Optional[int] = Query(default=None, description="Knowledge resource id"),
    content_format: Literal["text", "markdown"] = Query(default="text", description="Content format"),
    login_user: UserPayload = Depends(get_filelib_request_user),
    service: FilelibSpaceQueryService = Depends(get_filelib_space_query_service),
):
    return resp_200(data=await service.detail(file_encoding, knowledge_id, content_format))


@router.get("/file/source_url", response_model=UnifiedResponseModel[FileSourceUrlResp])
async def get_file_source_url(
    response: Response,
    file_id: int = Query(..., gt=0, description="KnowledgeFile ID, same as retrieve document_id"),
    service: FilelibFileSourceService = Depends(get_filelib_file_source_service),
) -> UnifiedResponseModel:
    """Return a seven-day original-file link for an authorized file entry."""
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.get_source_url(file_id))


@router.post("/chunks")
async def post_chunks(
    request: Request,
    knowledge_id: int = Form(...),
    metadata: str = Form(...),
    split_mode: Optional[Literal["auto", "custom", "hierarchical"]] = Form(default="auto"),
    separator: Optional[List[str]] = Form(default=None),
    separator_rule: Optional[List[str]] = Form(default=None),
    chunk_size: Optional[int] = Form(default=None),
    chunk_overlap: Optional[int] = Form(default=None),
    hierarchy_level: Optional[int] = Form(default=3),
    append_title: Optional[bool] = Form(default=False),
    max_chunk_size: Optional[int] = Form(default=1000),
    file: UploadFile = File(...),
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    """Upload files to the knowledge base and sync the interface"""
    await service.prepare_upload(knowledge_id)
    file_name = file.filename
    if not file_name:
        return resp_500(message="file name must be not empty")
    file_path = await sync_func_to_async(save_download_file)(file.file, "bisheng", file_name)

    req_data = KnowledgeFileProcess(
        knowledge_id=knowledge_id,
        split_mode=split_mode,
        separator=separator,
        separator_rule=separator_rule,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        hierarchy_level=hierarchy_level,
        append_title=append_title,
        max_chunk_size=max_chunk_size,
        file_list=[KnowledgeFileOne(file_path=file_path)],
    )

    res = await service.upload(req_data, synchronous=True)
    return resp_200(data=res[0])


@router.post("/chunks_string")
async def post_string_chunks(
    request: Request,
    document: ChunkInput,
    service: FilelibSpaceCommandService = Depends(get_filelib_space_command_service),
):
    return resp_200(data=await service.ingest_strings(document.knowledge_id, document.documents))


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


@router.post("/retrieve")
async def retrieve_chunks(
    request: Request,
    req: RetrieveReq,
    principal: DeveloperTokenPrincipal = Depends(get_filelib_developer_token_principal),
    user_context_service: FilelibUserContextService = Depends(get_filelib_user_context_service),
    version_repo: KnowledgeDocumentVersionRepository = Depends(get_filelib_knowledge_document_version_repository),
    doc_repo: KnowledgeDocumentRepository = Depends(get_filelib_knowledge_document_repository),
    source_service: FilelibRetrieveSourceService = Depends(get_filelib_retrieve_source_service),
    file_repo: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
    retrieval_runtime: AsyncRetrievalRuntime = Depends(get_async_retrieval_runtime),
):
    """Retrieve top-k chunks across one or more knowledge bases (no LLM generation).

    Designed for external retrieval-tool integrations (e.g. agents that bring
    their own LLM). The resolved request user controls permissions and scope.
    """

    async def _execute_retrieval():
        async with user_context_service.use_user(principal, req.external_id) as login_user:
            query = build_filelib_space_query_service(
                request=request,
                user=login_user,
                session=file_repo.session,
                storage=getattr(source_service, "storage", None),
            )
            await query.require_spaces(req.knowledge_base_ids)
            chat_svc = build_knowledge_space_chat_service_for_openapi(
                request=request,
                request_user=login_user,
                version_repo=version_repo,
                doc_repo=doc_repo,
                file_repo=file_repo,
                retrieval_runtime=retrieval_runtime,
            )
            return await FilelibRetrieveService(chat_svc, source_service, retrieval_runtime).retrieve(req)

    try:
        result = await asyncio.wait_for(
            _execute_retrieval(),
            timeout=retrieval_runtime.config.total_timeout_seconds,
        )
    except BaseErrorCode as e:
        if getattr(e, "http_status", 200) != 200:
            raise
        return e.return_resp_instance()
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="knowledge retrieval timed out") from exc

    return resp_200(data=result)


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
