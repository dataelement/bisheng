"""迁移状态机和可重算进度。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationUnitStatus,
)


class MigrationScope(str, Enum):
    """F4: distinguishes migration types so the executor can branch."""
    CROSS_SPACE = "cross_space"          # existing: move files between spaces
    SHARED_STORAGE = "shared_storage"    # F4: tenant → shared Milvus/ES

_BATCH_TRANSITIONS = {
    KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value: {
        KnowledgeMigrationBatchStatus.PREFLIGHTING.value,
        KnowledgeMigrationBatchStatus.FAILED.value,
    },
    KnowledgeMigrationBatchStatus.PREFLIGHTING.value: {
        KnowledgeMigrationBatchStatus.AWAITING_CONFIRMATION.value,
        KnowledgeMigrationBatchStatus.QUEUED.value,
        KnowledgeMigrationBatchStatus.FAILED.value,
    },
    KnowledgeMigrationBatchStatus.AWAITING_CONFIRMATION.value: {
        KnowledgeMigrationBatchStatus.QUEUED.value,
        KnowledgeMigrationBatchStatus.ABANDONED.value,
    },
    KnowledgeMigrationBatchStatus.QUEUED.value: {
        KnowledgeMigrationBatchStatus.RUNNING.value,
        KnowledgeMigrationBatchStatus.FAILED.value,
    },
    KnowledgeMigrationBatchStatus.RUNNING.value: {
        KnowledgeMigrationBatchStatus.SUCCEEDED.value,
        KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value,
        KnowledgeMigrationBatchStatus.FAILED.value,
    },
    KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value: {
        KnowledgeMigrationBatchStatus.QUEUED.value,
    },
    KnowledgeMigrationBatchStatus.FAILED.value: {
        KnowledgeMigrationBatchStatus.QUEUED.value,
    },
}


def assert_batch_transition(current: str, target: str) -> None:
    if current == target:
        return
    if target not in _BATCH_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid batch status transition: {current} -> {target}")


@dataclass(frozen=True)
class MigrationProgress:
    total_count: int
    executable_count: int
    completed_count: int
    succeeded_count: int
    skipped_count: int
    failed_count: int
    unprocessed_count: int


def calculate_progress(statuses: Iterable[str]) -> MigrationProgress:
    values = tuple(statuses)
    succeeded = values.count(KnowledgeMigrationUnitStatus.SUCCEEDED.value)
    skipped = values.count(KnowledgeMigrationUnitStatus.POLICY_SKIPPED.value)
    failed = values.count(KnowledgeMigrationUnitStatus.FAILED.value)
    unprocessed = values.count(KnowledgeMigrationUnitStatus.UNPROCESSED.value)
    completed = succeeded + skipped + failed
    return MigrationProgress(
        total_count=len(values),
        executable_count=len(values) - skipped,
        completed_count=completed,
        succeeded_count=succeeded,
        skipped_count=skipped,
        failed_count=failed,
        unprocessed_count=unprocessed,
    )


def aggregate_batch_status(progress: MigrationProgress) -> str:
    if progress.executable_count == 0:
        return KnowledgeMigrationBatchStatus.FAILED.value
    if progress.failed_count == 0 and progress.unprocessed_count == 0:
        return KnowledgeMigrationBatchStatus.SUCCEEDED.value
    if progress.succeeded_count > 0:
        return KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value
    return KnowledgeMigrationBatchStatus.FAILED.value
