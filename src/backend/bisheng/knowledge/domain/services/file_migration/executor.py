"""按持久检查点执行一个迁移单元的通用编排器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from bisheng.knowledge.domain.models.knowledge_migration import KnowledgeMigrationCheckpoint


@dataclass(frozen=True)
class MigrationExecutionUnit:
    unit_id: int
    checkpoint: str = KnowledgeMigrationCheckpoint.PLANNED.value
    restart_pre_switch: bool = False
    attempt_id: int | None = None
    execution_token: str = ""
    cancelled: Callable[[], bool] | None = None


@dataclass(frozen=True)
class ExecutionResult:
    succeeded: bool
    checkpoint: str
    source_cleanup_pending: bool
    error_summary: str = ""
    interrupted: bool = False


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
    async def is_attempt_active(
        self,
        unit: MigrationExecutionUnit,
    ) -> bool: ...

    async def save_checkpoint(
        self,
        unit: MigrationExecutionUnit,
        checkpoint: str,
    ) -> None: ...

    async def reset_after_compensation(
        self,
        unit: MigrationExecutionUnit,
    ) -> None: ...


class StaleMigrationAttemptError(RuntimeError):
    """当前 worker 已不再拥有该迁移单元的执行代。"""


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


async def _ensure_active(
    unit: MigrationExecutionUnit,
    checkpoint_store: CheckpointStore,
) -> None:
    if unit.cancelled is not None and unit.cancelled():
        raise StaleMigrationAttemptError("migration execution lease was lost")
    if not await checkpoint_store.is_attempt_active(unit):
        raise StaleMigrationAttemptError("migration execution generation is no longer active")


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
            await _ensure_active(unit, checkpoint_store)
            await operations.cleanup_new_target(unit)
            await _ensure_active(unit, checkpoint_store)
            await checkpoint_store.reset_after_compensation(unit)
            checkpoint = KnowledgeMigrationCheckpoint.PLANNED.value
            completed_steps = 0
        except StaleMigrationAttemptError as exc:
            return ExecutionResult(
                succeeded=False,
                checkpoint=checkpoint,
                source_cleanup_pending=False,
                error_summary=f"{type(exc).__name__}: {exc}",
                interrupted=True,
            )
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
            await _ensure_active(unit, checkpoint_store)
            await getattr(operations, method_name)(unit)
            checkpoint = next_checkpoint
            await _ensure_active(unit, checkpoint_store)
            await checkpoint_store.save_checkpoint(unit, checkpoint)
        checkpoint = KnowledgeMigrationCheckpoint.COMPLETED.value
        await _ensure_active(unit, checkpoint_store)
        await checkpoint_store.save_checkpoint(unit, checkpoint)
        return ExecutionResult(True, checkpoint, False)
    except StaleMigrationAttemptError as exc:
        return ExecutionResult(
            succeeded=False,
            checkpoint=checkpoint,
            source_cleanup_pending=False,
            error_summary=f"{type(exc).__name__}: {exc}",
            interrupted=True,
        )
    except Exception as exc:
        switched = _CHECKPOINT_INDEX[checkpoint] >= _CHECKPOINT_INDEX[KnowledgeMigrationCheckpoint.DB_SWITCHED.value]
        if not switched:
            try:
                await _ensure_active(unit, checkpoint_store)
                await operations.cleanup_new_target(unit)
                await _ensure_active(unit, checkpoint_store)
                await checkpoint_store.reset_after_compensation(unit)
                checkpoint = KnowledgeMigrationCheckpoint.PLANNED.value
            except StaleMigrationAttemptError as stale_exc:
                return ExecutionResult(
                    succeeded=False,
                    checkpoint=checkpoint,
                    source_cleanup_pending=False,
                    error_summary=(f"{type(stale_exc).__name__}: {stale_exc}"),
                    interrupted=True,
                )
            except Exception:
                # 补偿失败由上层 attempt/manifest 记录. 不能覆盖原始失败.
                pass
        return ExecutionResult(
            succeeded=False,
            checkpoint=checkpoint,
            source_cleanup_pending=switched,
            error_summary=f"{type(exc).__name__}: {exc}",
        )


async def execute_units(units, operations, checkpoint_store) -> list[ExecutionResult]:
    """有界批次按阶段推进，成功检查点成组提交，失败仅影响对应文档。"""
    checkpoints = {unit.unit_id: unit.checkpoint for unit in units}
    results = {}
    await checkpoint_store.refresh(units)

    async def failed(unit, exc):
        checkpoint = checkpoints[unit.unit_id]
        interrupted = isinstance(exc, StaleMigrationAttemptError)
        switched = _CHECKPOINT_INDEX[checkpoint] >= _CHECKPOINT_INDEX["db_switched"]
        checkpoint_store.pending.pop(unit.attempt_id, None)
        if not interrupted and not switched:
            try:
                await _ensure_active(unit, checkpoint_store)
                await operations.cleanup_new_target(unit)
                await checkpoint_store.reset_after_compensation(unit)
                checkpoint = "planned"
            except Exception as cleanup_exc:
                exc = RuntimeError(f"{exc}; compensation failed: {cleanup_exc}")
        results[unit.unit_id] = ExecutionResult(False, checkpoint, switched, str(exc), interrupted)

    for unit in units:
        if unit.restart_pre_switch and _CHECKPOINT_INDEX[unit.checkpoint] < _CHECKPOINT_INDEX["db_switched"]:
            try:
                await _ensure_active(unit, checkpoint_store)
                await operations.cleanup_new_target(unit)
                await checkpoint_store.reset_after_compensation(unit)
                checkpoints[unit.unit_id] = "planned"
            except Exception as exc:
                await failed(unit, exc)

    for method, next_checkpoint in (*_STEPS, (None, "completed")):
        active = [unit for unit in units if unit.unit_id not in results]
        if not active:
            break
        await checkpoint_store.refresh(active)
        if hasattr(operations, "prepare_stage"):
            await operations.prepare_stage(
                [
                    unit
                    for unit in active
                    if _CHECKPOINT_INDEX[checkpoints[unit.unit_id]] < _CHECKPOINT_INDEX[next_checkpoint]
                ],
                method,
            )
        for unit in active:
            if _CHECKPOINT_INDEX[checkpoints[unit.unit_id]] >= _CHECKPOINT_INDEX[next_checkpoint]:
                continue
            try:
                await _ensure_active(unit, checkpoint_store)
                if method:
                    await getattr(operations, method)(unit)
                checkpoints[unit.unit_id] = next_checkpoint
                await _ensure_active(unit, checkpoint_store)
                await checkpoint_store.save_checkpoint(unit, next_checkpoint)
            except Exception as exc:
                await failed(unit, exc)
        try:
            await checkpoint_store.flush()
        except StaleMigrationAttemptError as exc:
            for unit in active:
                if unit.unit_id not in results:
                    results[unit.unit_id] = ExecutionResult(False, checkpoints[unit.unit_id], False, str(exc), True)
            break
    return [results.get(unit.unit_id) or ExecutionResult(True, checkpoints[unit.unit_id], False) for unit in units]
