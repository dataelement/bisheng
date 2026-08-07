from __future__ import annotations

import logging

from bisheng.common.constants.enums.knowledge_parse_priority import (
    KNOWLEDGE_PARSE_PRIORITY_CONFIG_KEY,
    KnowledgeParsePriority,
)
from bisheng.role.domain.repositories.interfaces.role_priority_repository import (
    RolePriorityRepository,
)

logger = logging.getLogger(__name__)


class KnowledgeParsePriorityService:
    """Resolve one user's effective parse priority in the active tenant."""

    def __init__(self, repository: RolePriorityRepository):
        self.repository = repository

    async def resolve(
        self,
        *,
        user_id: int | None,
        is_global_super: bool | None = None,
        file_id: int | None = None,
        tenant_id: int | None = None,
    ) -> KnowledgeParsePriority:
        if user_id is None:
            return KnowledgeParsePriority.LOW

        try:
            if is_global_super is None:
                from bisheng.utils.http_middleware import _check_is_global_super

                is_global_super = await _check_is_global_super(user_id)
            if is_global_super:
                return KnowledgeParsePriority.HIGH
            if not await self.repository.user_exists(user_id):
                return KnowledgeParsePriority.LOW

            configs = await self.repository.list_role_quota_configs(user_id)
            priorities = [
                KnowledgeParsePriority.parse(
                    (config or {}).get(KNOWLEDGE_PARSE_PRIORITY_CONFIG_KEY),
                    default=KnowledgeParsePriority.MEDIUM,
                )
                for config in configs
            ]
            if not priorities:
                return KnowledgeParsePriority.MEDIUM
            return max(priorities, key=lambda priority: priority.rank)
        except Exception:
            logger.exception(
                "knowledge parse priority resolution failed user_id=%s file_id=%s tenant_id=%s priority=low",
                user_id,
                file_id,
                tenant_id,
            )
            return KnowledgeParsePriority.LOW
