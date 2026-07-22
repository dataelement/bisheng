from typing import Union

from sqlalchemy import and_, case, or_
from sqlmodel import Session, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_repository import KnowledgeRepository


class KnowledgeRepositoryImpl(BaseRepositoryImpl[Knowledge, int], KnowledgeRepository):
    """Knowledge Base Repository Implementation Class"""

    def __init__(self, session: Union[AsyncSession, Session]):
        super().__init__(session, Knowledge)

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
                KnowledgeSpaceScope.level.in_(
                    (
                        KnowledgeSpaceLevelEnum.PUBLIC.value,
                        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
                    )
                ),
            )
        )
        return [(row[0], row[1].value if hasattr(row[1], "value") else str(row[1])) for row in result.all()]
