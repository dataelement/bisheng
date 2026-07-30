"""按持久检查点执行一个迁移单元的通用编排器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bisheng.knowledge.domain.models.knowledge_migration import KnowledgeMigrationCheckpoint


@dataclass(frozen=True)
class MigrationExecutionUnit:
    unit_id: int
    checkpoint: str = KnowledgeMigrationCheckpoint.PLANNED.value
    restart_pre_switch: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    succeeded: bool
    checkpoint: str
    source_cleanup_pending: bool
    error_summary: str = ""


class MigrationOperations(Protocol):
    async def create_target_rows(self, unit: MigrationExecutionUnit) -> None: ...
    async def copy_target_objects(self, unit: MigrationExecutionUnit) -> None: ...
    async def build_target_indexes(self, unit: MigrationExecutionUnit) -> None: ...
    async def write_target_permissions(self, unit: MigrationExecutionUnit) -> None: ...
    async def verify_target(self, unit: MigrationExecutionUnit) -> None: ...
    async def switch_database(self, unit: MigrationExecutionUnit) -> None: ...
    async def cleanup_source_external(self, unit: MigrationExecutionUnit) -> None: ...
    async def cleanup_source_rows(self, unit: MigrationExecutionUnit) -> None: ...
    async def cleanup_new_target(self, unit: MigrationExecutionUnit) -> None: ...


class CheckpointStore(Protocol):
    async def save_checkpoint(self, unit_id: int, checkpoint: str) -> None: ...
    async def reset_after_compensation(self, unit_id: int) -> None: ...


_STEPS = (
    ("create_target_rows", KnowledgeMigrationCheckpoint.TARGET_ROWS_CREATED.value),
    ("copy_target_objects", KnowledgeMigrationCheckpoint.TARGET_OBJECTS_COPIED.value),
    ("build_target_indexes", KnowledgeMigrationCheckpoint.TARGET_INDEXES_BUILT.value),
    ("write_target_permissions", KnowledgeMigrationCheckpoint.TARGET_PERMISSIONS_READY.value),
    ("verify_target", KnowledgeMigrationCheckpoint.TARGET_VERIFIED.value),
    ("switch_database", KnowledgeMigrationCheckpoint.DB_SWITCHED.value),
    ("cleanup_source_external", KnowledgeMigrationCheckpoint.SOURCE_EXTERNAL_CLEANED.value),
    ("cleanup_source_rows", KnowledgeMigrationCheckpoint.SOURCE_ROWS_CLEANED.value),
)
_CHECKPOINT_INDEX = {
    KnowledgeMigrationCheckpoint.PLANNED.value: 0,
    **{checkpoint: index + 1 for index, (_, checkpoint) in enumerate(_STEPS)},
    KnowledgeMigrationCheckpoint.COMPLETED.value: len(_STEPS) + 1,
}


async def execute_unit(
    unit: MigrationExecutionUnit,
    operations: MigrationOperations,
    checkpoint_store: CheckpointStore,
) -> ExecutionResult:
    checkpoint = unit.checkpoint
    completed_steps = _CHECKPOINT_INDEX.get(checkpoint)
    if completed_steps is None:
        raise ValueError(f"unknown migration checkpoint: {checkpoint}")
    if checkpoint == KnowledgeMigrationCheckpoint.COMPLETED.value:
        return ExecutionResult(True, checkpoint, False)

    if (
        unit.restart_pre_switch
        and completed_steps
        < _CHECKPOINT_INDEX[
            KnowledgeMigrationCheckpoint.DB_SWITCHED.value
        ]
    ):
        try:
            await operations.cleanup_new_target(unit)
            await checkpoint_store.reset_after_compensation(unit.unit_id)
            checkpoint = KnowledgeMigrationCheckpoint.PLANNED.value
            completed_steps = 0
        except Exception as exc:
            return ExecutionResult(
                succeeded=False,
                checkpoint=checkpoint,
                source_cleanup_pending=False,
                error_summary=f"{type(exc).__name__}: {exc}",
            )

    try:
        for index, (method_name, next_checkpoint) in enumerate(_STEPS, start=1):
            if index <= completed_steps:
                continue
            await getattr(operations, method_name)(unit)
            checkpoint = next_checkpoint
            await checkpoint_store.save_checkpoint(unit.unit_id, checkpoint)
        checkpoint = KnowledgeMigrationCheckpoint.COMPLETED.value
        await checkpoint_store.save_checkpoint(unit.unit_id, checkpoint)
        return ExecutionResult(True, checkpoint, False)
    except Exception as exc:
        switched = _CHECKPOINT_INDEX[checkpoint] >= _CHECKPOINT_INDEX[KnowledgeMigrationCheckpoint.DB_SWITCHED.value]
        if not switched:
            try:
                await operations.cleanup_new_target(unit)
                await checkpoint_store.reset_after_compensation(unit.unit_id)
                checkpoint = KnowledgeMigrationCheckpoint.PLANNED.value
            except Exception:
                # 补偿失败由上层 attempt/manifest 记录. 不能覆盖原始失败.
                pass
        return ExecutionResult(
            succeeded=False,
            checkpoint=checkpoint,
            source_cleanup_pending=switched,
            error_summary=f"{type(exc).__name__}: {exc}",
        )
