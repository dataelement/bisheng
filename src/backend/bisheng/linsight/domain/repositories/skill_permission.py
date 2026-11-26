"""Tenant-scoped persistence for skill permission targets."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, strict_tenant_filter


class SkillPermissionRepository:
    async def get(self, skill_id: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(LinsightSkill).where(LinsightSkill.id == skill_id))).first()

    @asynccontextmanager
    async def lock(self, skill_id: int, *, tenant_id: int) -> AsyncIterator[LinsightSkill | None]:
        """Serialize a skill's bootstrap across processes, including F048 I/O."""
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            async with get_async_db_session() as session:
                row = (
                    await session.exec(select(LinsightSkill).where(LinsightSkill.id == skill_id).with_for_update())
                ).first()
                yield row
