from __future__ import annotations

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority
from bisheng.common.errcode.knowledge import KnowledgeFileNotExistError
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.interfaces.knowledge_file_repository import (
    KnowledgeFileRepository,
)
from bisheng.role.domain.services.knowledge_parse_priority_service import (
    KnowledgeParsePriorityService,
)


class KnowledgeParsePrioritySnapshotService:
    """Persist and reuse an immutable priority decision for each file."""

    def __init__(
        self,
        file_repository: KnowledgeFileRepository,
        priority_service: KnowledgeParsePriorityService,
    ):
        self.file_repository = file_repository
        self.priority_service = priority_service

    async def get_or_create(
        self,
        *,
        file_id: int,
        operator_user_id: int | None = None,
        operator_is_global_super: bool | None = None,
    ) -> KnowledgeParsePriority:
        result = await self.get_or_create_batch(
            file_ids=[file_id],
            operator_user_id=operator_user_id,
            operator_is_global_super=operator_is_global_super,
        )
        if file_id not in result:
            raise KnowledgeFileNotExistError()
        return result[file_id]

    async def get_or_create_batch(
        self,
        *,
        file_ids: list[int],
        operator_user_id: int | None = None,
        operator_is_global_super: bool | None = None,
    ) -> dict[int, KnowledgeParsePriority]:
        normalized_ids = list(dict.fromkeys(file_id for file_id in file_ids if file_id > 0))
        files = list(await self.file_repository.find_by_ids(normalized_ids))
        files_by_id = {int(file.id): file for file in files if file.id is not None}
        if len(files_by_id) != len(normalized_ids):
            raise KnowledgeFileNotExistError()

        priorities: dict[int, KnowledgeParsePriority] = {}
        resolved_by_user: dict[tuple[int | None, bool | None], KnowledgeParsePriority] = {}
        for file_id in normalized_ids:
            file = files_by_id[file_id]
            existing = self._parse_existing(file)
            if existing is not None:
                priorities[file_id] = existing
                continue

            actor_user_id = operator_user_id if operator_user_id is not None else file.user_id
            is_global_super = operator_is_global_super if actor_user_id == operator_user_id else None
            cache_key = (actor_user_id, is_global_super)
            priority = resolved_by_user.get(cache_key)
            if priority is None:
                priority = await self.priority_service.resolve(
                    user_id=actor_user_id,
                    is_global_super=is_global_super,
                    file_id=file_id,
                    tenant_id=file.tenant_id,
                )
                resolved_by_user[cache_key] = priority

            persisted = await self.file_repository.set_parse_priority_if_unset(
                file_id,
                priority.value,
            )
            if persisted is None:
                raise KnowledgeFileNotExistError()
            final_priority = self._parse_existing(persisted)
            if final_priority is None:
                raise RuntimeError(f"parse priority snapshot was not persisted for file_id={file_id}")
            priorities[file_id] = final_priority
        return priorities

    @staticmethod
    def _parse_existing(file: KnowledgeFile) -> KnowledgeParsePriority | None:
        if file.parse_priority is None:
            return None
        return KnowledgeParsePriority.parse(file.parse_priority, default=None)
