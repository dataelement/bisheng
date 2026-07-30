from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func
from sqlmodel import col, delete, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_migration import (
    TERMINAL_BATCH_STATUSES,
    KnowledgeMigrationAttempt,
    KnowledgeMigrationAttemptResult,
    KnowledgeMigrationBatch,
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationCheckpoint,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_repository import (
    KnowledgeMigrationRepository,
    MigrationPage,
)
from bisheng.knowledge.domain.services.file_migration.state import (
    MigrationProgress,
    assert_batch_transition,
    calculate_progress,
)

_CHECKPOINT_ORDER = {
    value.value: index
    for index, value in enumerate(KnowledgeMigrationCheckpoint)
}


class KnowledgeMigrationRepositoryImpl(KnowledgeMigrationRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def create_batch_idempotent(
        self,
        batch: KnowledgeMigrationBatch,
    ) -> tuple[KnowledgeMigrationBatch, bool]:
        existing = await self.session.exec(
            select(KnowledgeMigrationBatch).where(
                KnowledgeMigrationBatch.operator_id == batch.operator_id,
                KnowledgeMigrationBatch.request_id == batch.request_id,
            )
        )
        found = existing.first()
        if found is not None:
            return found, False
        self.session.add(batch)
        await self.session.flush()
        await self.session.refresh(batch)
        return batch, True

    async def find_batch_by_id(
        self,
        batch_id: int,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeMigrationBatch | None:
        statement = select(KnowledgeMigrationBatch).where(KnowledgeMigrationBatch.id == batch_id)
        if not include_deleted:
            statement = statement.where(KnowledgeMigrationBatch.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def find_batch_by_no(
        self,
        batch_no: str,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> KnowledgeMigrationBatch | None:
        statement = select(KnowledgeMigrationBatch).where(
            KnowledgeMigrationBatch.batch_no == batch_no
        )
        if not include_deleted:
            statement = statement.where(KnowledgeMigrationBatch.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.exec(statement)).first()

    async def list_batches(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> MigrationPage:
        filters = [KnowledgeMigrationBatch.deleted_at.is_(None)]
        if status:
            filters.append(KnowledgeMigrationBatch.status == status)
        total = int(
            (
                await self.session.exec(
                    select(func.count()).select_from(KnowledgeMigrationBatch).where(*filters)
                )
            ).one()
        )
        items = (
            await self.session.exec(
                select(KnowledgeMigrationBatch)
                .where(*filters)
                .order_by(
                    KnowledgeMigrationBatch.create_time.desc(),
                    KnowledgeMigrationBatch.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return MigrationPage(items=items, total=total, page=page, page_size=page_size)

    async def compare_and_set_batch_status(
        self,
        batch_id: int,
        expected: set[str],
        target: str,
        **values,
    ) -> bool:
        for current in expected:
            assert_batch_transition(current, target)
        result = await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(
                KnowledgeMigrationBatch.id == batch_id,
                col(KnowledgeMigrationBatch.status).in_(expected),
                KnowledgeMigrationBatch.deleted_at.is_(None),
            )
            .values(status=target, current_stage=target, **values)
        )
        return int(result.rowcount or 0) == 1

    async def replace_plan(
        self,
        batch_id: int,
        units_with_files: Sequence[
            tuple[KnowledgeMigrationUnit, Sequence[KnowledgeMigrationFile]]
        ],
    ) -> None:
        await self.clear_plan(batch_id)
        await self.append_plan(batch_id, units_with_files)

    async def clear_plan(self, batch_id: int) -> None:
        await self.session.exec(delete(KnowledgeMigrationFile).where(KnowledgeMigrationFile.batch_id == batch_id))
        await self.session.exec(delete(KnowledgeMigrationAttempt).where(KnowledgeMigrationAttempt.batch_id == batch_id))
        await self.session.exec(delete(KnowledgeMigrationUnit).where(KnowledgeMigrationUnit.batch_id == batch_id))
        await self.session.flush()

    async def append_plan(
        self,
        batch_id: int,
        units_with_files: Sequence[tuple[KnowledgeMigrationUnit, Sequence[KnowledgeMigrationFile]]],
    ) -> None:
        for unit, files in units_with_files:
            unit.batch_id = batch_id
            self.session.add(unit)
            await self.session.flush()
            if unit.id is None:
                raise RuntimeError("migration unit ID was not generated")
            for file_row in files:
                file_row.batch_id = batch_id
                file_row.unit_id = unit.id
                self.session.add(file_row)
        await self.session.flush()

    async def list_units(
        self,
        batch_id: int,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> MigrationPage:
        filters = [KnowledgeMigrationUnit.batch_id == batch_id]
        if status:
            filters.append(KnowledgeMigrationUnit.status == status)
        total = int(
            (
                await self.session.exec(
                    select(func.count()).select_from(KnowledgeMigrationUnit).where(*filters)
                )
            ).one()
        )
        items = (
            await self.session.exec(
                select(KnowledgeMigrationUnit)
                .where(*filters)
                .order_by(KnowledgeMigrationUnit.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return MigrationPage(items=items, total=total, page=page, page_size=page_size)

    async def list_files(self, unit_id: int) -> list[KnowledgeMigrationFile]:
        return list(
            (
                await self.session.exec(
                    select(KnowledgeMigrationFile)
                    .where(KnowledgeMigrationFile.unit_id == unit_id)
                    .order_by(
                        KnowledgeMigrationFile.source_version_no,
                        KnowledgeMigrationFile.id,
                    )
                )
            ).all()
        )

    async def list_attempts(
        self,
        batch_id: int,
        *,
        page: int,
        page_size: int,
    ) -> MigrationPage:
        total = int(
            (
                await self.session.exec(
                    select(func.count())
                    .select_from(KnowledgeMigrationAttempt)
                    .where(KnowledgeMigrationAttempt.batch_id == batch_id)
                )
            ).one()
        )
        items = (
            await self.session.exec(
                select(KnowledgeMigrationAttempt)
                .where(KnowledgeMigrationAttempt.batch_id == batch_id)
                .order_by(KnowledgeMigrationAttempt.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return MigrationPage(items=items, total=total, page=page, page_size=page_size)

    async def claim_next_unit(
        self,
        *,
        batch_id: int,
        round_no: int,
        execution_token: str,
        worker_task_id: str | None,
    ) -> tuple[KnowledgeMigrationUnit, KnowledgeMigrationAttempt] | None:
        batch = await self.find_batch_by_id(batch_id, for_update=True)
        if batch is None or batch.status != KnowledgeMigrationBatchStatus.RUNNING.value:
            return None
        unit = (
            await self.session.exec(
                select(KnowledgeMigrationUnit)
                .where(
                    KnowledgeMigrationUnit.batch_id == batch_id,
                    KnowledgeMigrationUnit.current_round_no == round_no,
                    col(KnowledgeMigrationUnit.status).in_(
                        {
                            KnowledgeMigrationUnitStatus.PLANNED.value,
                            KnowledgeMigrationUnitStatus.UNPROCESSED.value,
                        }
                    ),
                )
                .order_by(KnowledgeMigrationUnit.id)
                .limit(1)
                .with_for_update()
            )
        ).first()
        if unit is None:
            return None
        unit.status = KnowledgeMigrationUnitStatus.RUNNING.value
        unit.attempt_count += 1
        unit.started_at = unit.started_at or datetime.now()
        attempt = KnowledgeMigrationAttempt(
            batch_id=batch_id,
            unit_id=int(unit.id),
            round_no=round_no,
            attempt_no=unit.attempt_count,
            worker_task_id=worker_task_id,
            execution_token=execution_token,
            start_checkpoint=unit.checkpoint,
            started_at=datetime.now(),
        )
        self.session.add(unit)
        self.session.add(attempt)
        await self.session.flush()
        return unit, attempt

    async def update_checkpoint(
        self,
        unit_id: int,
        checkpoint: str,
        *,
        attempt_id: int,
        execution_token: str,
        file_ids: Sequence[int] = (),
    ) -> bool:
        active = await self._lock_active_attempt(
            attempt_id=attempt_id,
            execution_token=execution_token,
            expected_unit_id=unit_id,
        )
        if active is None:
            return False
        _, unit = active
        if _CHECKPOINT_ORDER[checkpoint] < _CHECKPOINT_ORDER[unit.checkpoint]:
            raise ValueError(
                f"migration checkpoint cannot move backwards: {unit.checkpoint} -> {checkpoint}"
            )
        unit.checkpoint = checkpoint
        self.session.add(unit)
        file_filters = [KnowledgeMigrationFile.unit_id == unit_id]
        if file_ids:
            file_filters.append(col(KnowledgeMigrationFile.id).in_(file_ids))
        await self.session.exec(
            update(KnowledgeMigrationFile).where(*file_filters).values(checkpoint=checkpoint)
        )
        await self.session.flush()
        return True

    async def _lock_active_attempt(
        self,
        *,
        attempt_id: int,
        execution_token: str,
        expected_unit_id: int | None = None,
    ) -> tuple[KnowledgeMigrationAttempt, KnowledgeMigrationUnit] | None:
        identity = (
            await self.session.exec(
                select(KnowledgeMigrationAttempt).where(
                    KnowledgeMigrationAttempt.id == attempt_id
                )
            )
        ).first()
        if identity is None:
            return None
        batch = (
            await self.session.exec(
                select(KnowledgeMigrationBatch)
                .where(KnowledgeMigrationBatch.id == identity.batch_id)
                .with_for_update()
            )
        ).first()
        unit = (
            await self.session.exec(
                select(KnowledgeMigrationUnit)
                .where(KnowledgeMigrationUnit.id == identity.unit_id)
                .with_for_update()
            )
        ).first()
        if unit is not None:
            (
                await self.session.exec(
                    select(KnowledgeMigrationFile.id)
                    .where(KnowledgeMigrationFile.unit_id == unit.id)
                    .with_for_update()
                )
            ).all()
        attempt = (
            await self.session.exec(
                select(KnowledgeMigrationAttempt)
                .where(KnowledgeMigrationAttempt.id == attempt_id)
                .with_for_update()
            )
        ).first()
        if (
            attempt is None
            or batch is None
            or batch.status
            != KnowledgeMigrationBatchStatus.RUNNING.value
            or attempt.execution_token != execution_token
            or attempt.result != KnowledgeMigrationAttemptResult.RUNNING.value
            or (expected_unit_id is not None and int(attempt.unit_id) != expected_unit_id)
        ):
            return None
        if (
            unit is None
            or int(unit.id) != int(attempt.unit_id)
            or unit.status != KnowledgeMigrationUnitStatus.RUNNING.value
            or int(unit.attempt_count) != int(attempt.attempt_no)
        ):
            return None
        return attempt, unit

    async def is_attempt_active(
        self,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> bool:
        return (
            await self._lock_active_attempt(
                attempt_id=attempt_id,
                execution_token=execution_token,
            )
            is not None
        )

    async def reset_after_compensation(
        self,
        unit_id: int,
        *,
        attempt_id: int,
        execution_token: str,
    ) -> bool:
        active = await self._lock_active_attempt(
            attempt_id=attempt_id,
            execution_token=execution_token,
            expected_unit_id=unit_id,
        )
        if active is None:
            return False
        _, unit = active
        if _CHECKPOINT_ORDER[unit.checkpoint] >= _CHECKPOINT_ORDER[KnowledgeMigrationCheckpoint.DB_SWITCHED.value]:
            raise ValueError("cannot compensate a unit after database switch")
        unit.checkpoint = KnowledgeMigrationCheckpoint.PLANNED.value
        self.session.add(unit)
        await self.session.exec(
            update(KnowledgeMigrationFile)
            .where(KnowledgeMigrationFile.unit_id == unit_id)
            .values(
                checkpoint=KnowledgeMigrationCheckpoint.PLANNED.value,
                target_file_id=None,
                target_folder_id=None,
                target_resource_manifest=None,
            )
        )
        await self.session.flush()
        return True

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
    ) -> bool:
        active = await self._lock_active_attempt(
            attempt_id=attempt_id,
            execution_token=execution_token,
        )
        if active is None:
            return False
        attempt, unit = active
        unit.status = unit_status
        unit.checkpoint = checkpoint
        unit.reason_code = reason_code
        unit.summary = error_summary
        unit.finished_at = datetime.now()
        attempt.end_checkpoint = checkpoint
        attempt.result = result
        attempt.reason_code = reason_code
        attempt.error_summary = error_summary
        attempt.finished_at = datetime.now()
        self.session.add(unit)
        self.session.add(attempt)
        await self.session.exec(
            update(KnowledgeMigrationFile)
            .where(KnowledgeMigrationFile.unit_id == unit.id)
            .values(
                status=unit_status,
                checkpoint=checkpoint,
                reason_code=reason_code,
                summary=error_summary,
            )
        )
        await self.session.flush()
        return True

    async def mark_remaining_unprocessed(
        self,
        batch_id: int,
        *,
        round_no: int,
        reason_code: str,
        summary: str,
    ) -> None:
        unit_ids = list(
            (
                await self.session.exec(
                    select(KnowledgeMigrationUnit.id).where(
                        KnowledgeMigrationUnit.batch_id == batch_id,
                        KnowledgeMigrationUnit.current_round_no == round_no,
                        col(KnowledgeMigrationUnit.status).in_(
                            {
                                KnowledgeMigrationUnitStatus.PLANNED.value,
                                KnowledgeMigrationUnitStatus.RUNNING.value,
                            }
                        ),
                    )
                )
            ).all()
        )
        if not unit_ids:
            return
        await self.session.exec(
            update(KnowledgeMigrationUnit)
            .where(col(KnowledgeMigrationUnit.id).in_(unit_ids))
            .values(
                status=KnowledgeMigrationUnitStatus.UNPROCESSED.value,
                reason_code=reason_code,
                summary=summary,
                finished_at=datetime.now(),
            )
        )
        await self.session.exec(
            update(KnowledgeMigrationFile)
            .where(col(KnowledgeMigrationFile.unit_id).in_(unit_ids))
            .values(
                status=KnowledgeMigrationUnitStatus.UNPROCESSED.value,
                reason_code=reason_code,
                summary=summary,
            )
        )
        await self.session.exec(
            update(KnowledgeMigrationAttempt)
            .where(
                col(KnowledgeMigrationAttempt.unit_id).in_(unit_ids),
                KnowledgeMigrationAttempt.result
                == KnowledgeMigrationAttemptResult.RUNNING.value,
            )
            .values(
                result=KnowledgeMigrationAttemptResult.INTERRUPTED.value,
                reason_code=reason_code,
                error_summary=summary,
                finished_at=datetime.now(),
            )
        )
        await self.session.flush()

    async def recompute_progress(self, batch_id: int) -> MigrationProgress:
        statuses = (
            await self.session.exec(
                select(KnowledgeMigrationUnit.status).where(
                    KnowledgeMigrationUnit.batch_id == batch_id
                )
            )
        ).all()
        progress = calculate_progress(statuses)
        await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(KnowledgeMigrationBatch.id == batch_id)
            .values(
                total_count=progress.total_count,
                executable_count=progress.executable_count,
                completed_count=progress.completed_count,
                succeeded_count=progress.succeeded_count,
                skipped_count=progress.skipped_count,
                failed_count=progress.failed_count,
                unprocessed_count=progress.unprocessed_count,
            )
        )
        return progress

    async def retry_batch(
        self,
        batch_id: int,
        *,
        queued_at: datetime,
    ) -> KnowledgeMigrationBatch | None:
        batch = await self.find_batch_by_id(batch_id, for_update=True)
        if batch is None or batch.status not in {
            KnowledgeMigrationBatchStatus.PARTIAL_SUCCESS.value,
            KnowledgeMigrationBatchStatus.FAILED.value,
        }:
            return None
        next_round = batch.round_no + 1
        result = await self.session.exec(
            update(KnowledgeMigrationUnit)
            .where(
                KnowledgeMigrationUnit.batch_id == batch_id,
                col(KnowledgeMigrationUnit.status).in_(
                    {
                        KnowledgeMigrationUnitStatus.FAILED.value,
                        KnowledgeMigrationUnitStatus.UNPROCESSED.value,
                    }
                ),
            )
            .values(
                status=KnowledgeMigrationUnitStatus.PLANNED.value,
                current_round_no=next_round,
                reason_code=None,
                summary=None,
                finished_at=None,
            )
        )
        if int(result.rowcount or 0) == 0:
            return None
        batch.round_no = next_round
        batch.status = KnowledgeMigrationBatchStatus.QUEUED.value
        batch.current_stage = KnowledgeMigrationBatchStatus.QUEUED.value
        batch.queued_at = queued_at
        batch.finished_at = None
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def soft_delete_batch(
        self,
        batch_id: int,
        *,
        deleted_by: int,
        deleted_at: datetime,
    ) -> bool:
        result = await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(
                KnowledgeMigrationBatch.id == batch_id,
                col(KnowledgeMigrationBatch.status).in_(TERMINAL_BATCH_STATUSES),
                KnowledgeMigrationBatch.deleted_at.is_(None),
            )
            .values(deleted_by=deleted_by, deleted_at=deleted_at)
        )
        return int(result.rowcount or 0) == 1

    async def find_oldest_queued_batch(self) -> KnowledgeMigrationBatch | None:
        return (
            await self.session.exec(
                select(KnowledgeMigrationBatch)
                .where(
                    KnowledgeMigrationBatch.status == KnowledgeMigrationBatchStatus.QUEUED.value,
                    KnowledgeMigrationBatch.deleted_at.is_(None),
                )
                .order_by(
                    KnowledgeMigrationBatch.queued_at,
                    KnowledgeMigrationBatch.id,
                )
                .limit(1)
            )
        ).first()

    async def list_reconcile_candidates(
        self,
        statuses: set[str],
        *,
        older_than: datetime,
        limit: int,
    ) -> list[KnowledgeMigrationBatch]:
        return list(
            (
                await self.session.exec(
                    select(KnowledgeMigrationBatch)
                    .where(
                        col(KnowledgeMigrationBatch.status).in_(statuses),
                        KnowledgeMigrationBatch.update_time < older_than,
                        KnowledgeMigrationBatch.deleted_at.is_(None),
                    )
                    .order_by(KnowledgeMigrationBatch.update_time, KnowledgeMigrationBatch.id)
                    .limit(limit)
                )
            ).all()
        )

    async def recover_stale_running_batch(
        self,
        batch_id: int,
        *,
        queued_at: datetime,
    ) -> bool:
        batch = await self.find_batch_by_id(batch_id, for_update=True)
        if (
            batch is None
            or batch.status != KnowledgeMigrationBatchStatus.RUNNING.value
        ):
            return False
        await self.mark_remaining_unprocessed(
            batch_id,
            round_no=batch.round_no,
            reason_code="worker_interrupted",
            summary="执行 worker 心跳超时, 等待同批次恢复",
        )
        batch.status = KnowledgeMigrationBatchStatus.QUEUED.value
        batch.current_stage = KnowledgeMigrationBatchStatus.QUEUED.value
        batch.queued_at = queued_at
        batch.execution_task_id = None
        self.session.add(batch)
        await self.session.flush()
        return True

    async def touch_running_batch(
        self,
        batch_id: int,
        *,
        touched_at: datetime,
    ) -> bool:
        result = await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(
                KnowledgeMigrationBatch.id == batch_id,
                KnowledgeMigrationBatch.status
                == KnowledgeMigrationBatchStatus.RUNNING.value,
            )
            .values(update_time=touched_at)
        )
        return int(result.rowcount or 0) == 1

    async def recover_stale_preflight_batch(self, batch_id: int) -> bool:
        result = await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(
                KnowledgeMigrationBatch.id == batch_id,
                KnowledgeMigrationBatch.status
                == KnowledgeMigrationBatchStatus.PREFLIGHTING.value,
            )
            .values(
                status=KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value,
                current_stage=KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value,
                preflight_task_id=None,
            )
        )
        return int(result.rowcount or 0) == 1

    async def touch_preflight_batch(
        self,
        batch_id: int,
        *,
        touched_at: datetime,
    ) -> bool:
        result = await self.session.exec(
            update(KnowledgeMigrationBatch)
            .where(
                KnowledgeMigrationBatch.id == batch_id,
                KnowledgeMigrationBatch.status
                == KnowledgeMigrationBatchStatus.PREFLIGHTING.value,
            )
            .values(update_time=touched_at)
        )
        return int(result.rowcount or 0) == 1
