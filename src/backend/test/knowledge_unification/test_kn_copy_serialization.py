"""Copy API/worker exclusion with native SQL and projection journals.

SQLite ignores FOR UPDATE. The fixture supplies only that lock primitive;
production MySQL/DM8 lock behavior remains an integration-test boundary.
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.permission import PermissionProjectionFailedError, PermissionPublishNotReadyError
from bisheng.knowledge.application.space_copy_owner import SpaceCopyOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob as Job
from bisheng.knowledge.domain.repositories.space_copy_repository import SpaceCopyRepository
from bisheng.knowledge.domain.schemas.processing_job import ProcessingRetryRequest
from bisheng.permission.domain.models import PermissionProjectionOperation
from test.knowledge_unification.test_kn_copy import (
    actual_processing_task as actual_processing_task,
)
from test.knowledge_unification.test_kn_copy import (
    admission as admission,
)
from test.knowledge_unification.test_kn_copy import (
    application as application,
)
from test.knowledge_unification.test_kn_copy import (
    business as business,
)
from test.knowledge_unification.test_kn_copy import (
    command,
)
from test.knowledge_unification.test_kn_copy import (
    copying as copying,
)
from test.knowledge_unification.test_kn_copy import (
    job_tenant as job_tenant,
)
from test.knowledge_unification.test_kn_copy import (
    processing as processing,
)
from test.knowledge_unification.test_kn_copy import (
    store as store,
)
from test.knowledge_unification.test_kn_copy import (
    tenant as tenant,
)


@pytest.fixture
async def serialized(copying, monkeypatch):
    app = copying.app
    original_sessions, original_root = app.sessions, SpaceCopyRepository.aroot
    row_lock, waiting = asyncio.Lock(), asyncio.Event()
    held = {}

    @asynccontextmanager
    async def sessions():
        async with original_sessions() as session:
            try:
                yield session
            finally:
                if session in held:
                    del held[session]
                    row_lock.release()

    async def root(repository, session, space_id, *, lock=False):
        if lock:
            if space_id == 40 and session not in held:
                if row_lock.locked():
                    waiting.set()
                await row_lock.acquire()
                held[session] = asyncio.current_task()
            session.info.setdefault("copy_lock_order", []).append(space_id)
        return await original_root(repository, session, space_id, lock=lock)

    monkeypatch.setattr(app, "sessions", sessions)
    monkeypatch.setattr(SpaceCopyRepository, "aroot", root)
    return copying, held, waiting


async def test_confirm_waits_for_usable_setup_and_worker_shares_original_projection_exclusion(serialized, monkeypatch):
    copying, held, waiting = serialized
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Concurrent copy", identity=ctx.user)
    staged, release = asyncio.Event(), asyncio.Event()
    original_write = copying.transport.write_atomic
    callers = []

    async def write(**kwargs):
        task = asyncio.current_task()
        assert any(owner is task and session.info["copy_lock_order"][:2] == [40, 41] for session, owner in held.items())
        callers.append(task)
        if not staged.is_set():
            staged.set()
            await release.wait()
        return await original_write(**kwargs)

    monkeypatch.setattr(copying.transport, "write_atomic", write)
    initialize = AsyncMock()
    monkeypatch.setattr(SpaceCopyOwner, "_initialize", initialize)
    api = asyncio.create_task(app.aconfirm(40, command(plan), identity=ctx.user))
    worker = None
    try:
        await asyncio.wait_for(staged.wait(), 5)
        assert not api.done()
        async with ctx.sessions() as session:
            job = (await session.execute(sa.select(Job))).scalars().one()
            job_id = job.id
            assert (await session.get(Knowledge, job.space_id)).state == 0
        waiting.clear()
        worker = asyncio.create_task(SpaceCopyOwner(app).astart(job_id, 0))
        await asyncio.wait_for(waiting.wait(), 5)
        assert callers == [api]
        release.set()
        result, lease = await asyncio.wait_for(asyncio.gather(api, worker), 10)
        assert lease is not None and result["knowledge"].state == 1
        initialize.assert_awaited_once()
        async with ctx.sessions() as session:
            operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
            assert len(operations) == 3 and all(row.status == "FINALIZED" for row in operations)
            job = await session.get(Job, job_id)
            assert job.state == "running" and job.error_code is None
    finally:
        release.set()
        for task in (api, worker):
            if task is not None and not task.done():
                task.cancel()
        results = await asyncio.gather(*(task for task in (api, worker) if task is not None), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result
    assert not held


async def test_failed_closed_after_commit_reuses_the_original_journal_and_releases_locks(
    serialized, monkeypatch, actual_processing_task
):
    copying, held, _ = serialized
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Recover original copy", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    target_id, job_id = accepted["knowledge"].id, accepted["processing_job"].job_id
    projection = app.projection.composition.components.projection
    original_transition = projection._transition

    async def fail_after_write(operation, *, expected, target, **kwargs):
        if expected == "STAGING" and target == "COMMITTED":
            _, frozen = await projection._load_operation_plan(operation.id)
            await projection._mark_failed_closed(frozen, operation, reason="simulated concurrent observer")
        return await original_transition(operation, expected=expected, target=target, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(projection, "_transition", fail_after_write)
        with pytest.raises(PermissionProjectionFailedError):
            await SpaceCopyOwner(app).aensure_logical(target_id, job_id, identity=ctx.user, entry_kind="web")
    assert not held
    async with ctx.sessions() as session:
        operation = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().one()
        original_id = operation.id
        assert operation.status == "FAILED_CLOSED"
        assert (await session.get(Knowledge, target_id)).state == 0
    owner = SpaceCopyOwner(app)
    failed = await owner.afail(job_id, 0, error_code=PermissionProjectionFailedError.Code)
    assert failed.state == "failed" and failed.failed_count == failed.total_count
    from bisheng.knowledge.application import move_processing_access, space_copy_access
    from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess

    # The target mirror does not exist yet. Recovery must authenticate the
    # original copy/source rather than require target edit permission first.
    target_permission = AsyncMock(side_effect=PermissionPublishNotReadyError())
    monkeypatch.setattr(space_copy_access, "require_business_action", target_permission)
    monkeypatch.setattr(move_processing_access, "batch_check_business_actions", AsyncMock(return_value={}))
    access = SpaceCopyAccess(owner)
    page = await access.alist(target_id, identity=ctx.user, page=1, page_size=20)
    assert page.total == 1 and page.data[0].id == job_id
    assert page.data[0].retryable and page.data[0].hidden_item_count == failed.total_count
    assert (await access.aget(target_id, job_id, identity=ctx.user)).error_code == 25009
    retried = await access.aretry(
        target_id,
        job_id,
        ProcessingRetryRequest(idempotency_key="recover-original", expected_job_revision=failed.revision),
        identity=ctx.user,
    )
    target_permission.assert_not_awaited()
    assert retried.job_id == job_id and retried.state == "accepted"
    assert not held
    async with ctx.sessions() as session:
        assert (await session.get(Knowledge, target_id)).state == 0
        assert (await session.get(PermissionProjectionOperation, original_id)).status == "FAILED_CLOSED"
    current, _ = await owner.aread(job_id)
    await owner.astart(job_id, current.revision)
    async with ctx.sessions() as session:
        operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert len(operations) == 3 and all(row.status == "FINALIZED" for row in operations)
        assert original_id in {row.id for row in operations}
        assert (await session.get(Knowledge, target_id)).state == 1


async def test_uninitialized_copy_task_access_requires_creator_and_current_source_authority(copying, monkeypatch):
    from bisheng.common.errcode.permission import PermissionDeniedError
    from bisheng.knowledge.application import space_copy as admission
    from bisheng.knowledge.application import space_copy_access
    from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess
    from bisheng.permission.application.identity import PermissionActor

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Uninitialized copy", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    target_id, job_id = accepted["knowledge"].id, accepted["processing_job"].job_id
    access = SpaceCopyAccess(SpaceCopyOwner(app))
    with monkeypatch.context() as patch:
        patch.setattr(
            space_copy_access,
            "resolve_permission_actor",
            AsyncMock(return_value=PermissionActor(user_id=8, tenant_id=101)),
        )
        with pytest.raises(PermissionDeniedError):
            await access.alist(target_id, identity=ctx.user, page=1, page_size=20)
    with monkeypatch.context() as patch:
        patch.setattr(admission, "require_business_action", AsyncMock(side_effect=PermissionDeniedError()))
        with pytest.raises(PermissionDeniedError):
            await access.aget(target_id, job_id, identity=ctx.user)


async def test_uninitialized_copy_retries_despite_unrelated_source_schema_changes(
    copying, monkeypatch, actual_processing_task
):
    from bisheng.knowledge.application import move_processing_access
    from bisheng.knowledge.application.space_copy_access import SpaceCopyAccess

    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Changed source", identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    target_id, job_id = accepted["knowledge"].id, accepted["processing_job"].job_id
    async with ctx.sessions() as session, session.begin():
        source = await session.get(Knowledge, 40)
        source.metadata_schema_revision += 1
    monkeypatch.setattr(move_processing_access, "batch_check_business_actions", AsyncMock(return_value={}))
    access = SpaceCopyAccess(SpaceCopyOwner(app))
    assert (await access.aget(target_id, job_id, identity=ctx.user)).id == job_id
    failed = await SpaceCopyOwner(app).afail(job_id, 0, error_code=10998)
    retried = await access.aretry(
        target_id,
        job_id,
        ProcessingRetryRequest(idempotency_key="independent-source-schema", expected_job_revision=failed.revision),
        identity=ctx.user,
    )
    assert retried.state == "accepted"
    async with ctx.sessions() as session:
        operations = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().all()
        assert not operations
        assert (await session.get(Knowledge, target_id)).state == 0


async def test_cancelled_executor_releases_sql_exclusion_and_resumes_the_original_commit(serialized, monkeypatch):
    copying, held, _ = serialized
    app, ctx = copying.app, copying.ctx
    plan = await app.aprecheck(40, name="Interrupted copy", identity=ctx.user)
    committed, pause = asyncio.Event(), asyncio.Event()
    original_write = copying.transport.write_atomic

    async def write(**kwargs):
        result = await original_write(**kwargs)
        if any(row.phase == "COMMIT" for row in kwargs["writes"]):
            committed.set()
            await pause.wait()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(SpaceCopyOwner, "aensure_logical", AsyncMock())
        accepted = await app.aconfirm(40, command(plan), identity=ctx.user)
    with monkeypatch.context() as patch:
        patch.setattr(copying.transport, "write_atomic", write)
        api = asyncio.create_task(
            SpaceCopyOwner(app).aensure_logical(accepted["knowledge"].id, accepted["processing_job"].job_id)
        )
        try:
            await asyncio.wait_for(committed.wait(), 5)
        finally:
            api.cancel()
            with pytest.raises(asyncio.CancelledError):
                await api
    assert not held
    async with ctx.sessions() as session:
        job = (await session.execute(sa.select(Job))).scalars().one()
        original = (await session.execute(sa.select(PermissionProjectionOperation))).scalars().one()
        job_id, target_id, operation_id = job.id, job.space_id, original.id
        assert original.status == "STAGING"
    await SpaceCopyOwner(app).aensure_logical(target_id, job_id, identity=ctx.user, entry_kind="web")
    assert not held
    async with ctx.sessions() as session:
        original = await session.get(PermissionProjectionOperation, operation_id)
        assert original.status == "FINALIZED"
        assert (await session.get(Knowledge, target_id)).state == 1
