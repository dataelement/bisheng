"""MCP-local orchestration over the existing knowledge application services.

This module mirrors the frozen v2 filelib facade's dispatch decisions without
calling FastAPI endpoint functions. The HTTP API remains unchanged; business
authorization, persistence, projections, scheduling, and audit hooks continue
to run in the existing domain/application services.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from bisheng.api.v1.schemas import ExcelRule, KnowledgeFileOne, KnowledgeFileProcess
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError
from bisheng.common.errcode.open_api import OpenApiAuthDependencyUnavailableError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.common.errcode.tenant_fga import PermissionBackendUnavailableError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    KnowledgeCreate,
    KnowledgeDao,
    KnowledgeRead,
    KnowledgeTypeEnum,
    KnowledgeUpdate,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.open_endpoints.domain.schemas.filelib import RetrieveChunk, RetrieveReq, RetrieveResp
from bisheng.open_endpoints.domain.utils import get_open_api_operator, get_open_api_operator_async
from bisheng.open_mcp.auth import get_current_mcp_scope
from bisheng.role.domain.services.quota_service import QuotaService

_KB_TYPES = (KnowledgeTypeEnum.NORMAL.value, KnowledgeTypeEnum.QA.value)


def current_request() -> Request:
    scope = get_current_mcp_scope()
    if scope is None:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v2/mcp",
            "raw_path": b"/api/v2/mcp",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "server": ("open-mcp", 0),
        }
    return Request(scope)


@asynccontextmanager
async def knowledge_repositories():
    async with get_async_db_session() as session:
        yield (
            KnowledgeDocumentVersionRepositoryImpl(session),
            KnowledgeDocumentRepositoryImpl(session),
        )


def _space_service(request: Request, login_user, version_repo, doc_repo) -> KnowledgeSpaceService:
    service = KnowledgeSpaceService(request=request, login_user=login_user)
    service.version_repo = version_repo
    service.doc_repo = doc_repo
    return service


async def list_knowledge(*, request: Request, command, version_repo, doc_repo):
    login_user = await get_open_api_operator_async()
    if command.resource_type in _KB_TYPES:
        return await KnowledgeService.get_knowledge(
            request,
            login_user,
            KnowledgeTypeEnum(command.resource_type),
            name=command.name,
            sort_by=command.sort_by,
            page_size=command.page_size,
            cursor=command.cursor,
        )
    if command.resource_type == KnowledgeTypeEnum.SPACE.value:
        return await _space_service(request, login_user, version_repo, doc_repo).alist_mine_and_joined_cursor(
            name=command.name,
            page_size=command.page_size,
            cursor=command.cursor,
        )
    raise KnowledgeTypeNotSupportedError.http_exception()


async def create_knowledge(*, request: Request, command, version_repo, doc_repo):
    login_user = await get_open_api_operator_async()
    knowledge = KnowledgeCreate(
        name=command.name,
        type=command.resource_type,
        description=command.description,
        model=command.model,
        auth_type=AuthTypeEnum(command.auth_type),
        is_released=command.is_released,
    )
    if command.resource_type in _KB_TYPES:
        knowledge.auth_type = AuthTypeEnum.PUBLIC
        knowledge.is_released = False
        created = await KnowledgeService.acreate_knowledge(request, login_user, knowledge)
        return (await KnowledgeService.aconvert_knowledge_read(login_user, [created]))[0]
    if command.resource_type == KnowledgeTypeEnum.SPACE.value:
        service = _space_service(request, login_user, version_repo, doc_repo)
        created = await service.create_knowledge_space(
            name=knowledge.name,
            description=knowledge.description,
            auth_type=knowledge.auth_type,
            is_released=knowledge.is_released,
        )
        return KnowledgeRead(
            **created.model_dump(),
            user_name=login_user.user_name,
            actions=sorted(await service._get_effective_actions("knowledge_space", created.id)),
        )
    raise KnowledgeTypeNotSupportedError.http_exception()


async def update_knowledge(*, request: Request, command, version_repo, doc_repo):
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(command.knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        return await _space_service(request, login_user, version_repo, doc_repo).update_knowledge_space(
            space_id=command.knowledge_id,
            name=command.name,
            description=command.description if command.description is not None else "",
            is_released=row.is_released,
        )
    if row.type in _KB_TYPES:
        return await run_in_threadpool(
            KnowledgeService.update_knowledge,
            request,
            login_user,
            KnowledgeUpdate(**command.model_dump()),
        )
    raise KnowledgeTypeNotSupportedError.http_exception()


async def delete_knowledge(*, request: Request, knowledge_id: int, version_repo, doc_repo) -> None:
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        await _space_service(request, login_user, version_repo, doc_repo).delete_space(knowledge_id)
        return
    if row.type in _KB_TYPES:
        await run_in_threadpool(KnowledgeService.delete_knowledge, request, login_user, knowledge_id)
        return
    raise KnowledgeTypeNotSupportedError.http_exception()


async def clear_knowledge(*, request: Request, knowledge_id: int, version_repo, doc_repo) -> None:
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        await _space_service(request, login_user, version_repo, doc_repo).clear_space(knowledge_id)
        return
    if row.type in _KB_TYPES:
        await run_in_threadpool(
            KnowledgeService.delete_knowledge,
            request,
            login_user,
            knowledge_id,
            only_clear=True,
        )
        return
    raise KnowledgeTypeNotSupportedError.http_exception()


async def retrieve_knowledge(*, request: Request, command, version_repo) -> RetrieveResp:
    login_user = await get_open_api_operator_async()
    service = KnowledgeSpaceChatService(request=request, login_user=login_user)
    service.version_repo = version_repo
    request_data = RetrieveReq.model_validate(command.model_dump())
    filters = None
    if request_data.filters and request_data.filters.knowledge_base_filters:
        filters = {
            item.knowledge_base_id: {
                "tags": item.tags,
                "tag_match_mode": item.tag_match_mode,
            }
            for item in request_data.filters.knowledge_base_filters
        }
    try:
        results = await service.aretrieve_chunks(
            query=request_data.query,
            knowledge_base_ids=request_data.knowledge_base_ids,
            kb_filters=filters,
            top_k=request_data.top_k,
            max_content=request_data.max_content,
        )
    except (PermissionBackendUnavailableError, PermissionServiceUnavailableError) as exc:
        raise OpenApiAuthDependencyUnavailableError() from exc
    chunks = [
        RetrieveChunk(
            content=document.page_content,
            knowledge_id=knowledge_id,
            document_id=int(document.metadata.get("document_id", 0)),
            document_name=str(document.metadata.get("document_name", "")),
            chunk_index=int(document.metadata.get("chunk_index", 0)),
            document_update_time=str(document.metadata.get("document_update_time", "")),
        )
        for knowledge_id, document in results
    ]
    return RetrieveResp(chunks=chunks, total=len(chunks))


async def ensure_upload_allowed(*, request: Request, command, version_repo, doc_repo) -> None:
    """Reject inaccessible upload targets before decoding or downloading file bytes."""
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(command.knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        service = _space_service(request, login_user, version_repo, doc_repo)
        if command.parent_id:
            await service._require_action("folder", command.parent_id, "upload_file")
            await service._get_folder_for_action(command.knowledge_id, command.parent_id)
        else:
            await service._require_action("knowledge_space", command.knowledge_id, "upload_file")
        service._ensure_space_async_task_tenant_consistency(row, "upload_file")
        return
    if row.type not in _KB_TYPES:
        raise KnowledgeTypeNotSupportedError.http_exception()
    try:
        await KnowledgeService.permission_service.ensure_knowledge_write_async(
            login_user=login_user,
            owner_user_id=row.user_id,
            knowledge_id=row.id,
        )
    except UnAuthorizedError:
        raise UnAuthorizedError.http_exception()
    KnowledgeService.ensure_knowledge_upload_tenant_consistency(login_user, row)


async def upload_knowledge_file(*, request: Request, command, path: str, file_name: str, version_repo, doc_repo):
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(command.knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        results = await _space_service(request, login_user, version_repo, doc_repo).add_file(
            knowledge_id=command.knowledge_id,
            file_path=[path],
            parent_id=command.parent_id,
        )
        return results[0]
    if row.type not in _KB_TYPES:
        raise KnowledgeTypeNotSupportedError.http_exception()
    process = KnowledgeFileProcess(
        knowledge_id=command.knowledge_id,
        split_mode=command.split_mode,
        separator=command.separator,
        separator_rule=command.separator_rule,
        chunk_size=command.chunk_size,
        chunk_overlap=command.chunk_overlap,
        hierarchy_level=3,
        append_title=False,
        max_chunk_size=1000,
        retain_images=command.retain_images,
        force_ocr=command.force_ocr,
        enable_formula=command.enable_formula,
        filter_page_header_footer=command.filter_page_header_footer,
        callback_url=None,
        file_list=[KnowledgeFileOne(file_path=path, excel_rule=ExcelRule())],
    )
    limit = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
    results = await KnowledgeService.aprocess_knowledge_file(
        request=request,
        login_user=login_user,
        background_tasks=BackgroundTasks(),
        req_data=process,
        upload_limit_bytes=limit,
    )
    return results[0]


async def list_knowledge_files(*, request: Request, command, version_repo, doc_repo):
    login_user = await get_open_api_operator_async()
    row = await KnowledgeDao.aquery_by_id(command.knowledge_id)
    if not row:
        raise NotFoundError.http_exception()
    if row.type == KnowledgeTypeEnum.SPACE.value:
        service = _space_service(request, login_user, version_repo, doc_repo)
        if command.keyword:
            page = await service.asearch_space_children_cursor(
                command.knowledge_id,
                parent_id=command.parent_id,
                keyword=command.keyword,
                file_status=command.status,
                page_size=command.page_size,
                cursor=command.cursor,
            )
        else:
            page = await service.list_space_children(
                command.knowledge_id,
                parent_id=command.parent_id,
                file_status=command.status,
                cursor=command.cursor,
                page_size=command.page_size,
            )
        data = page.model_dump()
        data["writeable"] = await service.can_write_space_container(command.knowledge_id, command.parent_id)
        return data
    if row.type not in _KB_TYPES:
        raise KnowledgeTypeNotSupportedError.http_exception()
    page, writeable = await KnowledgeService.aget_knowledge_files_cursor(
        request,
        login_user,
        command.knowledge_id,
        file_name=command.keyword,
        status=command.status,
        page_size=command.page_size,
        cursor=command.cursor,
    )
    data = page.model_dump()
    data["writeable"] = writeable
    return data


async def delete_knowledge_files(*, request: Request, file_ids: list[int]) -> None:
    login_user = get_open_api_operator()
    await run_in_threadpool(KnowledgeService.delete_knowledge_file, request, login_user, file_ids)


__all__ = [
    "clear_knowledge",
    "create_knowledge",
    "current_request",
    "delete_knowledge",
    "delete_knowledge_files",
    "ensure_upload_allowed",
    "knowledge_repositories",
    "list_knowledge",
    "list_knowledge_files",
    "retrieve_knowledge",
    "update_knowledge",
    "upload_knowledge_file",
]
