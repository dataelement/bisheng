from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.user.domain.models.user import User


@dataclass(frozen=True)
class MigrationRuntimeFile:
    control: KnowledgeMigrationFile
    source: KnowledgeFile
    target: KnowledgeFile


@dataclass(frozen=True)
class MigrationRuntimeContext:
    batch: KnowledgeMigrationBatch
    unit: KnowledgeMigrationUnit
    files: tuple[MigrationRuntimeFile, ...]
    source_spaces: dict[int, Knowledge]
    target_space: Knowledge
    target_owner: User
    created_folders: tuple[KnowledgeFile, ...]


class KnowledgeMigrationRuntimeRepository(ABC):
    @abstractmethod
    async def find_batch_modes(self, unit_ids: list[int]) -> dict[int, bool]: ...

    @abstractmethod
    async def finish_shared_projection(
        self, unit_id: int, plan: dict, *, attempt_id: int, execution_token: str
    ) -> None: ...

    @abstractmethod
    async def shared_projection_plan(self, unit_id: int, *, attempt_id: int, execution_token: str) -> dict: ...

    @abstractmethod
    async def prepare_preserve_link_folders(self, unit_id: int, *, attempt_id: int, execution_token: str): ...

    @abstractmethod
    async def record_preserve_link_result(self, unit_id: int, result, *, attempt_id: int, execution_token: str) -> None: ...

    @abstractmethod
    async def prepare_target_rows(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> MigrationRuntimeContext: ...

    @abstractmethod
    async def load_context(self, unit_id: int) -> MigrationRuntimeContext: ...

    @abstractmethod
    async def load_contexts(self, unit_ids: list[int]) -> dict[int, MigrationRuntimeContext]: ...

    @abstractmethod
    async def activate_switch(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> None: ...

    @abstractmethod
    async def cleanup_source_rows(self, unit_id: int) -> None: ...

    @abstractmethod
    async def cleanup_new_target_rows(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> None: ...
