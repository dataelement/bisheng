from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttempt,
    KnowledgeMigrationBatch,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.knowledge.domain.services.file_migration.state import MigrationProgress


@dataclass(frozen=True)
class MigrationPage:
    items: Sequence[object]
    total: int
    page: int
    page_size: int


class KnowledgeMigrationRepositoryContextFactory(Protocol):
    def __call__(
        self,
    ) -> AbstractAsyncContextManager[KnowledgeMigrationRepository]: ...


class KnowledgeMigrationRepository(ABC):
    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    @abstractmethod
    async def create_batch_idempotent(
        self,
        batch: KnowledgeMigrationBatch,
    ) -> tuple[KnowledgeMigrationBatch, bool]: ...

    @abstractmethod
    async def find_batch_by_id(
        self,
        batch_id: int,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeMigrationBatch | None: ...

    @abstractmethod
    async def find_batch_by_no(
        self,
        batch_no: str,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeMigrationBatch | None: ...

    @abstractmethod
    async def list_batches(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> MigrationPage: ...

    @abstractmethod
    async def compare_and_set_batch_status(
        self,
        batch_id: int,
        expected: set[str],
        target: str,
        **values,
    ) -> bool: ...

    @abstractmethod
    async def replace_plan(
        self,
        batch_id: int,
        units_with_files: Sequence[
            tuple[KnowledgeMigrationUnit, Sequence[KnowledgeMigrationFile]]
        ],
    ) -> None: ...

    @abstractmethod
    async def clear_plan(self, batch_id: int) -> None: ...

    @abstractmethod
    async def append_plan(
        self,
        batch_id: int,
        units_with_files: Sequence[tuple[KnowledgeMigrationUnit, Sequence[KnowledgeMigrationFile]]],
    ) -> None: ...

    @abstractmethod
    async def list_units(
        self,
        batch_id: int,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> MigrationPage: ...

    @abstractmethod
    async def list_files(self, unit_id: int) -> list[KnowledgeMigrationFile]: ...

    @abstractmethod
    async def list_attempts(
        self,
        batch_id: int,
        *,
        page: int,
        page_size: int,
    ) -> MigrationPage: ...

    @abstractmethod
    async def claim_next_unit(
        self,
        *,
        batch_id: int,
        round_no: int,
        execution_token: str,
        worker_task_id: str | None,
    ) -> tuple[KnowledgeMigrationUnit, KnowledgeMigrationAttempt] | None: ...

    @abstractmethod
    async def update_checkpoint(
        self,
        unit_id: int,
        checkpoint: str,
        *,
        attempt_id: int,
        execution_token: str,
        file_ids: Sequence[int] = (),
    ) -> bool: ...

    @abstractmethod
    async def is_attempt_active(
        self,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> bool: ...

    @abstractmethod
    async def reset_after_compensation(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> bool: ...

    @abstractmethod
    async def finish_attempt(
        self,
        *,
        attempt_id: int,
        execution_token: str,
        unit_status: str,
        checkpoint: str,
        result: str,
        reason_code: str | None = None,
        error_summary: str | None = None,
    ) -> bool: ...

    @abstractmethod
    async def mark_remaining_unprocessed(
        self,
        batch_id: int,
        *,
        round_no: int,
        reason_code: str,
        summary: str,
    ) -> None: ...

    @abstractmethod
    async def recompute_progress(self, batch_id: int) -> MigrationProgress: ...

    @abstractmethod
    async def retry_batch(
        self,
        batch_id: int,
        *,
        queued_at: datetime,
    ) -> KnowledgeMigrationBatch | None: ...

    @abstractmethod
    async def soft_delete_batch(
        self,
        batch_id: int,
        *,
        deleted_by: int,
        deleted_at: datetime,
    ) -> bool: ...

    @abstractmethod
    async def find_oldest_queued_batch(self) -> KnowledgeMigrationBatch | None: ...

    @abstractmethod
    async def list_reconcile_candidates(
        self,
        statuses: set[str],
        *,
        older_than: datetime,
        limit: int,
    ) -> list[KnowledgeMigrationBatch]: ...

    @abstractmethod
    async def recover_stale_running_batch(
        self,
        batch_id: int,
        *,
        queued_at: datetime,
    ) -> bool: ...

    @abstractmethod
    async def recover_stale_preflight_batch(self, batch_id: int) -> bool: ...

    @abstractmethod
    async def touch_running_batch(
        self,
        batch_id: int,
        *,
        touched_at: datetime,
    ) -> bool: ...

    @abstractmethod
    async def touch_preflight_batch(
        self,
        batch_id: int,
        *,
        touched_at: datetime,
    ) -> bool: ...
