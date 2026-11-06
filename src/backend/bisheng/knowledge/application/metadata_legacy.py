"""Original metadata protocols composed with the native schema/J1 operation."""

from uuid import uuid4

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.processing_owner import KnowledgeProcessingOwner
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest, ProcessingPrecheckRequest
from bisheng.knowledge.domain.services.knowledge_metadata_service import KnowledgeMetadataService
from bisheng.knowledge.domain.services.knowledge_permission_service import KnowledgePermissionService
from bisheng.knowledge.domain.services.processing_job_service import ProcessingJobService
from bisheng.open_api.application.access_context import get_current_open_api_principal


class LegacyMetadataWriter:
    async def achange(self, login_user, space_id, changes):
        principal = get_current_open_api_principal()
        identity = principal if principal is not None else login_user
        entry_kind = "open_api" if principal is not None else "web"
        owner = KnowledgeProcessingOwner()
        service = ProcessingJobService(owner=owner, available_kinds={"metadata_schema_change"})
        async with get_async_db_session() as session:
            await session.begin()
            current = await owner.metadata.execution.aread_configuration(session, space_id)
            plan = await service.aprecheck(
                session,
                space_id,
                ProcessingPrecheckRequest(
                    kind="metadata_schema_change",
                    parameters={"expected_schema_revision": current.metadata_schema_revision, "changes": changes},
                ),
                identity=identity,
                entry_kind=entry_kind,
            )
            result = await service.acreate(
                session,
                space_id,
                ProcessingCreateRequest(
                    idempotency_key=str(uuid4()), confirmation_id=plan.confirmation_id, plan_digest=plan.plan_digest
                ),
                identity=identity,
                entry_kind=entry_kind,
            )
            row = await KnowledgeModelReferenceRepository().aget(session, space_id)
            response = {
                **row.model_dump(),
                "processing_job": {
                    "job_id": result.job_id,
                    "state": result.state,
                    "accepted": True,
                    "completed": result.state == "succeeded",
                },
            }
            await session.commit()
            return response


def build_legacy_metadata_service(*, knowledge_repository, knowledge_file_repository, permission_service=None):
    return KnowledgeMetadataService(
        knowledge_repository=knowledge_repository,
        knowledge_file_repository=knowledge_file_repository,
        permission_service=permission_service if permission_service is not None else KnowledgePermissionService(),
        space_writer=LegacyMetadataWriter(),
    )
