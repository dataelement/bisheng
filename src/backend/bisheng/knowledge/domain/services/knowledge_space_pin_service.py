from typing import Any

from bisheng.common.errcode.knowledge_space import SpacePinLimitError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_space_pin_repository_impl import (
    KnowledgeSpacePinRepositoryImpl,
)

KNOWLEDGE_SPACE_PIN_TYPE = "knowledge_space_pin"
MAX_PINS_PER_LEVEL = 5


class KnowledgeSpacePinService:
    @staticmethod
    async def list_pinned_space_ids(user_id: int, visible_space_ids: set[int]) -> list[int]:
        """Pinned space ids visible to the user, most recently pinned first."""
        if not visible_space_ids:
            return []
        async with get_async_db_session() as session:
            pinned_ids = await KnowledgeSpacePinRepositoryImpl(session).list_for_user(user_id)
        return [space_id for space_id in pinned_ids if space_id in visible_space_ids]

    @staticmethod
    async def get_pinned_space_ids(user_id: int, visible_space_ids: set[int]) -> set[int]:
        return set(await KnowledgeSpacePinService.list_pinned_space_ids(user_id, visible_space_ids))

    @classmethod
    async def set_pin(
        cls,
        *,
        user_id: int,
        space_id: int,
        visible_space_ids: set[int],
        is_pinned: bool,
    ) -> bool:
        async with get_async_db_session() as session:
            repository = KnowledgeSpacePinRepositoryImpl(session)
            await repository.lock_user(user_id)
            pinned_ids = await repository.list_for_user(user_id)
            current_ids = [item for item in pinned_ids if item in visible_space_ids]
            if not is_pinned:
                await repository.remove_pin(user_id, space_id)
                await session.commit()
                return True
            if space_id in current_ids:
                return True
            if len(current_ids) >= MAX_PINS_PER_LEVEL:
                raise SpacePinLimitError()
            await repository.add_pin(user_id, space_id)
            await session.commit()
            return True

    @classmethod
    async def apply_pins(cls, spaces: list[Any], user_id: int) -> list[Any]:
        if not spaces:
            return spaces
        visible_ids = {
            int(item.get("id") if isinstance(item, dict) else item.id)
            for item in spaces
            if (item.get("id") if isinstance(item, dict) else getattr(item, "id", None)) is not None
        }
        pinned_order = await cls.list_pinned_space_ids(user_id, visible_ids)
        pin_rank = {space_id: index for index, space_id in enumerate(pinned_order)}
        pinned: list[Any] = []
        normal: list[Any] = []
        for item in spaces:
            item_id = int(item.get("id") if isinstance(item, dict) else item.id)
            level = item.get("space_level") if isinstance(item, dict) else getattr(item, "space_level", None)
            level_value = getattr(level, "value", level)
            is_pinned = level_value != KnowledgeSpaceLevelEnum.PERSONAL.value and item_id in pin_rank
            if isinstance(item, dict):
                item["is_pinned"] = is_pinned
            else:
                item.is_pinned = is_pinned
            (pinned if is_pinned else normal).append(item)
        pinned.sort(key=lambda item: pin_rank[int(item.get("id") if isinstance(item, dict) else item.id)])
        return pinned + normal

    @staticmethod
    async def delete_space_pins(space_id: int) -> int:
        async with get_async_db_session() as session:
            count = await KnowledgeSpacePinRepositoryImpl(session).delete_by_space_id(space_id)
            await session.commit()
            return count
