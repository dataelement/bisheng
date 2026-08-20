from unittest.mock import AsyncMock

import pytest

from bisheng.core.lock import RedisLockLostError
from bisheng.permission.domain.services.relation_binding_mutation_service import (
    RELATION_BINDING_LOCK_KEY,
    RelationBindingMutationService,
)


class FakeLock:
    def __init__(self, key: str):
        self.key = key
        self.lost = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def ensure_owned(self):
        if self.lost:
            raise RedisLockLostError("lost")


async def test_mutations_share_global_lock():
    locks = []

    def lock_factory(key):
        lock = FakeLock(key)
        locks.append(lock)
        return lock

    service = RelationBindingMutationService(
        get_bindings=AsyncMock(return_value=[]),
        save_bindings=AsyncMock(),
        lock_factory=lock_factory,
    )
    await service.mutate(lambda rows: [*rows, {"key": "knowledge"}])
    await service.mutate(lambda rows: [*rows, {"key": "channel"}])

    assert [lock.key for lock in locks] == [RELATION_BINDING_LOCK_KEY, RELATION_BINDING_LOCK_KEY]


async def test_mutation_reads_inside_lock_and_commits_latest_state():
    state = [{"key": "existing"}]

    async def read():
        return [dict(item) for item in state]

    async def save(rows):
        state[:] = [dict(item) for item in rows]

    service = RelationBindingMutationService(
        get_bindings=read,
        save_bindings=save,
        lock_factory=lambda key: FakeLock(key),
    )

    await service.mutate(lambda rows: [*rows, {"key": "new"}])

    assert state == [{"key": "existing"}, {"key": "new"}]


async def test_restore_snapshot():
    save = AsyncMock()
    service = RelationBindingMutationService(
        get_bindings=AsyncMock(return_value=[{"key": "before"}]),
        save_bindings=save,
        lock_factory=lambda key: FakeLock(key),
    )

    async with service.transaction() as transaction:
        await transaction.commit([{"key": "after"}])
        await transaction.restore()

    assert save.await_args_list[0].args[0] == [{"key": "after"}]
    assert save.await_args_list[1].args[0] == [{"key": "before"}]


async def test_restore_snapshot_after_save_applied_then_raised():
    state = [{"key": "before"}]

    async def save(rows):
        state[:] = [dict(item) for item in rows]
        if rows == [{"key": "after"}]:
            raise RuntimeError("refresh failed after commit")

    service = RelationBindingMutationService(
        get_bindings=AsyncMock(return_value=[{"key": "before"}]),
        save_bindings=save,
        lock_factory=lambda key: FakeLock(key),
    )

    async with service.transaction() as transaction:
        with pytest.raises(RuntimeError, match="refresh failed"):
            await transaction.commit([{"key": "after"}])
        await transaction.restore()

    assert state == [{"key": "before"}]


async def test_lock_loss_aborts_commit():
    lock = FakeLock(RELATION_BINDING_LOCK_KEY)
    save = AsyncMock()
    service = RelationBindingMutationService(
        get_bindings=AsyncMock(return_value=[]),
        save_bindings=save,
        lock_factory=lambda key: lock,
    )

    async with service.transaction() as transaction:
        lock.lost = True
        with pytest.raises(RedisLockLostError):
            await transaction.commit([{"key": "unsafe"}])

    save.assert_not_awaited()
