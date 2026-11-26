"""Business readiness before identity shortcuts; no public pending bypass."""

from bisheng.tool.domain.models.gpts_tools import assert_tool_ready
from bisheng.tool.domain.repositories.creation_repository import CreationRepository


async def require_creation_ready(tenant_id, resource_ids):
    for row in await CreationRepository.readiness_rows(resource_ids):
        assert_tool_ready(row)
