"""Thin web entry points for the assembled durable knowledge processing path."""

from fastapi import APIRouter, Depends, Path, Query, Request

from bisheng.admin.application.tenant_scope import require_expected_management_tenant, resolve_management_scope
from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.admin_scope import AdminScopeChangedError
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.schemas.processing_job import (
    ItemState,
    JobState,
    ProcessingCreateRequest,
    ProcessingKind,
    ProcessingPrecheckRequest,
    ProcessingRetryRequest,
)
from bisheng.knowledge.domain.schemas.processing_settings import (
    DocumentProcessingRule,
    ProcessingDefaults,
    ProcessingSettingsWrite,
)
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService
from bisheng.permission.application.business_authorization import require_business_action

router = APIRouter(tags=["knowledge_processing"])


def get_processing_service():
    # These kinds have native handlers and same-transaction SQL Owners.
    # Move/copy kinds stay unavailable until their real assembly joins.
    return ProcessingJobService(
        owner=KnowledgeProcessingOwner(),
        available_kinds={"embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"},
    )


async def _write_scope(request, identity):
    scope = await resolve_management_scope(identity.user_id, is_super=identity.is_global_super, for_write=True)
    require_expected_management_tenant(request.headers.get("X-Management-Tenant"), scope)
    if scope.tenant_id != get_current_tenant_id():
        raise AdminScopeChangedError(scope_tenant_id=scope.tenant_id)


def _system_defaults(space_id):
    # The existing compatibility model resolves every current system default,
    # including separator and Excel rules; do not invent a second default set.
    legacy = FileProcessBase(knowledge_id=space_id)
    fields = DocumentProcessingRule.model_fields
    return ProcessingDefaults.model_validate(
        {"document": legacy.model_dump(include=set(fields)), "table": legacy.excel_rule.model_dump(mode="json")}
    )


@router.get("/{space_id}/processing-settings")
async def get_processing_settings(
    space_id: int = Path(gt=0), identity: UserPayload = Depends(UserPayload.get_login_user)
):
    await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
    async with get_async_db_session() as session:
        data = await ProcessingSettingsService(ProcessingSettingsRepository()).get_settings(
            session, space_id, system_defaults=_system_defaults(space_id)
        )
    return resp_200(data)


@router.put("/{space_id}/processing-settings")
async def update_processing_settings(
    change: ProcessingSettingsWrite,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
):
    await _write_scope(request, identity)
    await require_business_action(identity, resource_type="knowledge_space", resource_id=space_id, action="edit")
    async with get_async_db_session() as session:
        data = await ProcessingSettingsService(ProcessingSettingsRepository()).save_settings(
            session, space_id, change, system_defaults=_system_defaults(space_id)
        )
        await session.commit()
    return resp_200(data)


@router.post("/{space_id}/processing-jobs/precheck")
async def precheck_processing(
    change: ProcessingPrecheckRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    await _write_scope(request, identity)
    async with get_async_db_session() as session:
        data = await service.aprecheck(session, space_id, change, identity=identity, entry_kind="web")
        await session.commit()
    return resp_200(data)


@router.post("/{space_id}/processing-jobs")
async def create_processing_job(
    change: ProcessingCreateRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    await _write_scope(request, identity)
    async with get_async_db_session() as session:
        data = await service.acreate(session, space_id, change, identity=identity, entry_kind="web")
        await session.commit()
    return resp_200(data)


@router.get("/{space_id}/processing-jobs")
async def list_processing_jobs(
    space_id: int = Path(gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    kind: ProcessingKind | None = None,
    state: JobState | None = None,
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    async with get_async_db_session() as session:
        data = await service.alist(
            session, space_id, identity=identity, page=page, page_size=page_size, kind=kind, state=state
        )
    return resp_200(data)


@router.get("/{space_id}/processing-jobs/{job_id}")
async def get_processing_job(
    job_id: str,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    async with get_async_db_session() as session:
        data = await service.aget(session, space_id, job_id, identity=identity)
    return resp_200(data)


@router.get("/{space_id}/processing-jobs/{job_id}/items")
async def list_processing_items(
    job_id: str,
    space_id: int = Path(gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    state: ItemState | None = None,
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    async with get_async_db_session() as session:
        data = await service.alist_items(
            session, space_id, job_id, identity=identity, page=page, page_size=page_size, state=state
        )
    return resp_200(data)


@router.post("/{space_id}/processing-jobs/{job_id}/retry")
async def retry_processing_job(
    job_id: str,
    change: ProcessingRetryRequest,
    request: Request,
    space_id: int = Path(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    service: ProcessingJobService = Depends(get_processing_service),
):
    await _write_scope(request, identity)
    async with get_async_db_session() as session:
        outcome = await service.aretry(session, space_id, job_id, change, identity=identity, entry_kind="web")
        # Obsolescence is durable business state; report its error only after
        # committing the transaction, rather than rolling it back on raise.
        await session.commit()
    if outcome.error is not None:
        raise outcome.error
    return resp_200(outcome.data)
