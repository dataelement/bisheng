"""Tenant-scoped persistence for skill permission targets."""

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill, strict_tenant_filter


class SkillPermissionRepository:
    async def get(self, skill_id: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(LinsightSkill).where(LinsightSkill.id == skill_id))).first()
