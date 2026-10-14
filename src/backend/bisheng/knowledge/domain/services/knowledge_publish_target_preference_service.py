import json
import logging
from dataclasses import dataclass
from typing import Any

from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.repositories.implementations.knowledge_publish_target_preference_repository_impl import (
    KnowledgePublishTargetPreferenceRepositoryImpl,
)

logger = logging.getLogger(__name__)
_LINK_TYPES = {
    "personal": "publish_target_personal",
    "team": "publish_target_team",
    "team_ks": "publish_target_team",
    "department": "publish_target_department",
}


@dataclass(frozen=True)
class PublishTargetPreference:
    target_space_id: int
    target_folder_id: int | None


class KnowledgePublishTargetPreferenceService:
    @staticmethod
    def _link_type(source_level: KnowledgeSpaceLevelEnum | str) -> str:
        level = getattr(source_level, "value", source_level)
        if level not in _LINK_TYPES:
            raise ValueError("unsupported publish target preference group")
        return _LINK_TYPES[level]

    @staticmethod
    def _positive_id(value: Any) -> bool:
        return type(value) is int and value > 0

    async def get(self, *, user_id: int, source_level: KnowledgeSpaceLevelEnum | str) -> PublishTargetPreference | None:
        link_type = self._link_type(source_level)
        async with get_async_db_session() as session:
            detail = await KnowledgePublishTargetPreferenceRepositoryImpl(session).get_detail(
                user_id=user_id,
                link_type=link_type,
            )
        if detail is None:
            return None
        try:
            data = json.loads(detail)
            if (
                not isinstance(data, dict)
                or set(data) != {"v", "space", "folder"}
                or type(data["v"]) is not int
                or data["v"] != 1
                or not self._positive_id(data["space"])
                or (data["folder"] is not None and not self._positive_id(data["folder"]))
            ):
                raise ValueError("invalid publish preference payload")
            return PublishTargetPreference(data["space"], data["folder"])
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("invalid publish target preference user_id=%s type=%s", user_id, link_type)
            return None

    async def save(
        self,
        *,
        user_id: int,
        source_level: KnowledgeSpaceLevelEnum | str,
        target_space_id: int,
        target_folder_id: int | None,
    ) -> None:
        if (
            not self._positive_id(user_id)
            or not self._positive_id(target_space_id)
            or (target_folder_id is not None and not self._positive_id(target_folder_id))
        ):
            raise ValueError("invalid publish target preference ids")
        detail = json.dumps({"v": 1, "space": target_space_id, "folder": target_folder_id}, separators=(",", ":"))
        async with get_async_db_session() as session:
            await KnowledgePublishTargetPreferenceRepositoryImpl(session).save_detail(
                user_id=user_id,
                link_type=self._link_type(source_level),
                detail=detail,
            )
            await session.commit()
