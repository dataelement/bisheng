from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.api.dependencies import get_approval_submission_port
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import KnowledgeAuditTelemetryService
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.message.api.dependencies import get_message_service as _get_message_service

# Service imports are deferred to avoid circular imports
if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
        KnowledgeFileVisibilityService,
    )
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService


async def get_knowledge_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """DapatkanKnowledgeRepositoryInstance Dependencies"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'KnowledgeFileRepository':
    """DapatkanKnowledgeFileRepositoryInstance Dependencies"""

    return KnowledgeFileRepositoryImpl(session)


async def get_knowledge_document_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeDocumentRepository:
    return KnowledgeDocumentRepositoryImpl(session)


async def get_knowledge_document_version_repository(
        session: AsyncSession = Depends(get_db_session),
) -> KnowledgeDocumentVersionRepository:
    return KnowledgeDocumentVersionRepositoryImpl(session)


async def get_knowledge_metadata_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
        permission_service: KnowledgePermissionService = Depends(KnowledgePermissionService),
) -> KnowledgeMetadataService:
    return KnowledgeMetadataService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
        permission_service=permission_service,
    )


async def get_knowledge_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
        permission_service: KnowledgePermissionService = Depends(KnowledgePermissionService),
        audit_telemetry_service: KnowledgeAuditTelemetryService = Depends(KnowledgeAuditTelemetryService),
        metadata_service: KnowledgeMetadataService = Depends(get_knowledge_metadata_service),
) -> 'KnowledgeService':
    """DapatkanKnowledgeServiceInstance Dependencies"""
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService as _KnowledgeService
    return _KnowledgeService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
        permission_service=permission_service,
        audit_telemetry_service=audit_telemetry_service,
        metadata_service=metadata_service,
    )


async def get_knowledge_file_service(
        knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
        knowledge_file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeFileService':
    """DapatkanKnowledgeFileServiceInstance Dependencies"""
    from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService as _KnowledgeFileService
    return _KnowledgeFileService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
    )


async def get_knowledge_space_service(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
) -> 'KnowledgeSpaceService':
    """Get KnowledgeSpaceService instance, bound to the current request and login user"""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService as _SvcClass
    from bisheng.permission.application.access import get_f048_runtime
    from bisheng.permission.application.initial_grant import InitialGrantApplication
    from bisheng.permission.application.prospective_grant import ProspectiveGrantApplication
    from bisheng.tenant.domain.services.f048_permission_subject import TenantPermissionSubjectDirectory

    message_service = await _get_message_service(session)
    runtime = await get_f048_runtime()
    subject_directory = TenantPermissionSubjectDirectory()
    service = _SvcClass(
        request=request,
        login_user=login_user,
        initial_grant_application=InitialGrantApplication(
            runtime=runtime,
            subjects=subject_directory,
        ),
        prospective_grant_application=ProspectiveGrantApplication(
            runtime=runtime,
            subjects=subject_directory,
        ),
    )
    service.message_service = message_service
    service.version_repo = version_repo
    service.doc_repo = doc_repo
    return service


async def get_knowledge_space_upload_stage_service(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Compose opaque upload staging with authoritative user and tenant quotas."""
    from bisheng.knowledge.domain.repositories.knowledge_space_mutation_repository import (
        KnowledgeSpaceMutationRepository,
    )
    from bisheng.knowledge.domain.services.knowledge_space_upload_stage_service import (
        KnowledgeSpaceUploadCapacity,
        KnowledgeSpaceUploadStageService,
    )
    from bisheng.role.domain.services.quota_service import QuotaService

    async def load_capacity(tenant_id: int, uploader_user_id: int) -> KnowledgeSpaceUploadCapacity:
        user_limit = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
        async with get_async_db_session() as session:
            user_used = await KnowledgeSpaceMutationRepository(session).get_user_uploaded_file_size(
                tenant_id=tenant_id,
                user_id=uploader_user_id,
            )
        tenant_used = await QuotaService.get_tenant_storage_used_bytes(tenant_id)
        tenant_remaining = await QuotaService.get_tenant_storage_remaining_bytes(tenant_id)
        return KnowledgeSpaceUploadCapacity(
            user_used_bytes=user_used,
            user_limit_bytes=user_limit,
            tenant_used_bytes=tenant_used,
            tenant_limit_bytes=(tenant_used + tenant_remaining) if tenant_remaining is not None else None,
        )

    return KnowledgeSpaceUploadStageService(
        storage=await get_minio_storage(),
        capacity_loader=load_capacity,
    )


async def get_knowledge_space_file_change_service(
    owner_service: "KnowledgeSpaceService" = Depends(get_knowledge_space_service),
    stage_service=Depends(get_knowledge_space_upload_stage_service),
    submission_port=Depends(get_approval_submission_port),
):
    """Compose F046 with real permission, footprint, executor and notification owners."""
    from bisheng.knowledge.domain.services.knowledge_space_file_change_service import (
        KnowledgeSpaceFileChangeService,
    )

    async def execute_direct(command):
        return await owner_service.execute_direct_file_change(command, stage_service=stage_service)

    return KnowledgeSpaceFileChangeService(
        session_factory=get_async_db_session,
        submission_port=submission_port,
        mutation_authorizer=owner_service.authorize_file_change,
        footprint_resolver=owner_service.resolve_file_change_footprints,
        direct_executor=execute_direct,
        stage_retainer=stage_service.retain_bound_stage,
    )
async def get_knowledge_space_chat_service(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
) -> 'KnowledgeSpaceChatService':
    """Get KnowledgeSpaceChatService instance, bound to the current request and login user."""
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService as _SvcClass
    service = _SvcClass(request=request, login_user=login_user)
    service.version_repo = version_repo
    return service


async def get_knowledge_file_visibility_service(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
) -> 'KnowledgeFileVisibilityService':
    """Get KnowledgeFileVisibilityService instance (F029).

    Bound to the current request and login user; shared by chat_folder,
    queryChunksFromDB and CitationResolveService for view_file filtering.
    """
    from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
        KnowledgeFileVisibilityService as _SvcClass,
    )
    service = _SvcClass(request=request, login_user=login_user)
    service.version_repo = version_repo
    return service


async def get_knowledge_version_service(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
        version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
        knowledge_file_repo: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
) -> 'KnowledgeVersionService':
    """Get KnowledgeVersionService instance, bound to the current request and login user."""
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
    return KnowledgeVersionService(
        request=request,
        login_user=login_user,
        doc_repo=doc_repo,
        version_repo=version_repo,
        knowledge_file_repo=knowledge_file_repo,
    )
