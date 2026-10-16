"""Lazy saved-tool composition; Redis connection is owned by the app manager."""

from bisheng.dsh.domain.services.tools import ToolInvocationService


async def get_tool_service():
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.dsh.infrastructure.tool_leases import ToolLeases
    from bisheng.tool.domain.services.saved_tools import SavedToolService

    redis = (await get_redis_client()).async_connection
    return ToolInvocationService(SavedToolService(), ToolLeases(redis))
