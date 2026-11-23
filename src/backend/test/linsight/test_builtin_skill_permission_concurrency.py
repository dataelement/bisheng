"""Exercise bootstrap races through the real F048 SQL journal and services.

SQLite ignores FOR UPDATE: only that database primitive is supplied here.
The disposable-database tests separately exercise native connection locking.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionInvalidResourceError, PermissionProjectionFailedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.linsight.domain.models.linsight_skill import LinsightSkill
from bisheng.linsight.domain.repositories import skill_permission as persistence
from bisheng.linsight.domain.services.skill_permission import ensure_builtin_skill_permission
from bisheng.permission.application import process_runtime
from bisheng.permission.domain.models import PermissionGrant, PermissionProjectionOperation, ResourcePermissionMode
from test.permission.test_f048_projection_service import FakeFGAProjection
from test.permission.test_f048_system_resource_repair import repair_env as repair_env


def builtin(ident=902, **changes):
    values = {
        "id": ident,
        "tenant_id": 1,
        "name": f"builtin-{ident}",
        "description": "Bootstrap regression fixture",
        "source": "builtin",
        "owner_user_id": 0,
        "object_path": f"skills/{ident}.zip",
    }
    return LinsightSkill(**(values | changes))


@pytest.fixture
async def skills(repair_env, monkeypatch):
    env = repair_env
    async with env.factory() as session:
        session.add_all([builtin(), builtin(903)])
        await session.commit()

    locks, held = {}, {}
    attempted = asyncio.Event()

    @asynccontextmanager
    async def sessions():
        async with env.factory() as session:
            original = session.exec

            async def execute(statement, *args, **kwargs):
                if statement._for_update_arg is not None:
                    ident = statement.compile().params["id_1"]
                    key = (get_current_tenant_id(), ident)
                    attempted.set()
                    lock = locks.setdefault(key, asyncio.Lock())
                    await lock.acquire()
                    held[session] = lock
                return await original(statement, *args, **kwargs)

            monkeypatch.setattr(session, "exec", execute)
            try:
                yield session
            finally:
                if session in held:
                    held.pop(session).release()

    monkeypatch.setattr(persistence, "get_async_db_session", sessions)
    monkeypatch.setattr(
        process_runtime,
        "get_f048_process_runtime",
        AsyncMock(return_value=SimpleNamespace(components=SimpleNamespace(facade=env.runtime))),
    )
    return SimpleNamespace(env=env, held=held, attempted=attempted)


async def cancel_pending(*tasks):
    pending = [task for task in tasks if task is not None and not task.done()]
    for task in pending:
        task.cancel()
    for result in await asyncio.gather(*pending, return_exceptions=True):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


async def snapshot(env):
    async with env.factory() as session:
        operations = (await session.exec(select(PermissionProjectionOperation))).all()
        modes = (await session.exec(select(ResourcePermissionMode))).all()
        grants = (await session.exec(select(PermissionGrant))).all()
    return operations, modes, grants


async def test_two_startups_wait_for_the_same_skill_and_recheck_current(skills, monkeypatch):
    env = skills.env
    staged, release = asyncio.Event(), asyncio.Event()
    original = env.fga.write_atomic

    async def write(**kwargs):
        if not staged.is_set():
            staged.set()
            await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(env.fga, "write_atomic", write)
    first = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
    second = signal = None
    try:
        await asyncio.wait_for(staged.wait(), 5)
        skills.attempted.clear()
        second = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
        signal = asyncio.create_task(skills.attempted.wait())
        done, _ = await asyncio.wait((second, signal), timeout=5, return_when=asyncio.FIRST_COMPLETED)
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 5)
        assert outcomes == [None, None], outcomes
        assert signal in done and second not in done
        operations, modes, grants = await snapshot(env)
        assert len(operations) == len(modes) == len(grants) == 1
        assert operations[0].status == "FINALIZED"
        assert modes[0].projection_state == grants[0].projection_state == "CURRENT"
        assert modes[0].version == 1 and grants[0].state == "ACTIVE"
        assert len(env.fga.calls) == 2  # The waiter does not replay STAGE/COMMIT.
        assert ("tenant:1#member", "visible", "linsight_skill:902") in env.fga.present
    finally:
        release.set()
        await cancel_pending(first, second, signal)
    assert not skills.held


async def test_different_skills_progress_while_one_projection_is_paused(skills, monkeypatch):
    env = skills.env
    staged, release = asyncio.Event(), asyncio.Event()

    async def write(**kwargs):
        if kwargs["writes"][0].object == "linsight_skill:902" and not staged.is_set():
            staged.set()
            await release.wait()
        return await FakeFGAProjection.write_atomic(env.fga, **kwargs)

    monkeypatch.setattr(env.fga, "write_atomic", write)
    first = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
    try:
        await asyncio.wait_for(staged.wait(), 5)
        await asyncio.wait_for(ensure_builtin_skill_permission(builtin(903)), 5)
        assert not first.done()
        release.set()
        await asyncio.wait_for(first, 5)
    finally:
        release.set()
        await cancel_pending(first)
    operations, modes, _ = await snapshot(env)
    assert len(operations) == len(modes) == 2
    assert all(row.status == "FINALIZED" for row in operations)
    assert all(row.projection_state == "CURRENT" for row in modes)
    assert not skills.held


async def test_waiter_recovers_the_same_journal_after_first_projection_fails(skills, monkeypatch):
    env = skills.env
    staged, release = asyncio.Event(), asyncio.Event()
    original = env.fga.write_atomic
    env.fga.timeout_mode, env.fga.timeout_call = "mixed", 2

    async def write(**kwargs):
        if not staged.is_set():
            staged.set()
            await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(env.fga, "write_atomic", write)
    first = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
    second = signal = None
    try:
        await asyncio.wait_for(staged.wait(), 5)
        skills.attempted.clear()
        second = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
        signal = asyncio.create_task(skills.attempted.wait())
        await asyncio.wait((second, signal), timeout=5, return_when=asyncio.FIRST_COMPLETED)
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 5)
        assert isinstance(outcomes[0], PermissionProjectionFailedError), outcomes
        assert outcomes[1] is None, outcomes
    finally:
        release.set()
        await cancel_pending(first, second, signal)
    operations, modes, grants = await snapshot(env)
    assert len(operations) == len(modes) == len(grants) == 1
    assert operations[0].status == "FINALIZED"
    assert modes[0].projection_state == grants[0].projection_state == "CURRENT"
    assert grants[0].state == "ACTIVE"
    assert not skills.held


async def test_cancellation_releases_the_skill_lock(skills, monkeypatch):
    staged, release = asyncio.Event(), asyncio.Event()

    async def write(**kwargs):
        staged.set()
        await release.wait()

    monkeypatch.setattr(skills.env.fga, "write_atomic", write)
    first = asyncio.create_task(ensure_builtin_skill_permission(builtin()))
    try:
        await asyncio.wait_for(staged.wait(), 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not skills.held
        async with asyncio.timeout(5):
            async with persistence.SkillPermissionRepository().lock(902, tenant_id=1) as row:
                assert row.id == 902
    finally:
        release.set()
        await cancel_pending(first)


@pytest.mark.parametrize("changes", [{"source": "manual"}, {"owner_user_id": 9}, {"tenant_id": 2}])
async def test_stale_builtin_claim_does_not_authorize_a_changed_business_row(skills, changes):
    async with skills.env.factory() as session:
        row = await session.get(LinsightSkill, 902)
        for key, value in changes.items():
            setattr(row, key, value)
        session.add(row)
        await session.commit()
    with pytest.raises(PermissionInvalidResourceError):
        await ensure_builtin_skill_permission(builtin())
    assert not skills.env.fga.calls
    assert not (await snapshot(skills.env))[0]
    assert not skills.held


async def test_missing_skill_is_not_recreated_as_a_permission_resource(skills):
    with pytest.raises(PermissionInvalidResourceError):
        await ensure_builtin_skill_permission(builtin(999))
    assert not skills.env.fga.calls
    assert not (await snapshot(skills.env))[0]
    assert not skills.held


async def test_restart_does_not_restore_an_administrators_revoked_tenant_grant(skills):
    from bisheng.permission.domain.models import PermissionGrantAssignee

    env = skills.env
    await ensure_builtin_skill_permission(builtin())
    async with env.factory() as session:
        grant = (await session.exec(select(PermissionGrant))).one()
        source = (await session.exec(select(PermissionGrantAssignee))).one()
        grant.state = source.state = "INACTIVE"
        session.add_all([grant, source])
        await session.commit()
    # Revoke the tenant audience without removing technical mode/enable facts.
    env.fga.present = {
        key
        for key in env.fga.present
        if not (key[0] == "tenant:1#member" and key[1] in {"visible", "ordinary_assignee"})
    }
    before = set(env.fga.present)
    calls = len(env.fga.calls)
    await ensure_builtin_skill_permission(builtin())
    assert len(env.fga.calls) == calls and env.fga.present == before
    assert ("tenant:1#member", "visible", "linsight_skill:902") not in env.fga.present
    operations, modes, grants = await snapshot(env)
    assert len(operations) == 1 and operations[0].status == "FINALIZED"
    assert modes[0].version == 1 and grants[0].state == "INACTIVE"
    assert not skills.held
