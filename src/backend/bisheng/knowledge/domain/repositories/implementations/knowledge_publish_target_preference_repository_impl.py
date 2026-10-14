from datetime import datetime

from sqlalchemy import Integer, column, table
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.user_link import UserLink
from bisheng.knowledge.domain.repositories.interfaces.knowledge_publish_target_preference_repository import (
    PUBLISH_TARGET_LINK_TYPES,
    KnowledgePublishTargetPreferenceRepository,
)

_USER_TABLE = table("user", column("user_id", Integer))


class KnowledgePublishTargetPreferenceRepositoryImpl(
    BaseRepositoryImpl[UserLink, int],
    KnowledgePublishTargetPreferenceRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, UserLink)

    @staticmethod
    def _validate_type(link_type: str) -> None:
        if link_type not in PUBLISH_TARGET_LINK_TYPES:
            raise ValueError("unsupported publish target preference type")

    async def _rows(self, user_id: int, link_type: str) -> list[UserLink]:
        self._validate_type(link_type)
        result = await self.session.exec(
            select(UserLink)
            .where(UserLink.user_id == user_id, UserLink.type == link_type)
            .order_by(UserLink.update_time.desc(), UserLink.id.desc())
        )
        return list(result.all())

    async def get_detail(self, *, user_id: int, link_type: str) -> str | None:
        rows = await self._rows(user_id, link_type)
        return rows[0].type_detail if rows else None

    async def save_detail(self, *, user_id: int, link_type: str, detail: str) -> None:
        self._validate_type(link_type)
        if len(detail) > 255:
            raise ValueError("publish target preference exceeds user_link capacity")
        # 唯一键包含内容, 须先锁用户, 串行化同账号首次插入及替换。
        user = await self.session.exec(
            select(_USER_TABLE.c.user_id).where(_USER_TABLE.c.user_id == user_id).with_for_update(),
        )
        if user.first() is None:
            raise ValueError("publish target preference user not found")
        rows = await self._rows(user_id, link_type)
        if rows:
            for duplicate in rows[1:]:
                await self.session.delete(duplicate)
            # 先移除重复内容, 避免更新最近记录时触发现有唯一约束。
            await self.session.flush()
            row = rows[0]
            row.type_detail = detail
            row.update_time = datetime.now()
        else:
            row = UserLink(user_id=user_id, type=link_type, type_detail=detail)
        self.session.add(row)
        await self.session.flush()
