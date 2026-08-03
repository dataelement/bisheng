from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.services.file_migration.state import (
    calculate_progress,
)
from bisheng.knowledge.domain.services.knowledge_migration_executor import (
    KnowledgeMigrationExecutionService,
    KnowledgeMigrationReconcileService,
)


class FakeRepository:
    def __init__(self):
        self.batch = SimpleNamespace(
            id=1,
            round_no=1,
            status="queued",
            started_at=None,
        )
        self.units = [
            SimpleNamespace(
                id=10,
                status="planned",
                checkpoint="planned",
                attempt_count=0,
            ),
            SimpleNamespace(
                id=11,
                status="planned",
                checkpoint="planned",
                attempt_count=0,
            ),
        ]
        self.attempt_by_id = {}
        self.next_attempt_id = 100
        self.recovered_running = 0

    async def find_oldest_queued_batch(self):
        return self.batch if self.batch.status == "queued" else None

    async def compare_and_set_batch_status(
        self,
        batch_id,
        expected,
        target,
        **values,
    ):
        if batch_id != self.batch.id or self.batch.status not in expected:
            return False
        self.batch.status = target
        for key, value in values.items():
            setattr(self.batch, key, value)
        return True

    async def claim_next_unit(
        self,
        *,
        batch_id,
        round_no,
        execution_token,
        worker_task_id,
    ):
        del round_no, worker_task_id
        if batch_id != self.batch.id or self.batch.status != "running":
            return None
        unit = next(
            (item for item in self.units if item.status == "planned"),
            None,
        )
        if unit is None:
            return None
        unit.status = "running"
        unit.attempt_count += 1
        attempt = SimpleNamespace(
            id=self.next_attempt_id,
            unit_id=unit.id,
            attempt_no=unit.attempt_count,
            execution_token=execution_token,
            result="running",
        )
        self.next_attempt_id += 1
        self.attempt_by_id[attempt.id] = attempt
        return unit, attempt

    async def is_attempt_active(self, *, attempt_id, execution_token):
        attempt = self.attempt_by_id.get(attempt_id)
        if attempt is None or attempt.execution_token != execution_token:
            return False
        unit = next(item for item in self.units if item.id == attempt.unit_id)
        return attempt.result == "running" and unit.status == "running" and unit.attempt_count == attempt.attempt_no

    async def update_checkpoint(
        self,
        unit_id,
        checkpoint,
        *,
        attempt_id,
        execution_token,
    ):
        if not await self.is_attempt_active(
            attempt_id=attempt_id,
            execution_token=execution_token,
        ):
            return False
        next(item for item in self.units if item.id == unit_id).checkpoint = checkpoint
        return True

    async def reset_after_compensation(
        self,
        unit_id,
        *,
        attempt_id,
        execution_token,
    ):
        if not await self.is_attempt_active(
            attempt_id=attempt_id,
            execution_token=execution_token,
        ):
            return False
        next(item for item in self.units if item.id == unit_id).checkpoint = "planned"
        return True

    async def finish_attempt(
        self,
        *,
        attempt_id,
        execution_token,
        unit_status,
        checkpoint,
        result,
        reason_code=None,
        error_summary=None,
    ):
        del reason_code, error_summary
        attempt = self.attempt_by_id[attempt_id]
        if not await self.is_attempt_active(
            attempt_id=attempt_id,
            execution_token=execution_token,
        ):
            return False
        unit = next(item for item in self.units if item.id == attempt.unit_id)
        unit.status = unit_status
        unit.checkpoint = checkpoint
        attempt.result = result
        return True

    async def recompute_progress(self, batch_id):
        assert batch_id == self.batch.id
        return calculate_progress(item.status for item in self.units)

    async def mark_remaining_unprocessed(self, *args, **kwargs):
        del args, kwargs
        for unit in self.units:
            if unit.status in {"planned", "running"}:
                unit.status = "unprocessed"

    async def touch_running_batch(self, *args, **kwargs):
        del args, kwargs
        return True

    async def list_reconcile_candidates(
        self,
        statuses,
        *,
        older_than,
        limit,
    ):
        del older_than, limit
        return [self.batch] if self.batch.status in statuses else []

    async def recover_stale_running_batch(
        self,
        batch_id,
        *,
        queued_at,
    ):
        del queued_at
        assert batch_id == self.batch.id
        self.recovered_running += 1
        self.batch.status = "queued"
        return True

    async def commit(self):
        return None

    async def rollback(self):
        return None


