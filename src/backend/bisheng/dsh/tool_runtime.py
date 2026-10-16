"""Lazy published-tool composition; Redis connection is owned by the app manager."""

from bisheng.dsh.domain.services.tool_publications import ToolPublicationService


async def get_tool_service():
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.dsh.domain.repositories.tool_publications import ToolPublicationRepository
    from bisheng.dsh.infrastructure.tool_leases import ToolLeases
    from bisheng.tool.domain.repositories.published_tools import PublishedToolRepository
    from bisheng.tool.domain.services.published_tools import PublishedToolService

    redis = (await get_redis_client()).async_connection
    return ToolPublicationService(
        ToolPublicationRepository(), PublishedToolService(PublishedToolRepository()), ToolLeases(redis)
    )
