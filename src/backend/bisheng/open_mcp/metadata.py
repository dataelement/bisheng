"""MCP-local orchestration for knowledge and file metadata.

Mirrors the frozen v2 ``/api/v2/knowledge`` metadata endpoints without calling
the FastAPI endpoint functions. Permission checks stay in
``KnowledgeService`` / ``KnowledgeFileService``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.schemas.knowledge_schema import (
    AddKnowledgeMetadataFieldsReq,
    ModifyKnowledgeFileMetaDataReq,
    UpdateKnowledgeMetadataFieldsReq,
)
from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.open_endpoints.domain.schemas.knowledge import DeleteUserMetadataReq
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async


@asynccontextmanager
async def _services():
    async with get_async_db_session() as session:
        knowledge_repo = KnowledgeRepositoryImpl(session)
        file_repo = KnowledgeFileRepositoryImpl(session)
        yield (
            KnowledgeService(knowledge_repository=knowledge_repo, knowledge_file_repository=file_repo),
            KnowledgeFileService(knowledge_repository=knowledge_repo, knowledge_file_repository=file_repo),
        )


async def add_fields(*, knowledge_id: int, fields: list[dict[str, Any]]) -> None:
    login_user = await get_open_api_operator_async()
    request = AddKnowledgeMetadataFieldsReq(knowledge_id=knowledge_id, metadata_fields=fields)
    async with _services() as (knowledge_service, _):
        await knowledge_service.add_metadata_fields(login_user, request)


async def rename_fields(*, knowledge_id: int, fields: list[dict[str, str]]) -> None:
    login_user = await get_open_api_operator_async()
    request = UpdateKnowledgeMetadataFieldsReq(knowledge_id=knowledge_id, metadata_fields=fields)
    tasks = BackgroundTasks()
    async with _services() as (knowledge_service, _):
        await knowledge_service.update_metadata_fields(login_user, request, tasks)
    # No HTTP response lifecycle here, so run the follow-up work (vector metadata refresh) explicitly.
    await tasks()


async def delete_fields(*, knowledge_id: int, field_names: list[str]) -> None:
    login_user = await get_open_api_operator_async()
    tasks = BackgroundTasks()
    async with _services() as (knowledge_service, _):
        await knowledge_service.delete_metadata_fields(login_user, knowledge_id, field_names, tasks)
    await tasks()


async def list_fields(*, knowledge_id: int) -> Any:
    login_user = await get_open_api_operator_async()
    async with _services() as (knowledge_service, _):
        return await knowledge_service.list_metadata_fields(login_user, knowledge_id)


async def add_file_metadata(*, knowledge_id: int, items: list[dict[str, Any]]) -> None:
    login_user = await get_open_api_operator_async()
    requests = [ModifyKnowledgeFileMetaDataReq.model_validate(item) for item in items]
    async with _services() as (_, file_service):
        await file_service.add_file_user_metadata(login_user, knowledge_id, requests)


async def modify_file_metadata(*, knowledge_id: int, items: list[dict[str, Any]]) -> None:
    login_user = await get_open_api_operator_async()
    requests = [ModifyKnowledgeFileMetaDataReq.model_validate(item) for item in items]
    async with _services() as (_, file_service):
        await file_service.batch_modify_file_user_metadata(login_user, knowledge_id, requests)


async def delete_file_metadata(*, knowledge_id: int, items: list[dict[str, Any]]) -> None:
    login_user = await get_open_api_operator_async()
    requests = [DeleteUserMetadataReq.model_validate(item) for item in items]
    async with _services() as (_, file_service):
        await file_service.batch_delete_file_user_metadata(login_user, knowledge_id, requests)


async def list_file_metadata(*, knowledge_id: int, knowledge_file_ids: list[int]) -> Any:
    login_user = await get_open_api_operator_async()
    async with _services() as (_, file_service):
        return await file_service.list_knowledge_file_user_metadata(login_user, knowledge_id, knowledge_file_ids)


__all__ = [
    "add_fields",
    "add_file_metadata",
    "delete_fields",
    "delete_file_metadata",
    "list_fields",
    "list_file_metadata",
    "modify_file_metadata",
    "rename_fields",
]
