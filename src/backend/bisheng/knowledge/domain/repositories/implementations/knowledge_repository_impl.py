from typing import Union

from sqlalchemy import and_, case, func, or_
from sqlmodel import Session, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository


class KnowledgeRepositoryImpl(BaseRepositoryImpl[Knowledge, int], KnowledgeRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: Union[AsyncSession, Session]):
        super().__init__(session, Knowledge)

    async def find_retiring_spaces(self, *, after_id: int, limit: int) -> list[Knowledge]:
        result = await self.session.execute(
            select(Knowledge)
            .where(Knowledge.state == KnowledgeState.DELETING.value, Knowledge.id > after_id)
            .order_by(Knowledge.id.asc()).limit(limit)
        )
        return list(result.scalars().all())

    async def personal_space_name_exists_globally(self, name: str) -> bool:
        statement = (
            select(Knowledge.id)
            .outerjoin(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                func.trim(Knowledge.name) == name.strip(),
                or_(
                    KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value,
                    KnowledgeSpaceScope.space_id.is_(None),
                ),
            )
            .limit(1)
        )
        # 仅名称占用查询跨租户, 既不返回其他人员信息, 也不改变后续写入上下文。
        with bypass_tenant_filter():
            result = await self.session.execute(statement)
            return result.first() is not None

    async def find_personal_default_space_by_owner(self, owner_id: int) -> Knowledge | None:
        result = await self.session.execute(
            select(Knowledge)
            .join(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.user_id == owner_id,
                Knowledge.is_favorite == False,  # noqa: E712
                Knowledge.name != "我的收藏",
                KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PERSONAL.value,
                KnowledgeSpaceScope.owner_type == "user",
                KnowledgeSpaceScope.owner_id == owner_id,
            )
            .order_by(Knowledge.id.asc())
            .limit(1)
        )
        return result.scalars().first()

    async def find_file_sync_spaces(
        self,
        *,
        allowed_space_ids: set[int] | None,
        keyword: str | None,
        after: tuple[int, str, int] | None,
        limit: int,
    ) -> list[tuple[Knowledge, str]]:
        if allowed_space_ids is not None and not allowed_space_ids:
            return []
        level_order = case(
            (KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PUBLIC.value, 0),
            else_=1,
        )
        stmt = (
            select(Knowledge, KnowledgeSpaceScope.level)
            .join(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.state == KnowledgeState.PUBLISHED.value,
                KnowledgeSpaceScope.level.in_(
                    (
                        KnowledgeSpaceLevelEnum.PUBLIC.value,
                        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
                    )
                ),
            )
        )
        if allowed_space_ids is not None:
            stmt = stmt.where(col(Knowledge.id).in_(allowed_space_ids))
        if keyword:
            stmt = stmt.where(Knowledge.name.contains(keyword, autoescape=True))
        if after is not None:
            after_level, after_name, after_id = after
            stmt = stmt.where(
                or_(
                    level_order > after_level,
                    and_(
                        level_order == after_level,
                        Knowledge.name > after_name,
                    ),
                    and_(
                        level_order == after_level,
                        Knowledge.name == after_name,
                        Knowledge.id > after_id,
                    ),
                )
            )
        result = await self.session.execute(
            stmt.order_by(
                level_order.asc(),
                Knowledge.name.asc(),
                Knowledge.id.asc(),
            ).limit(limit)
        )
        return [(row[0], row[1].value if hasattr(row[1], "value") else str(row[1])) for row in result.all()]

    async def find_file_sync_spaces_by_ids(
        self,
        space_ids: set[int],
    ) -> list[tuple[Knowledge, str]]:
        if not space_ids:
            return []
        result = await self.session.execute(
            select(Knowledge, KnowledgeSpaceScope.level)
            .join(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
            .where(
                col(Knowledge.id).in_(space_ids),
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.state == KnowledgeState.PUBLISHED.value,
                KnowledgeSpaceScope.level.in_(
                    (
                        KnowledgeSpaceLevelEnum.PUBLIC.value,
                        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
                    )
                ),
            )
        )
        return [(row[0], row[1].value if hasattr(row[1], "value") else str(row[1])) for row in result.all()]

    async def find_space_by_id(self, space_id: int) -> Knowledge | None:
        result = await self.session.execute(
            select(Knowledge).where(
                Knowledge.id == space_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            )
        )
        return result.scalar_one_or_none()

    async def find_qa_spaces_by_ids(self, space_ids: list[int]) -> list[tuple[Knowledge, str | None]]:
        rows = []
        ids = sorted(set(space_ids))
        for start in range(0, len(ids), 500):
            result = await self.session.execute(
                select(Knowledge, KnowledgeSpaceScope.level)
                .outerjoin(KnowledgeSpaceScope, Knowledge.id == KnowledgeSpaceScope.space_id)
                .where(col(Knowledge.id).in_(ids[start:start + 500]),
                       Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                       Knowledge.state != KnowledgeState.DELETING.value))
            rows.extend((row[0], getattr(row[1], "value", row[1])) for row in result.all())
        return rows
