from sqlalchemy import Integer, column, delete, table
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.database.models.user_link import UserLink
from bisheng.knowledge.domain.repositories.interfaces.knowledge_space_pin_repository import (
    KnowledgeSpacePinRepository,
)

KNOWLEDGE_SPACE_PIN_TYPE = "knowledge_space_pin"
_USER_TABLE = table("user", column("user_id", Integer))


class KnowledgeSpacePinRepositoryImpl(BaseRepositoryImpl[UserLink, int], KnowledgeSpacePinRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session, UserLink)

    async def lock_user(self, user_id: int) -> None:
        await self.session.exec(select(_USER_TABLE.c.user_id).where(_USER_TABLE.c.user_id == user_id).with_for_update())

    async def list_for_user(self, user_id: int) -> set[int]:
        result = await self.session.exec(
            select(UserLink.type_detail).where(
                UserLink.user_id == user_id,
                UserLink.type == KNOWLEDGE_SPACE_PIN_TYPE,
            )
        )
        return {int(type_detail) for type_detail in result.all() if str(type_detail).isdigit()}

    async def add_pin(self, user_id: int, space_id: int) -> bool:
        existing = await self.session.exec(
            select(UserLink.id).where(
                UserLink.user_id == user_id,
                UserLink.type == KNOWLEDGE_SPACE_PIN_TYPE,
                UserLink.type_detail == str(space_id),
            )
        )
        if existing.first() is not None:
            return False
        self.session.add(UserLink(user_id=user_id, type=KNOWLEDGE_SPACE_PIN_TYPE, type_detail=str(space_id)))
        await self.session.flush()
        return True

    async def remove_pin(self, user_id: int, space_id: int) -> bool:
        result = await self.session.exec(
            delete(UserLink).where(
                UserLink.user_id == user_id,
                UserLink.type == KNOWLEDGE_SPACE_PIN_TYPE,
                UserLink.type_detail == str(space_id),
            )
        )
        return bool(result.rowcount)

    async def delete_by_space_id(self, space_id: int) -> int:
        result = await self.session.exec(
            delete(UserLink).where(
                UserLink.type == KNOWLEDGE_SPACE_PIN_TYPE,
                UserLink.type_detail == str(space_id),
            )
        )
        return int(result.rowcount or 0)
