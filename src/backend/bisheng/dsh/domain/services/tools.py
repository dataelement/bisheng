"""Authenticated invocation of existing saved tools without separate publication."""

import asyncio

from loguru import logger

from bisheng.common.errcode.dsh import DshToolExecutionTimeoutError, DshToolInputTooLargeError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.schemas.tool_invocation import ToolLimits
from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.domain.services.tool_results import normalize_result


class ToolInvocationService:
    def __init__(self, tools, leases, limits=None):
        self.tools, self.leases = tools, leases
        self.limits = limits if limits is not None else ToolLimits()

    async def invoke(self, principal, tool_key, arguments, input_bytes, started_at=None):
        tenant_id = int(principal.tenant_id)
        started_at = asyncio.get_running_loop().time() if started_at is None else started_at
        owner = None
        try:
            async with asyncio.timeout_at(started_at + self.limits.timeout_seconds):
                with principal_scope(principal), strict_tenant_filter():
                    if input_bytes > self.limits.max_input_bytes:
                        raise DshToolInputTooLargeError()
                    executor, arguments = await self.tools.prepare(
                        tenant_id, int(principal.user_id), tool_key, arguments, self.limits
                    )
                    owner = await self.leases.acquire(tenant_id, tool_key, self.limits.max_concurrency)
                    raw = await self.tools.execute(executor, arguments)
                    return {"tool": tool_key, "result": normalize_result(raw, self.limits.max_output_bytes)}
        except TimeoutError:
            raise DshToolExecutionTimeoutError() from None
        finally:
            if owner is not None:
                try:
                    await asyncio.shield(asyncio.wait_for(self.leases.release(tenant_id, tool_key, owner), timeout=2))
                except TimeoutError:
                    # Cleanup is best effort; the owner lease expires after 65 seconds.
                    logger.warning("Tool lease cleanup deadline tenant={} tool={}", tenant_id, tool_key)
