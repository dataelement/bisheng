"""Authenticated invocation of existing saved tools without separate publication."""

import asyncio

from loguru import logger

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.schemas.tool_invocation import ToolLimits
from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.domain.services.tool_results import normalize_result


class ToolInvocationService:
    """Admission and result bounds; the caller owns the overall deadline."""

    def __init__(self, tools, leases, limits=None):
        self.tools, self.leases = tools, leases
        self.limits = limits if limits is not None else ToolLimits()

    async def invoke(self, principal, tool_key, arguments):
        tenant_id = int(principal.tenant_id)
        owner = None
        try:
            with principal_scope(principal), strict_tenant_filter():
                executor, arguments = await self.tools.prepare(
                    tenant_id, int(principal.user_id), tool_key, arguments, self.limits
                )
                owner = await self.leases.acquire(tenant_id, tool_key, self.limits.max_concurrency)
                raw = await self.tools.execute(executor, arguments)
                return {"tool": tool_key, "result": normalize_result(raw, self.limits.max_output_bytes)}
        finally:
            if owner is not None:
                await self._release(tenant_id, tool_key, owner)

    async def _release(self, tenant_id, tool_key, owner):
        try:
            # Shield so a cancelled request still frees its slot.
            await asyncio.shield(asyncio.wait_for(self.leases.release(tenant_id, tool_key, owner), timeout=2))
        except TimeoutError:
            # Best effort: the lease expires on its own deadline.
            logger.warning("Tool lease cleanup deadline tenant={} tool={}", tenant_id, tool_key)
