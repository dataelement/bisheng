"""Department concurrency leases.

The Lua-backed cases need a Redis that can run scripts. ``fakeredis[lua]`` is a
dev dependency; when it is unavailable (or built without Lua) those cases skip
instead of failing, so the DAO/limit cases still run everywhere.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _dept(dept_id, parent_id=None, limit=0):
    return SimpleNamespace(
        id=dept_id,
        parent_id=parent_id,
        concurrent_session_limit=limit,
    )


class _AsyncConnection:
    """Awaitable EVAL over a sync fake Redis client."""

    def __init__(self, client):
        self._client = client

    async def eval(self, script, numkeys, *args):
        return self._client.eval(script, numkeys, *args)


class _AsyncRedis:
    def __init__(self, client):
        self.async_connection = _AsyncConnection(client)


@pytest.fixture()
def lease_backend():
    """(fake redis, wrapper) pair; skips when Lua scripting is unavailable."""
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis()
    try:
        client.eval("return redis.call('TIME')[1]", 0)
    except Exception as exc:  # pragma: no cover - depends on the lua extra
        pytest.skip(f"fakeredis without Lua support: {exc}")
    yield client, _AsyncRedis(client)
    client.flushall()


def _patch_departments(depts, primary_dept_id):
    return (
        patch(
            "bisheng.department.domain.services.department_flow_service.UserDepartmentDao.aget_user_primary_department",
            AsyncMock(return_value=SimpleNamespace(department_id=primary_dept_id)),
        ),
        patch(
            "bisheng.department.domain.services.department_flow_service.DepartmentDao.aget_by_id",
            AsyncMock(side_effect=lambda dept_id: depts.get(dept_id)),
        ),
    )


def _patch_redis(wrapper):
    return patch(
        "bisheng.department.domain.services.department_flow_service.get_redis_client",
        AsyncMock(return_value=wrapper),
    )


def _user(user_id):
    return SimpleNamespace(user_id=user_id)


def _keys(client):
    return sorted(k.decode() if isinstance(k, bytes) else k for k in client.keys("*"))


@pytest.mark.asyncio
async def test_resolve_limit_uses_nearest_limited_department():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
    )

    login_user = _user(10)
    depts = {
        3: _dept(3, parent_id=2, limit=0),
        2: _dept(2, parent_id=1, limit=5),
        1: _dept(1, parent_id=None, limit=20),
    }

    primary_patch, dept_patch = _patch_departments(depts, 3)
    with primary_patch, dept_patch:
        # Only the primary department's own limit counts: it is 0, so the
        # parent's 5 must NOT be inherited.
        assert await DepartmentFlowService.resolve_limit_and_dept(login_user) == (0, None)


@pytest.mark.asyncio
async def test_resolve_limit_without_primary_department_is_unlimited():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
    )

    with patch(
        "bisheng.department.domain.services.department_flow_service.UserDepartmentDao.aget_user_primary_department",
        AsyncMock(return_value=None),
    ):
        assert await DepartmentFlowService.resolve_limit_and_dept(_user(10)) == (0, None)


@pytest.mark.asyncio
async def test_slot_acquire_fails_open_when_redis_is_unavailable():
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    # ``ensure_lease`` resolves the department first; without a limit it returns
    # SKIPPED before touching Redis, which would not exercise the fail-open path.
    depts = {2: _dept(2, limit=1)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with (
        primary_patch,
        dept_patch,
        patch(
            "bisheng.department.domain.services.department_flow_service.get_redis_client",
            AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        outcome, lease = await DepartmentFlowService.ensure_lease(_user(10))
        assert outcome is SlotOutcome.SKIPPED
        assert lease is None


@pytest.mark.asyncio
async def test_limit_reached_rejects_third_lease(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    depts = {2: _dept(2, limit=2)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        first, lease_a = await DepartmentFlowService.ensure_lease(_user(10))
        second, lease_b = await DepartmentFlowService.ensure_lease(_user(10))
        third, lease_c = await DepartmentFlowService.ensure_lease(_user(10))

    assert first is SlotOutcome.HELD
    assert second is SlotOutcome.HELD
    assert third is SlotOutcome.REJECTED
    assert lease_c is None
    assert client.zcard("bisheng:dept_flow:2:leases") == 2
    assert {lease_a.lease_id, lease_b.lease_id} == {
        m.decode().split(":", 1)[1] for m in client.zrange("bisheng:dept_flow:2:leases", 0, -1)
    }


@pytest.mark.asyncio
async def test_same_lease_id_renews_without_growing(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    depts = {2: _dept(2, limit=1)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        lease_id = "a" * 32
        first, _ = await DepartmentFlowService.ensure_lease(_user(10), lease_id)
        second, renewed = await DepartmentFlowService.ensure_lease(_user(10), lease_id)

    assert first is SlotOutcome.HELD
    assert second is SlotOutcome.HELD
    assert renewed.lease_id == lease_id
    assert client.zcard("bisheng:dept_flow:2:leases") == 1


@pytest.mark.asyncio
async def test_expired_lease_is_swept_by_next_ensure(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    key = "bisheng:dept_flow:2:leases"
    # Score 1ms after the epoch: expired by any clock.
    client.zadd(key, {"10:" + "a" * 32: 1})
    depts = {2: _dept(2, limit=2)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome, lease = await DepartmentFlowService.ensure_lease(_user(11))

    assert outcome is SlotOutcome.HELD
    members = [m.decode() for m in client.zrange(key, 0, -1)]
    assert members == [f"11:{lease.lease_id}"]


@pytest.mark.asyncio
async def test_release_frees_one_slot_and_is_idempotent(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotLease,
    )

    client, wrapper = lease_backend
    key = "bisheng:dept_flow:2:leases"
    depts = {2: _dept(2, limit=2)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        _, lease_a = await DepartmentFlowService.ensure_lease(_user(10))
        _, lease_b = await DepartmentFlowService.ensure_lease(_user(10))
        await DepartmentFlowService.release_lease(lease_a)
        await DepartmentFlowService.release_lease(lease_a)

    members = [m.decode() for m in client.zrange(key, 0, -1)]
    assert members == [f"10:{lease_b.lease_id}"]

    # Releasing something that was never there must not raise.
    with _patch_redis(wrapper):
        await DepartmentFlowService.release_lease(SlotLease(department_id=2, user_id=99, lease_id="b" * 32))
    assert client.zcard(key) == 1


@pytest.mark.asyncio
async def test_key_deleted_allows_reacquire(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    key = "bisheng:dept_flow:2:leases"
    client.delete(key)
    depts = {2: _dept(2, limit=1)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome, _lease = await DepartmentFlowService.ensure_lease(_user(10), "c" * 32)

    # Nothing is occupying the department, so this can only be HELD.
    assert outcome is SlotOutcome.HELD
    assert [m.decode() for m in client.zrange(key, 0, -1)] == ["10:" + "c" * 32]


@pytest.mark.asyncio
async def test_no_limit_on_primary_department_writes_nothing(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    depts = {
        3: _dept(3, parent_id=2, limit=0),
        2: _dept(2, limit=20),
    }
    primary_patch, dept_patch = _patch_departments(depts, 3)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome, lease = await DepartmentFlowService.ensure_lease(_user(10))

    assert outcome is SlotOutcome.SKIPPED
    assert lease is None
    assert _keys(client) == []


@pytest.mark.asyncio
async def test_lease_written_to_primary_department_key_only(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    depts = {
        3: _dept(3, parent_id=2, limit=5),
        2: _dept(2, limit=20),
    }
    primary_patch, dept_patch = _patch_departments(depts, 3)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome, lease = await DepartmentFlowService.ensure_lease(_user(10))

    assert outcome is SlotOutcome.HELD
    assert lease.department_id == 3
    assert client.zcard("bisheng:dept_flow:3:leases") == 1
    assert client.exists("bisheng:dept_flow:2:leases") == 0


@pytest.mark.asyncio
async def test_user_cannot_renew_or_release_another_users_lease(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotLease,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    key = "bisheng:dept_flow:2:leases"
    depts = {2: _dept(2, limit=1)}
    lease_b_id = "d" * 32
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome_b, _ = await DepartmentFlowService.ensure_lease(_user(11), lease_b_id)
        # Department is now full for everyone: A cannot take B's slot with B's id.
        outcome_a, _ = await DepartmentFlowService.ensure_lease(_user(10), lease_b_id)
        await DepartmentFlowService.release_lease(SlotLease(department_id=2, user_id=10, lease_id=lease_b_id))

    assert outcome_b is SlotOutcome.HELD
    assert outcome_a is SlotOutcome.REJECTED
    # The member is ``{user}:{lease}``, so A's release removed nothing.
    assert [m.decode() for m in client.zrange(key, 0, -1)] == [f"11:{lease_b_id}"]


@pytest.mark.asyncio
async def test_renew_lease_stays_in_original_department(lease_backend):
    from bisheng.department.domain.services.department_flow_service import (
        DepartmentFlowService,
        SlotLease,
        SlotOutcome,
    )

    client, wrapper = lease_backend
    dept_three_key = "bisheng:dept_flow:3:leases"
    lease = SlotLease(department_id=3, user_id=10, lease_id="f" * 32)
    # Lease taken in department 3 before the user was moved to department 2.
    client.zadd(dept_three_key, {f"10:{'f' * 32}": 1})

    # The user's primary department is now 2, but renewing must not re-resolve
    # it — that would take a second lease under department 2 while the release
    # path only removes the department-3 one.
    depts = {2: _dept(2, limit=1), 3: _dept(3, limit=1)}
    primary_patch, dept_patch = _patch_departments(depts, 2)
    with primary_patch, dept_patch, _patch_redis(wrapper):
        outcome = await DepartmentFlowService.renew_lease(lease)

    assert outcome is SlotOutcome.HELD
    assert client.zcard(dept_three_key) == 1
    assert client.exists("bisheng:dept_flow:2:leases") == 0
