from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.repositories.interfaces.skill_repository import SkillRepository

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SkillRepositoryImpl(SkillRepository):
    """SQLModel implementation of the read-only skill lookups."""

    def __init__(self, session_factory: SessionFactory = get_async_db_session):
        self._session_factory = session_factory

    async def list_by_names(self, names: list[str]) -> list[LinsightSkill]:
        if not names:
            return []
        # Skills are tenant-private: strict mode drops the Root fallback that the
        # IN-list filter would otherwise add for a child tenant.
        with strict_tenant_filter():
            async with self._session_factory() as session:
                statement = select(LinsightSkill).where(col(LinsightSkill.name).in_(list(names)))
                result = await session.exec(statement)
                return list(result.all())