class FakeRepositoryFactory:
    def __init__(self, repository):
        self.repository = repository

    @asynccontextmanager
    async def __call__(self):
        yield self.repository


class FakeLock:
    def __init__(self):
        self.value = None
        self.released = False

    async def acquire(self, token, *, ttl_seconds):
        del ttl_seconds
        if self.value is not None:
            return False
        self.value = token
        return True

    async def renew(self, token, *, ttl_seconds):
        del ttl_seconds
        return self.value == token

    async def release(self, token):
        if self.value != token:
            return False
        self.value = None
        self.released = True
        return True

    async def is_locked(self):
        return self.value is not None


class FakeOperations:
    def __init__(self):
        self.calls = []

    async def _call(self, name, unit):
        self.calls.append((unit.unit_id, name))
        if unit.unit_id == 10 and name == "verify_target":
            raise RuntimeError("injected")

    async def create_target_rows(self, unit):
        await self._call("create_target_rows", unit)

    async def copy_target_objects(self, unit):
        await self._call("copy_target_objects", unit)

    async def build_target_indexes(self, unit):
        await self._call("build_target_indexes", unit)

    async def write_target_permissions(self, unit):
        await self._call("write_target_permissions", unit)

    async def verify_target(self, unit):
        await self._call("verify_target", unit)

    async def switch_database(self, unit):
        await self._call("switch_database", unit)

    async def cleanup_source_external(self, unit):
        await self._call("cleanup_source_external", unit)

    async def cleanup_source_rows(self, unit):
        await self._call("cleanup_source_rows", unit)

    async def cleanup_new_target(self, unit):
        await self._call("cleanup_new_target", unit)

    async def cleanup_empty_source_folders(self, batch_id):
        self.calls.append((batch_id, "cleanup_empty_source_folders"))


class FakeDispatcher:
    def dispatch_preflight(self, batch_id):
        del batch_id
        return None

    def dispatch_execution(self, batch_id, round_no):
        del batch_id, round_no
        return None


@pytest.mark.asyncio
async def test_execution_uses_oldest_batch_and_continues_after_unit_failure():
    repository = FakeRepository()
    lock = FakeLock()
    operations = FakeOperations()
    service = KnowledgeMigrationExecutionService(
        repository_factory=FakeRepositoryFactory(repository),
        lock_repository=lock,
        operations=operations,
        dispatcher=FakeDispatcher(),
        lease_ttl_seconds=60,
    )

    result = await service.execute(
        requested_batch_id=99,
        requested_round_no=9,
        worker_task_id="task-1",
    )

    assert result["batch_id"] == 1
    assert result["requested_batch_id"] == 99
    assert result["status"] == "partial_success"
    assert [unit.status for unit in repository.units] == [
        "failed",
        "succeeded",
    ]
    assert (11, "switch_database") in operations.calls
    assert lock.released is True


@pytest.mark.asyncio
async def test_reconcile_does_not_take_over_while_global_lease_exists():
    repository = FakeRepository()
    repository.batch.status = "running"
    lock = FakeLock()
    lock.value = "active-token"
    service = KnowledgeMigrationReconcileService(
        repository_factory=FakeRepositoryFactory(repository),
        lock_repository=lock,
        dispatcher=FakeDispatcher(),
        stale_seconds=1,
    )

    recovered = await service.reconcile(limit=10)

    assert recovered == 0
    assert repository.recovered_running == 0
    assert repository.batch.status == "running"
