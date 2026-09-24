"""全局串行的跨知识库迁移执行、续租和异常恢复编排。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from loguru import logger

from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttemptResult,
    KnowledgeMigrationBatchStatus,
    KnowledgeMigrationUnitStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_lock_repository import (
    KnowledgeMigrationLockRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_repository import (
    KnowledgeMigrationRepositoryContextFactory,
)
from bisheng.knowledge.domain.services.file_migration.executor import (
    MigrationExecutionUnit,
    MigrationOperations,
    StaleMigrationAttemptError,
    execute_units,
)
from bisheng.knowledge.domain.services.file_migration.state import (
    aggregate_batch_status,
)
from bisheng.knowledge.domain.services.knowledge_migration_service import (
    KnowledgeMigrationTaskDispatcher,
    sanitize_error_summary,
)

DEFAULT_LEASE_TTL_SECONDS = 300
DEFAULT_RECONCILE_STALE_SECONDS = 1800
DEFAULT_RECONCILE_MAX_RECOVERIES = 4


class BatchMigrationOperations(MigrationOperations, Protocol):
    async def cleanup_empty_source_folders(self, batch_id: int) -> None: ...


class DatabaseMigrationCheckpointStore:
    def __init__(
        self,
        repository_factory: KnowledgeMigrationRepositoryContextFactory,
    ):
        self.repository_factory = repository_factory

    @staticmethod
    def _attempt_identity(
        unit: MigrationExecutionUnit,
    ) -> tuple[int, str]:
        if unit.attempt_id is None or not unit.execution_token:
            raise StaleMigrationAttemptError("migration execution generation is missing")
        return unit.attempt_id, unit.execution_token

    async def is_attempt_active(
        self,
        unit: MigrationExecutionUnit,
    ) -> bool:
        attempt_id, execution_token = self._attempt_identity(unit)
        async with self.repository_factory() as repository:
            return await repository.is_attempt_active(
                attempt_id=attempt_id,
                execution_token=execution_token,
            )

    async def save_checkpoint(
        self,
        unit: MigrationExecutionUnit,
        checkpoint: str,
    ) -> None:
        attempt_id, execution_token = self._attempt_identity(unit)
        async with self.repository_factory() as repository:
            updated = await repository.update_checkpoint(
                unit.unit_id,
                checkpoint,
                attempt_id=attempt_id,
                execution_token=execution_token,
            )
            if not updated:
                await repository.rollback()
                raise StaleMigrationAttemptError("migration checkpoint write was fenced")
            await repository.commit()

    async def reset_after_compensation(
        self,
        unit: MigrationExecutionUnit,
    ) -> None:
        attempt_id, execution_token = self._attempt_identity(unit)
        async with self.repository_factory() as repository:
            reset = await repository.reset_after_compensation(
                unit.unit_id,
                attempt_id=attempt_id,
                execution_token=execution_token,
            )
            if not reset:
                await repository.rollback()
                raise StaleMigrationAttemptError("migration compensation write was fenced")
            await repository.commit()


class BatchMigrationCheckpointStore(DatabaseMigrationCheckpointStore):
    """同一阶段批量检查执行代、批量回写；DB 切换仍在业务事务中落盘。"""

    def __init__(self, repository_factory):
        super().__init__(repository_factory)
        self.active = set()
        self.pending = {}
        self.token = ""

    async def refresh(self, units):
        self.token = units[0].execution_token
        async with self.repository_factory() as repository:
            active = await repository.active_attempts([unit.attempt_id for unit in units], self.token)
            self.active = set(active)
            await repository.commit()

    async def is_attempt_active(self, unit):
        return unit.attempt_id in self.active and not (unit.cancelled and unit.cancelled())

    async def save_checkpoint(self, unit, checkpoint):
        self.pending[unit.attempt_id] = checkpoint

    async def flush(self):
        if not self.pending:
            return
        async with self.repository_factory() as repository:
            if not await repository.update_checkpoints(self.pending, execution_token=self.token):
                await repository.rollback()
                raise StaleMigrationAttemptError("batch checkpoint write was fenced")
            await repository.commit()
        self.pending.clear()


class _LeaseHeartbeat:
    def __init__(
        self,
        *,
        lock_repository: KnowledgeMigrationLockRepository,
        repository_factory: KnowledgeMigrationRepositoryContextFactory,
        token: str,
        ttl_seconds: int,
    ):
        self.lock_repository = lock_repository
        self.repository_factory = repository_factory
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.batch_id: int | None = None
        self.lost = asyncio.Event()
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        interval = max(1, self.ttl_seconds // 3)
        while True:
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=interval,
                )
                return
            except asyncio.TimeoutError:
                pass
            try:
                renewed = await self.lock_repository.renew(
                    self.token,
                    ttl_seconds=self.ttl_seconds,
                )
            except Exception:
                self.lost.set()
                return
            if not renewed:
                self.lost.set()
                return
            if self.batch_id is not None:
                try:
                    async with self.repository_factory() as repository:
                        await repository.touch_running_batch(
                            self.batch_id,
                            touched_at=datetime.now(),
                        )
                        await repository.commit()
                except Exception:
                    self.lost.set()
                    return

    def stop(self) -> None:
        self._stopped.set()


class KnowledgeMigrationExecutionService:
    def __init__(
        self,
        *,
        repository_factory: KnowledgeMigrationRepositoryContextFactory,
        lock_repository: KnowledgeMigrationLockRepository,
        operations: BatchMigrationOperations,
        dispatcher: KnowledgeMigrationTaskDispatcher,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        execution_batch_size: int = 20,
    ):
        self.repository_factory = repository_factory
        self.lock_repository = lock_repository
        self.operations = operations
        self.dispatcher = dispatcher
        self.lease_ttl_seconds = lease_ttl_seconds
        self.execution_batch_size = min(100, max(1, int(execution_batch_size)))
        self.checkpoint_store = DatabaseMigrationCheckpointStore(
            repository_factory
        )

    async def _claim_oldest_batch(self, worker_task_id: str | None):
        async with self.repository_factory() as repository:
            batch = await repository.find_oldest_queued_batch()
            if batch is None:
                return None
            now = datetime.now()
            changed = await repository.compare_and_set_batch_status(
                int(batch.id),
                {KnowledgeMigrationBatchStatus.QUEUED.value},
                KnowledgeMigrationBatchStatus.RUNNING.value,
                execution_task_id=worker_task_id,
                started_at=batch.started_at or now,
                finished_at=None,
            )
            if not changed:
                await repository.rollback()
                return None
            await repository.commit()
            return {
                "id": int(batch.id),
                "round_no": int(batch.round_no),
            }

    async def _claim_units(
        self,
        *,
        batch_id: int,
        round_no: int,
        execution_token: str,
        worker_task_id: str | None,
    ):
        async with self.repository_factory() as repository:
            claimed = await repository.claim_next_units(
                limit=self.execution_batch_size,
                batch_id=batch_id,
                round_no=round_no,
                execution_token=execution_token,
                worker_task_id=worker_task_id,
            )
            await repository.commit()
            return [
                MigrationExecutionUnit(
                    unit_id=int(unit.id),
                    checkpoint=unit.checkpoint,
                    attempt_id=int(attempt.id),
                    execution_token=execution_token,
                    restart_pre_switch=int(unit.attempt_count) > 1,
                )
                for unit, attempt in claimed
            ]

    async def _finish_units(self, batch_id, units, results) -> bool:
        values = []
        for unit, result in zip(units, results):
            if result.interrupted:
                continue
            values.append(
                {
                    "attempt_id": unit.attempt_id,
                    "unit_status": "succeeded" if result.succeeded else "failed",
                    "checkpoint": result.checkpoint,
                    "result": "succeeded" if result.succeeded else "failed",
                    "reason_code": None
                    if result.succeeded
                    else ("source_cleanup_pending" if result.source_cleanup_pending else "unit_execution_failed"),
                    "error_summary": sanitize_error_summary(result.error_summary),
                }
            )
        async with self.repository_factory() as repository:
            if not await repository.finish_attempts(values, execution_token=units[0].execution_token):
                await repository.rollback()
                return False
            await repository.recompute_progress(batch_id)
            await repository.commit()
        return not any(result.interrupted for result in results)

    async def _finish_unit(
        self,
        *,
        attempt_id: int,
        execution_token: str,
        result,
    ) -> bool:
        if result.interrupted:
            return False
        async with self.repository_factory() as repository:
            if result.succeeded:
                finished = await repository.finish_attempt(
                    attempt_id=attempt_id,
                    execution_token=execution_token,
                    unit_status=KnowledgeMigrationUnitStatus.SUCCEEDED.value,
                    checkpoint=result.checkpoint,
                    result=KnowledgeMigrationAttemptResult.SUCCEEDED.value,
                )
            else:
                reason_code = "source_cleanup_pending" if result.source_cleanup_pending else "unit_execution_failed"
                finished = await repository.finish_attempt(
                    attempt_id=attempt_id,
                    execution_token=execution_token,
                    unit_status=KnowledgeMigrationUnitStatus.FAILED.value,
                    checkpoint=result.checkpoint,
                    result=KnowledgeMigrationAttemptResult.FAILED.value,
                    reason_code=reason_code,
                    error_summary=sanitize_error_summary(
                        result.error_summary
                    ),
                )
            if not finished:
                await repository.rollback()
                return False
            await repository.commit()
            return True

    async def _finish_batch(
        self,
        *,
        batch_id: int,
        round_no: int,
        lease_lost: bool,
    ) -> str:
        async with self.repository_factory() as repository:
            if lease_lost:
                await repository.mark_remaining_unprocessed(
                    batch_id,
                    round_no=round_no,
                    reason_code="global_lease_lost",
                    summary="全局执行租约丢失, 剩余单元未处理",
                )
            progress = await repository.recompute_progress(batch_id)
            terminal_status = aggregate_batch_status(progress)
            changed = await repository.compare_and_set_batch_status(
                batch_id,
                {KnowledgeMigrationBatchStatus.RUNNING.value},
                terminal_status,
                finished_at=datetime.now(),
                last_error_code=(
                    "global_lease_lost" if lease_lost else None
                ),
                last_error_summary=(
                    "全局执行租约丢失, 剩余单元可在同批次重试"
                    if lease_lost
                    else None
                ),
            )
            if not changed:
                await repository.rollback()
                return KnowledgeMigrationBatchStatus.FAILED.value
            await repository.commit()
            return terminal_status

    async def _wake_next_batch(self) -> None:
        async with self.repository_factory() as repository:
            next_batch = await repository.find_oldest_queued_batch()
            if next_batch is None:
                return
            batch_id = int(next_batch.id)
            round_no = int(next_batch.round_no)
        try:
            self.dispatcher.dispatch_execution(batch_id, round_no)
        except Exception:
            # queued 状态仍是 DB 真相源, reconcile 会再次投递.
            return

    async def execute(
        self,
        *,
        requested_batch_id: int,
        requested_round_no: int,
        worker_task_id: str | None = None,
    ) -> dict[str, object]:
        """竞争全局租约后始终执行数据库中的最早 queued 批次。"""

        execution_token = uuid4().hex
        acquired = await self.lock_repository.acquire(
            execution_token,
            ttl_seconds=self.lease_ttl_seconds,
        )
        if not acquired:
            return {
                "acquired": False,
                "requested_batch_id": requested_batch_id,
                "requested_round_no": requested_round_no,
            }

        heartbeat = _LeaseHeartbeat(
            lock_repository=self.lock_repository,
            repository_factory=self.repository_factory,
            token=execution_token,
            ttl_seconds=self.lease_ttl_seconds,
        )
        heartbeat_task = asyncio.create_task(heartbeat.run())
        claimed_batch = None
        terminal_status = None
        ownership_lost = False
        try:
            claimed_batch = await self._claim_oldest_batch(worker_task_id)
            if claimed_batch is None:
                return {
                    "acquired": True,
                    "executed": False,
                }
            batch_id = int(claimed_batch["id"])
            round_no = int(claimed_batch["round_no"])
            heartbeat.batch_id = batch_id

            from dataclasses import replace

            while not heartbeat.lost.is_set():
                units = await self._claim_units(
                    batch_id=batch_id, round_no=round_no, execution_token=execution_token, worker_task_id=worker_task_id
                )
                if not units:
                    break
                units = [replace(unit, cancelled=heartbeat.lost.is_set) for unit in units]
                if hasattr(self.operations, "prepare_batch"):
                    await self.operations.prepare_batch(units)
                results = await execute_units(
                    units, self.operations, BatchMigrationCheckpointStore(self.repository_factory)
                )
                if not await self._finish_units(batch_id, units, results):
                    ownership_lost = True
                    break

            ownership_lost = ownership_lost or heartbeat.lost.is_set()
            if ownership_lost:
                return {
                    "acquired": True,
                    "executed": True,
                    "batch_id": batch_id,
                    "round_no": round_no,
                    "status": "lease_lost",
                    "requested_batch_id": requested_batch_id,
                }
            await self.operations.cleanup_empty_source_folders(batch_id)
            if heartbeat.lost.is_set():
                ownership_lost = True
                return {
                    "acquired": True,
                    "executed": True,
                    "batch_id": batch_id,
                    "round_no": round_no,
                    "status": "lease_lost",
                    "requested_batch_id": requested_batch_id,
                }
            terminal_status = await self._finish_batch(
                batch_id=batch_id,
                round_no=round_no,
                lease_lost=False,
            )
            return {
                "acquired": True,
                "executed": True,
                "batch_id": batch_id,
                "round_no": round_no,
                "status": terminal_status,
                "requested_batch_id": requested_batch_id,
            }
        finally:
            heartbeat.stop()
            await heartbeat_task
            await self.lock_repository.release(execution_token)
            if claimed_batch is not None and not ownership_lost:
                await self._wake_next_batch()


class KnowledgeMigrationReconcileService:
    def __init__(
        self,
        *,
        repository_factory: KnowledgeMigrationRepositoryContextFactory,
        lock_repository: KnowledgeMigrationLockRepository,
        dispatcher: KnowledgeMigrationTaskDispatcher,
        stale_seconds: int = DEFAULT_RECONCILE_STALE_SECONDS,
        max_recoveries: int = DEFAULT_RECONCILE_MAX_RECOVERIES,
    ):
        self.repository_factory = repository_factory
        self.lock_repository = lock_repository
        self.dispatcher = dispatcher
        self.stale_seconds = stale_seconds
        self.max_recoveries = max(1, int(max_recoveries))

    async def reconcile(self, *, limit: int = 100) -> int:
        now = datetime.now()
        older_than = now - timedelta(seconds=self.stale_seconds)
        statuses = {"preflight_queued", "preflighting", "queued", "running"}
        if await self.lock_repository.is_locked():
            # 正式迁移占用执行器时只扫描预检, 避免排队批次挤占扫描额度。
            statuses -= {"queued", "running"}
        async with self.repository_factory() as repository:
            batches = await repository.list_reconcile_candidates(
                statuses,
                older_than=older_than,
                now=now,
                limit=max(1, min(int(limit), 100)),
            )
            candidates = [(int(batch.id), batch.status, int(batch.round_no)) for batch in batches]

        dispatched = 0
        for batch_id, status, round_no in candidates:
            token = None
            try:
                if status in {"queued", "running"}:
                    # 与执行 worker 竞争同一租约, 避免先查无锁后接管的竞态。
                    token = uuid4().hex
                    if not await self.lock_repository.acquire(token, ttl_seconds=DEFAULT_LEASE_TTL_SECONDS):
                        token = None
                        continue
                async with self.repository_factory() as repository:
                    recovered = await repository.claim_reconcile_batch(
                        batch_id,
                        expected_status=status,
                        expected_round_no=round_no,
                        older_than=older_than,
                        now=now,
                        max_recoveries=self.max_recoveries,
                    )
                    delivery = (recovered.status, int(recovered.round_no)) if recovered else None
                    await repository.commit()
            except Exception:
                logger.exception("迁移恢复领取失败 batch_id={}", batch_id)
                continue
            finally:
                if token is not None:
                    await self.lock_repository.release(token)

            if delivery is None:
                continue
            try:
                if delivery[0] == KnowledgeMigrationBatchStatus.PREFLIGHT_QUEUED.value:
                    self.dispatcher.dispatch_preflight(batch_id)
                else:
                    self.dispatcher.dispatch_execution(batch_id, delivery[1])
                dispatched += 1
            except Exception:
                # 保留已提交的预算和退避, 单条发布失败不阻塞后续批次。
                logger.exception("迁移恢复投递失败 batch_id={}", batch_id)
        return dispatched
