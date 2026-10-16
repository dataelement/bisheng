"""Management and invocation of tenant-qualified published saved tools."""

import asyncio

from loguru import logger

from bisheng.common.errcode.dsh import (
    DshToolArgumentsInvalidError,
    DshToolExecutionTimeoutError,
    DshToolInputTooLargeError,
    DshToolPublicationNotFoundError,
)
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.dsh.domain.schemas.tool_publications import ToolPublication
from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.domain.services.tool_results import normalize_result


def search_arguments(code, arguments):
    if code != "bs_web_search":
        return arguments
    query = arguments.get("query")
    if type(query) is not str or not 1 <= len(query.strip()) <= 4096:
        raise DshToolArgumentsInvalidError()
    count = arguments.get("maxResults", 20)
    if type(count) is not int or not 1 <= count <= 20:
        raise DshToolArgumentsInvalidError()
    return {**arguments, "query": query.strip()}


class ToolPublicationService:
    def __init__(self, repository, tools, leases):
        self.repository, self.tools, self.leases = repository, tools, leases

    @staticmethod
    def management_tenant(user):
        # Tenant admin authentication has already verified the browser actor.
        tenant_id = get_current_tenant_id()
        if not tenant_id or (not user.is_global_super and tenant_id != user.tenant_id):
            raise DshToolPublicationNotFoundError()
        return tenant_id

    async def list(self, user, offset=0, limit=50):
        tenant_id = self.management_tenant(user)
        result = []
        with strict_tenant_filter():
            items, total = await self.repository.list(tenant_id, offset, limit)
            for item in items:
                await self.tools.verify(tenant_id, item.tool_id, user, "edit")
                result.append(item)
        return {"data": result, "total": total}

    async def get(self, user, code):
        tenant_id = self.management_tenant(user)
        with strict_tenant_filter():
            async with self.repository.locked(tenant_id, code) as record:
                if record.publication is None:
                    raise DshToolPublicationNotFoundError()
                await self.tools.verify(tenant_id, record.publication.tool_id, user, "edit")
                return record.publication

    async def put(self, user, code, body):
        tenant_id = self.management_tenant(user)
        initial = ToolPublication(**body.model_dump(), tool_code=code, revision=1)
        with strict_tenant_filter():
            await self.tools.verify(tenant_id, body.tool_id, user, "edit", code)
            async with self.repository.locked(tenant_id, code, initial=initial) as record:
                old = record.publication
                if not record.created:
                    await self.tools.verify(tenant_id, old.tool_id, user, "edit")
                await self.tools.verify(tenant_id, body.tool_id, user, "edit", code)
                if record.created:
                    await self.leases.initialize(tenant_id, code)
                record.publication = initial.model_copy(update={"revision": 1 if record.created else old.revision + 1})
                return record.publication

    async def invoke(self, principal, code, arguments, input_bytes, started_at=None):
        tenant_id = int(principal.tenant_id)
        started_at = asyncio.get_running_loop().time() if started_at is None else started_at
        owner = None
        try:
            # The hard deadline also bounds SQL admission and permission checks.
            async with asyncio.timeout_at(started_at + 60) as deadline:
                with principal_scope(principal), strict_tenant_filter():
                    async with self.repository.locked(tenant_id, code) as record:
                        publication = record.publication
                        if publication is None or not publication.enabled:
                            raise DshToolPublicationNotFoundError()
                        deadline.reschedule(started_at + publication.limits.timeout_seconds)
                        if input_bytes > publication.limits.max_input_bytes:
                            raise DshToolInputTooLargeError()
                        arguments = search_arguments(code, arguments)
                        executor, arguments = await self.tools.prepare(
                            tenant_id, int(principal.user_id), publication, arguments
                        )
                        # Admission and disabling serialize on the same SQL row.
                        owner = await self.leases.acquire(tenant_id, code, publication.limits.max_concurrency)
                    raw = await self.tools.execute(executor, arguments)
                    result = normalize_result(
                        code, raw, publication.limits.max_output_bytes, arguments.get("maxResults", 20)
                    )
                    return {"tool": code, "result": result}
        except TimeoutError:
            raise DshToolExecutionTimeoutError() from None
        finally:
            if owner is not None:
                try:
                    await asyncio.shield(asyncio.wait_for(self.leases.release(tenant_id, code, owner), timeout=2))
                except TimeoutError:
                    # Cleanup is best effort; the owner lease expires after 65 seconds.
                    logger.warning("Published tool lease cleanup deadline tenant={} tool={}", tenant_id, code)

    async def preflight(self, principal, code):
        with principal_scope(principal), strict_tenant_filter():
            async with self.repository.locked(int(principal.tenant_id), code) as record:
                if record.publication is None or not record.publication.enabled:
                    raise DshToolPublicationNotFoundError()
                return record.publication.limits
