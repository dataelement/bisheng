"""Saved-tool composition; Redis connection is owned by the app manager."""

from bisheng.dsh.domain.schemas.tool_invocation import ToolLimits
from bisheng.dsh.domain.services.tools import ToolInvocationService
from bisheng.dsh.infrastructure.tool_leases import ToolLeases


async def get_tool_service():
    # Deferred: the tool executor chain pulls in RAG/MCP/worker modules that the
    # DSH router must not load at import time.
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.tool.domain.services.saved_tools import SavedToolService

    limits = ToolLimits()
    redis = (await get_redis_client()).async_connection
    leases = ToolLeases(redis, lease_ms=(limits.timeout_seconds + 5) * 1000)
    return ToolInvocationService(SavedToolService(), leases, limits)
