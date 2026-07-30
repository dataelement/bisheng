import pytest

from bisheng.knowledge.domain.services.file_migration.executor import (
    ExecutionResult,
    MigrationExecutionUnit,
    execute_unit,
)


class FakeOperations:
    def __init__(self, fail_at: str | None = None):
        self.fail_at = fail_at
        self.calls: list[str] = []

    async def _call(self, name: str):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"{name} failed")

    async def create_target_rows(self, unit):
        await self._call("create_target_rows")

    async def copy_target_objects(self, unit):
        await self._call("copy_target_objects")

    async def build_target_indexes(self, unit):
        await self._call("build_target_indexes")

    async def write_target_permissions(self, unit):
        await self._call("write_target_permissions")

    async def verify_target(self, unit):
        await self._call("verify_target")

    async def switch_database(self, unit):
        await self._call("switch_database")

    async def cleanup_source_external(self, unit):
        await self._call("cleanup_source_external")

    async def cleanup_source_rows(self, unit):
        await self._call("cleanup_source_rows")

    async def cleanup_new_target(self, unit):
        await self._call("cleanup_new_target")


class FakeCheckpointStore:
    def __init__(self):
        self.checkpoints: list[str] = []
        self.compensated: list[int] = []

    async def save_checkpoint(self, unit_id: int, checkpoint: str):
        self.checkpoints.append(checkpoint)

    async def reset_after_compensation(self, unit_id: int):
        self.compensated.append(unit_id)


@pytest.mark.asyncio
async def test_pre_switch_failure_preserves_source_and_compensates_new_target():
    operations = FakeOperations(fail_at="verify_target")
    store = FakeCheckpointStore()

    result = await execute_unit(MigrationExecutionUnit(unit_id=1), operations, store)

    assert result == ExecutionResult(
        succeeded=False,
        checkpoint="planned",
        source_cleanup_pending=False,
        error_summary="RuntimeError: verify_target failed",
    )
    assert store.compensated == [1]
    assert "cleanup_new_target" in operations.calls
    assert "switch_database" not in operations.calls
    assert "cleanup_source_rows" not in operations.calls


@pytest.mark.asyncio
async def test_post_switch_failure_keeps_target_and_resumes_source_cleanup():
    operations = FakeOperations(fail_at="cleanup_source_external")
    store = FakeCheckpointStore()

    first = await execute_unit(MigrationExecutionUnit(unit_id=1), operations, store)
    operations.fail_at = None
    second = await execute_unit(
        MigrationExecutionUnit(unit_id=1, checkpoint=first.checkpoint),
        operations,
        store,
    )

    assert first.source_cleanup_pending is True
    assert "cleanup_new_target" not in operations.calls
    assert second.succeeded is True
    assert operations.calls.count("switch_database") == 1
    assert operations.calls.count("create_target_rows") == 1


@pytest.mark.asyncio
async def test_retry_before_switch_cleans_residue_and_restarts_from_planned():
    operations = FakeOperations()
    store = FakeCheckpointStore()

    result = await execute_unit(
        MigrationExecutionUnit(
            unit_id=1,
            checkpoint="target_indexes_built",
            restart_pre_switch=True,
        ),
        operations,
        store,
    )

    assert result.succeeded is True
    assert operations.calls[0] == "cleanup_new_target"
    assert operations.calls.count("create_target_rows") == 1
    assert store.compensated == [1]
