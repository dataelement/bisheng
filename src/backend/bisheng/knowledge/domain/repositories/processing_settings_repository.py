"""Tenant-scoped processing defaults; the owning use case owns the transaction."""

from copy import deepcopy
from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeProcessingSettingsConflictError
from bisheng.common.errcode.knowledge_space import SpaceNotFoundError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.schemas.processing_settings import ProcessingDefaults


@dataclass(frozen=True)
class ProcessingSettingsRecord:
    space_id: int
    config_version: int
    saved_defaults: dict | None


class ProcessingSettingsRepository:
    """No commit/rollback, no independent session and no historical file writes."""

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if type(tenant_id) is not int or tenant_id <= 0:
            raise RuntimeError("processing settings require a concrete tenant context")
        return tenant_id

    async def _load(self, session: AsyncSession, space_id: int, *, lock: bool) -> Knowledge:
        tenant_id = self._tenant_id()
        if type(space_id) is not int or space_id <= 0:
            raise SpaceNotFoundError()
        query = select(Knowledge).where(Knowledge.id == space_id, Knowledge.type == KnowledgeTypeEnum.SPACE.value)
        if lock:
            # Refresh an existing identity-map row with the current locking read.
            query = query.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            result = await session.exec(query)
        row = result.one_or_none()
        if row is None or row.tenant_id != tenant_id:
            raise SpaceNotFoundError()
        return row

    @staticmethod
    def _record(row: Knowledge) -> ProcessingSettingsRecord:
        return ProcessingSettingsRecord(
            space_id=row.id,
            config_version=row.processing_config_version,
            saved_defaults=deepcopy(row.processing_defaults),
        )

    async def aget(self, session: AsyncSession, space_id: int) -> ProcessingSettingsRecord:
        return self._record(await self._load(session, space_id, lock=False))

    async def areplace(
        self,
        session: AsyncSession,
        space_id: int,
        *,
        expected_config_version: int,
        defaults: ProcessingDefaults,
    ) -> ProcessingSettingsRecord:
        # Validate the complete replacement before touching a row. Revalidation
        # also catches invalid internal model_copy/model_construct inputs.
        canonical = ProcessingDefaults.model_validate(defaults.model_dump(mode="json")).model_dump(mode="json")
        row = await self._load(session, space_id, lock=True)
        if type(expected_config_version) is not int or row.processing_config_version != expected_config_version:
            raise KnowledgeProcessingSettingsConflictError()
        row.processing_defaults = canonical
        row.processing_config_version += 1
        session.add(row)
        await session.flush()
        return self._record(row)
