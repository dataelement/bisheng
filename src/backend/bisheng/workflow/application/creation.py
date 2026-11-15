"""Business readiness before identity shortcuts; no public pending bypass."""

from bisheng.database.models.flow import assert_workflow_ready
from bisheng.workflow.domain.repositories.creation_repository import CreationRepository


async def require_creation_ready(tenant_id, resource_ids):
    for row in await CreationRepository.readiness_rows(resource_ids):
        assert_workflow_ready(row)
