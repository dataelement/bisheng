from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.repositories.implementations.department_space_binding_repository_impl import (
    DepartmentSpaceBindingRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_similarity_candidate_repository_impl import (
    KnowledgeFileSimilarityCandidateRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_repository import (
    KnowledgeDocumentRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_document_version_repository import (
    KnowledgeDocumentVersionRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import KnowledgeFileRepository
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_similarity_candidate_repository import (
    KnowledgeFileSimilarityCandidateRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository
from bisheng.knowledge.domain.repositories.interfaces.department_file_view_grant_repository import (
    DepartmentFileViewGrantRepository,
)
from bisheng.knowledge.domain.services.knowledge_audit_telemetry_service import KnowledgeAuditTelemetryService
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.department_file_view_lifecycle_service import (
    DepartmentFileViewLifecycleService,
)
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.message.api.dependencies import get_message_service as _get_message_service

# Service imports are deferred to avoid circular imports
if TYPE_CHECKING:
    from bisheng.knowledge.domain.services.knowledge_file_service import KnowledgeFileService
    from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService
    from bisheng.knowledge.domain.services.portal_pdf_download_service import PortalPdfDownloadService


async def get_knowledge_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeRepository:
    """DapatkanKnowledgeRepositoryInstance Dependencies"""
    return KnowledgeRepositoryImpl(session)


async def get_knowledge_file_repository(
    session: AsyncSession = Depends(get_db_session),
) -> "KnowledgeFileRepository":
    """DapatkanKnowledgeFileRepositoryInstance Dependencies"""

    return KnowledgeFileRepositoryImpl(session)


async def get_department_file_view_grant_repository(
    session: AsyncSession = Depends(get_db_session),
) -> DepartmentFileViewGrantRepository:
    return DepartmentFileViewGrantRepositoryImpl(session)


async def get_department_file_view_access_service(
    session: AsyncSession = Depends(get_db_session),
    grant_repository: DepartmentFileViewGrantRepository = Depends(
        get_department_file_view_grant_repository
    ),
) -> DepartmentFileViewAccessService:
    return DepartmentFileViewAccessService(
        session=session,
        grant_repository=grant_repository,
        persist_stale_grant_revalidation=True,
    )


async def get_knowledge_document_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeDocumentRepository:
    return KnowledgeDocumentRepositoryImpl(session)


async def get_knowledge_document_version_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeDocumentVersionRepository:
    return KnowledgeDocumentVersionRepositoryImpl(session)


async def get_knowledge_file_similarity_candidate_repository(
    session: AsyncSession = Depends(get_db_session),
) -> KnowledgeFileSimilarityCandidateRepository:
    return KnowledgeFileSimilarityCandidateRepositoryImpl(session)


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
) -> "KnowledgeService":
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
) -> "KnowledgeFileService":
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
    similar_candidate_repo: KnowledgeFileSimilarityCandidateRepository = Depends(
        get_knowledge_file_similarity_candidate_repository
    ),
    department_file_view_access_service: DepartmentFileViewAccessService = Depends(
        get_department_file_view_access_service
    ),
) -> "KnowledgeSpaceService":
    """Get KnowledgeSpaceService instance, bound to the current request and login user"""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService as _SvcClass

    message_service = await _get_message_service(session)
    service = _SvcClass(request=request, login_user=login_user)
    service.department_space_binding_repo = DepartmentSpaceBindingRepositoryImpl(session)
    service.message_service = message_service
    service.version_repo = version_repo
    service.doc_repo = doc_repo
    service.similar_candidate_repo = similar_candidate_repo
    service.department_file_view_access_service = department_file_view_access_service
    service.department_file_view_lifecycle_service = (
        DepartmentFileViewLifecycleService(
            session=session,
            file_repository=KnowledgeFileRepositoryImpl(session),
            grant_repository=department_file_view_access_service.grant_repository,
        )
    )
    return service


async def get_portal_pdf_download_service(
    file_repository: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
    authorization_service: "KnowledgeSpaceService" = Depends(get_knowledge_space_service),
    session: AsyncSession = Depends(get_db_session),
) -> "PortalPdfDownloadService":
    from bisheng.common.services.config_service import settings
    from bisheng.core.storage.minio.minio_manager import get_minio_storage
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_pdf_artifact_repository_impl import (
        KnowledgeFilePdfArtifactRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_pdf_artifact_service import (
        KnowledgePdfArtifactService,
        get_available_pdf_artifact_reference,
    )
    from bisheng.knowledge.domain.services.pdf_artifact_generation_service import (
        process_pdf_artifact_on_demand,
    )
    from bisheng.knowledge.domain.services.pdf_artifact_on_demand_service import (
        PdfArtifactGenerationLock,
        PdfArtifactOnDemandService,
    )
    from bisheng.knowledge.domain.services.portal_pdf_download_service import (
        PortalPdfDownloadService,
        PortalPdfDownloadUserLock,
    )
    from bisheng.knowledge.domain.services.portal_share_download_grant_service import (
        PortalShareDownloadGrantService,
    )
    from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl
    knowledge_config = await settings.async_get_knowledge()
    artifact_service = KnowledgePdfArtifactService(
        repository=KnowledgeFilePdfArtifactRepositoryImpl(session),
        config=knowledge_config.pdf_artifact,
    )
    on_demand_service = PdfArtifactOnDemandService(
        artifact_service=artifact_service,
        artifact_accessor=get_available_pdf_artifact_reference,
        generation_runner=process_pdf_artifact_on_demand,
        generation_lock=PdfArtifactGenerationLock(),
        config=knowledge_config.pdf_artifact,
    )
    return PortalPdfDownloadService(
        config=knowledge_config.pdf_watermark,
        file_repository=file_repository,
        user_repository=UserRepositoryImpl(session),
        authorization_service=authorization_service,
        artifact_ensurer=on_demand_service.ensure_available,
        artifact_readiness_timeout_seconds=knowledge_config.pdf_artifact.on_demand_timeout_seconds,
        storage=await get_minio_storage(),
        share_grant_service=PortalShareDownloadGrantService(secret=settings.jwt_secret),
        user_lock=PortalPdfDownloadUserLock(),
    )


async def get_knowledge_space_chat_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
    department_file_view_access_service: DepartmentFileViewAccessService = Depends(
        get_department_file_view_access_service
    ),
) -> "KnowledgeSpaceChatService":
    """Get KnowledgeSpaceChatService instance, bound to the current request and login user."""
    from bisheng.knowledge.domain.services.knowledge_space_chat_service import KnowledgeSpaceChatService as _SvcClass

    service = _SvcClass(request=request, login_user=login_user)
    service.version_repo = version_repo
    service.department_file_view_access_service = (
        department_file_view_access_service
    )
    return service


async def get_knowledge_version_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    doc_repo: KnowledgeDocumentRepository = Depends(get_knowledge_document_repository),
    version_repo: KnowledgeDocumentVersionRepository = Depends(get_knowledge_document_version_repository),
    knowledge_file_repo: KnowledgeFileRepository = Depends(get_knowledge_file_repository),
    similar_candidate_repo: KnowledgeFileSimilarityCandidateRepository = Depends(
        get_knowledge_file_similarity_candidate_repository
    ),
) -> "KnowledgeVersionService":
    """Get KnowledgeVersionService instance, bound to the current request and login user."""
    from bisheng.knowledge.domain.services.knowledge_version_service import KnowledgeVersionService

    service = KnowledgeVersionService(
        request=request,
        login_user=login_user,
        doc_repo=doc_repo,
        version_repo=version_repo,
        knowledge_file_repo=knowledge_file_repo,
        similar_candidate_repo=similar_candidate_repo,
    )
    # 版本关联变更时给收藏了受影响文件的用户发站内信，需要 message_service。
    service.message_service = await _get_message_service(session)
    return service
