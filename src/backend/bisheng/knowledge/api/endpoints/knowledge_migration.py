"""系统管理员跨知识库文件迁移 API。"""

from typing import Literal

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.api.dependencies import get_knowledge_migration_service
from bisheng.knowledge.domain.schemas.knowledge_migration_schema import (
    MigrationBatchCreateRequest,
)
from bisheng.knowledge.domain.services.knowledge_migration_service import (
    KnowledgeMigrationService,
)

router = APIRouter(
    prefix="/knowledge/migrations",
    tags=["KnowledgeMigration"],
)


@router.get("/spaces")
async def list_migration_spaces(
    purpose: Literal["source", "target"] = "source",
    keyword: str | None = None,
    space_level: str | None = None,
    preserve_link: bool = False,
    source_level: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await service.list_spaces(
            login_user,
            keyword=keyword,
            space_level=space_level,
            page=page,
            page_size=page_size,
            purpose=purpose,
            preserve_link=preserve_link,
            source_level=source_level,
        )
    )


@router.get("/spaces/{space_id}/children")
async def list_migration_children(
    space_id: int,
    parent_id: int | None = None,
    cursor: str | None = None,
    page_size: int = Query(50, ge=1, le=200),
    purpose: Literal["source", "target"] = "source",
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await service.list_children(
            login_user,
            space_id=space_id,
            parent_id=parent_id,
            cursor=cursor,
            page_size=page_size,
            purpose=purpose,
        )
    )


@router.post("/batches")
async def create_migration_batch(
    request: MigrationBatchCreateRequest,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.create_batch(login_user, request))


@router.get("/batches")
async def list_migration_batches(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await service.list_batches(
            login_user,
            page=page,
            page_size=page_size,
            status_filter=status,
        )
    )


@router.get("/batches/{batch_no}")
async def get_migration_batch(
    batch_no: str,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.get_batch(login_user, batch_no))


@router.get("/batches/{batch_no}/units")
async def list_migration_units(
    batch_no: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await service.list_units(
            login_user,
            batch_no,
            page=page,
            page_size=page_size,
            status_filter=status,
        )
    )


@router.get("/batches/{batch_no}/attempts")
async def list_migration_attempts(
    batch_no: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await service.list_attempts(
            login_user,
            batch_no,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/batches/{batch_no}/confirm-overwrite")
async def confirm_migration_overwrite(
    batch_no: str,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.confirm_overwrite(login_user, batch_no))


@router.post("/batches/{batch_no}/abandon")
async def abandon_migration_batch(
    batch_no: str,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.abandon(login_user, batch_no))


@router.post("/batches/{batch_no}/retry")
async def retry_migration_batch(
    batch_no: str,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.retry(login_user, batch_no))


@router.delete("/batches/{batch_no}")
async def delete_migration_batch(
    batch_no: str,
    service: KnowledgeMigrationService = Depends(get_knowledge_migration_service),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(await service.soft_delete(login_user, batch_no))
