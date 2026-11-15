"""Assistant admission through the explicitly composed source read runtime."""

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import get_async_db_session
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.source_access import get_reference_read_runtime
from bisheng.resource_reference.application.source_contracts import (
    SourceReadPurpose,
    SourceReadRequest,
    SourceReferenceReadResult,
)


class AssistantExecutionAdmission:
    @classmethod
    async def prepare(
        cls,
        identity: UserPayload,
        assistant_id: str,
        *,
        session: AsyncSession | None = None,
        purpose: SourceReadPurpose = "execute",
        inspect_token: str | None = None,
    ) -> SourceReferenceReadResult:
        request = SourceReadRequest(SourceType.ASSISTANT, assistant_id, "current", purpose, inspect_token)
        runtime = await get_reference_read_runtime()

        async def read(active):
            scope = await runtime.verifier.aissue_scope(active, request, identity)
            if purpose == "inspect":
                return await runtime.ainspect_source(active, scope, identity)
            return await runtime.arequire_source_valid(active, scope, identity)

        if session is not None:
            if not session.in_transaction():
                raise ResourceReferenceInvalidError(reason="assistant_read_transaction_required")
            return await read(session)
        async with get_async_db_session() as owned, owned.begin():
            return await read(owned)
