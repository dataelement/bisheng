from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationAttempt,
    KnowledgeMigrationAttemptResult,
    KnowledgeMigrationBatch,
    KnowledgeMigrationFile,
    KnowledgeMigrationUnit,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_lock_repository_impl import (
    GLOBAL_MIGRATION_LOCK_KEY,
    KnowledgeMigrationLockRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_repository_impl import (
    KnowledgeMigrationRepositoryImpl,
)


@pytest.fixture()
async def migration_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [
        KnowledgeMigrationBatch.__table__,
        KnowledgeMigrationUnit.__table__,
        KnowledgeMigrationFile.__table__,
        KnowledgeMigrationAttempt.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: [table.create(sync_connection) for table in tables])
    session = AsyncSession(engine, expire_on_commit=False)
    yield session
    await session.close()
    await engine.dispose()


def _batch(request_id: str = "request-1") -> KnowledgeMigrationBatch:
    return KnowledgeMigrationBatch(
        batch_no=f"batch-{request_id}",
        request_id=request_id,
        operator_id=1,
        operator_name="admin",
        source_selection_snapshot=[],
        source_spaces_snapshot=[],
        target_space_id=20,
        target_space_name="目标库",
    )


@pytest.mark.asyncio
async def test_repository_idempotent_create_plan_claim_checkpoint_and_retry(migration_session):
    repo = KnowledgeMigrationRepositoryImpl(migration_session)
    batch, created = await repo.create_batch_idempotent(_batch())
    duplicate, duplicate_created = await repo.create_batch_idempotent(_batch())
    assert created is True
    assert duplicate_created is False
    assert duplicate.id == batch.id

    unit = KnowledgeMigrationUnit(
        batch_id=int(batch.id),
        unit_key="file:10",
        source_space_id=10,
        source_space_name="来源库",
    )
    file_row = KnowledgeMigrationFile(
        batch_id=int(batch.id),
        unit_id=0,
        source_file_id=10,
        source_space_id=10,
        source_space_name="来源库",
        source_file_name="a.pdf",
        target_space_id=20,
        target_space_name="目标库",
        target_file_name="a.pdf",
    )
    await repo.replace_plan(int(batch.id), [(unit, [file_row])])
    assert (await repo.list_units(int(batch.id), page=1, page_size=20)).total == 1
    assert (await repo.list_files(int(unit.id)))[0].source_file_id == 10

    assert await repo.compare_and_set_batch_status(
        int(batch.id),
        {"preflight_queued"},
        "preflighting",
    )
    assert await repo.compare_and_set_batch_status(
        int(batch.id),
        {"preflighting"},
        "queued",
        queued_at=datetime.now(),
    )
    assert await repo.compare_and_set_batch_status(int(batch.id), {"queued"}, "running")
    claimed = await repo.claim_next_unit(
        batch_id=int(batch.id),
        round_no=1,
        execution_token="digest",
        worker_task_id="task-1",
    )
    assert claimed is not None
    claimed_unit, attempt = claimed
    await repo.update_checkpoint(
        int(claimed_unit.id),
        "target_rows_created",
        attempt_id=int(attempt.id),
        execution_token="digest",
    )
    with pytest.raises(ValueError, match="cannot move backwards"):
        await repo.update_checkpoint(
            int(claimed_unit.id),
            "planned",
            attempt_id=int(attempt.id),
            execution_token="digest",
        )
    await repo.finish_attempt(
        attempt_id=int(attempt.id),
        execution_token="digest",
        unit_status="failed",
        checkpoint="target_rows_created",
        result="failed",
        reason_code="injected",
        error_summary="测试失败",
    )
    progress = await repo.recompute_progress(int(batch.id))
    assert progress.failed_count == 1
    await repo.compare_and_set_batch_status(int(batch.id), {"running"}, "failed")
    retried = await repo.retry_batch(int(batch.id), queued_at=datetime.now())
    assert retried is not None
    assert retried.round_no == 2


class _FakeRedisConnection:
    def __init__(self):
        self.value: str | None = None
        self.ttl: int | None = None

    async def set(self, key, value, *, nx, ex):
        assert key == GLOBAL_MIGRATION_LOCK_KEY
        if nx and self.value is not None:
            return False
        self.value = value
        self.ttl = ex
        return True

    async def get(self, key):
        assert key == GLOBAL_MIGRATION_LOCK_KEY
        return self.value

    async def eval(self, script, key_count, key, token, *args):
        assert key_count == 1
        assert key == GLOBAL_MIGRATION_LOCK_KEY
        if self.value != token:
            return 0
        if "expire" in script:
            self.ttl = int(args[0])
            return 1
        self.value = None
        return 1


@pytest.mark.asyncio
async def test_global_lock_uses_token_cas_for_renew_and_release():
    connection = _FakeRedisConnection()
    repo = KnowledgeMigrationLockRepositoryImpl(
        redis_client=SimpleNamespace(async_connection=connection)
    )

    assert await repo.acquire("token-a", ttl_seconds=30) is True
    assert await repo.is_locked() is True
    assert await repo.acquire("token-b", ttl_seconds=30) is False
    assert await repo.renew("token-b", ttl_seconds=60) is False
    assert await repo.release("token-b") is False
    assert connection.value == "token-a"
    assert await repo.renew("token-a", ttl_seconds=60) is True
    assert connection.ttl == 60
    assert await repo.release("token-a") is True
    assert connection.value is None
    assert await repo.is_locked() is False


@pytest.mark.asyncio
async def test_interrupted_attempt_cannot_overwrite_new_attempt(
    migration_session,
):
    repo = KnowledgeMigrationRepositoryImpl(migration_session)
    batch, _ = await repo.create_batch_idempotent(_batch("fencing"))
    unit = KnowledgeMigrationUnit(
        batch_id=int(batch.id),
        unit_key="file:20",
        source_space_id=10,
        source_space_name="来源库",
    )
    file_row = KnowledgeMigrationFile(
        batch_id=int(batch.id),
        unit_id=0,
        source_file_id=20,
        source_space_id=10,
        source_space_name="来源库",
        source_file_name="fenced.pdf",
        target_space_id=20,
        target_space_name="目标库",
        target_file_name="fenced.pdf",
    )
    await repo.replace_plan(int(batch.id), [(unit, [file_row])])
    assert await repo.compare_and_set_batch_status(
        int(batch.id),
        {"preflight_queued"},
        "preflighting",
    )
    assert await repo.compare_and_set_batch_status(
        int(batch.id),
        {"preflighting"},
        "queued",
        queued_at=datetime.now(),
    )
    assert await repo.compare_and_set_batch_status(
        int(batch.id),
        {"queued"},
        "running",
    )

    first_claim = await repo.claim_next_unit(
        batch_id=int(batch.id),
        round_no=1,
        execution_token="token-old",
        worker_task_id="task-old",
    )
    assert first_claim is not None
    _, old_attempt = first_claim
    await repo.mark_remaining_unprocessed(
        int(batch.id),
        round_no=1,
        reason_code="worker_interrupted",
        summary="old worker lost its lease",
    )
    second_claim = await repo.claim_next_unit(
        batch_id=int(batch.id),
        round_no=1,
        execution_token="token-new",
        worker_task_id="task-new",
    )
    assert second_claim is not None
    current_unit, new_attempt = second_claim

    assert (
        await repo.update_checkpoint(
            int(current_unit.id),
            "target_rows_created",
            attempt_id=int(old_attempt.id),
            execution_token="token-old",
        )
        is False
    )
    assert (
        await repo.finish_attempt(
            attempt_id=int(old_attempt.id),
            execution_token="token-old",
            unit_status="failed",
            checkpoint="planned",
            result="failed",
            reason_code="late_old_worker",
        )
        is False
    )

    refreshed = await repo.find_batch_by_id(int(batch.id))
    assert refreshed is not None
    current = await migration_session.get(KnowledgeMigrationUnit, int(current_unit.id))
    old = await migration_session.get(
        KnowledgeMigrationAttempt,
        int(old_attempt.id),
    )
    new = await migration_session.get(
        KnowledgeMigrationAttempt,
        int(new_attempt.id),
    )
    assert current is not None
    assert current.status == "running"
    assert current.checkpoint == "planned"
    assert old is not None
    assert old.result == KnowledgeMigrationAttemptResult.INTERRUPTED.value
    assert new is not None
    assert new.result == KnowledgeMigrationAttemptResult.RUNNING.value
