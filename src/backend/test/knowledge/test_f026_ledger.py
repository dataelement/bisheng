"""T005/T056 ledger contracts: SQLite control, opt-in real MySQL and DM8."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance, KnowledgeProviderOperation
from test.knowledge.f026_ledger_database import ledger_engine


@pytest_asyncio.fixture(params=["sqlite", "mysql", "dm8"])
async def ledger(request, tmp_path):
    async with ledger_engine(request.param, tmp_path / "ledger.sqlite") as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            inst = KnowledgeProviderInstance(
                tenant_id=17,
                provider_key="weknora",
                endpoint="fixture",
                credential_ref="fixture-ref",
                remote_scope_id="org",
            )
            session.add(inst)
            await session.flush()
        yield engine, inst.id


@pytest_asyncio.fixture
async def db(ledger):
    engine, instance = ledger
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session, instance


def intent(instance, key, digest="a"):
    return KnowledgeProviderOperation(
        tenant_id=17,
        kind="create_space",
        request_key=key,
        request_hash=digest * 64,
        actor_user_id=57,
        provider_instance_id=instance,
        remote_scope_id="org",
        remote_kb_id="original-kb",
        generation=1,
        operation_epoch=4,
        capability_revision=1,
        phase="create",
        next_attempt_at=datetime(2026, 1, 1),
    )


async def test_replay_and_same_key_different_hash(db):
    from bisheng.knowledge.domain.repositories.provider_operation_repository import (
        ProviderOperationRepository,
        RequestKeyConflict,
    )

    session, instance = db
    repo = ProviderOperationRepository()
    key = uuid4().hex
    first = await repo.accept(session, intent(instance, key))
    replay = await repo.accept(session, intent(instance, key))
    assert replay.operation_id == first.operation_id
    with pytest.raises(RequestKeyConflict):
        await repo.accept(session, intent(instance, key, "b"))
    stored = (
        (
            await session.execute(
                select(KnowledgeProviderOperation).where(
                    KnowledgeProviderOperation.tenant_id == 17, KnowledgeProviderOperation.request_key == key
                )
            )
        )
        .scalars()
        .one()
    )
    assert (stored.request_hash, stored.remote_kb_id) == ("a" * 64, "original-kb")


async def test_expired_sender_can_only_be_reconciled_by_new_owner(db):
    from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository

    session, instance = db
    repo = ProviderOperationRepository()
    row = await repo.accept(session, intent(instance, uuid4().hex))
    target = {"tenant_id": 17, "operation_id": row.operation_id}
    start = datetime(2026, 1, 2)
    old = await repo.claim(session, **target, now=start, lease_seconds=10)
    assert old.state == "sending"
    old_token, old_rev = old.lease_token, old.revision
    assert await repo.claim(session, **target, now=start + timedelta(seconds=3), lease_seconds=10) is None
    now = start + timedelta(seconds=11)
    new = await repo.claim(session, **target, now=now, lease_seconds=10)
    assert new.lease_token != old_token and new.revision > old_rev
    assert (new.state, new.remote_kb_id, new.generation) == ("reconciling", "original-kb", 1)
    for principal, token, revision, generation, epoch in [
        (17, old_token, old_rev, 1, 4),
        (18, new.lease_token, new.revision, 1, 4),
        (17, new.lease_token, new.revision, 2, 4),
        (17, new.lease_token, new.revision, 1, 5),
    ]:
        assert not await repo.apply(
            session,
            tenant_id=principal,
            operation_id=target["operation_id"],
            lease_token=token,
            expected_revision=revision,
            generation=generation,
            operation_epoch=epoch,
            now=now,
            state="applying",
        )
    await session.refresh(new)
    assert new.state == "reconciling"
    assert await repo.apply(
        session,
        **target,
        lease_token=new.lease_token,
        expected_revision=new.revision,
        generation=1,
        operation_epoch=4,
        now=now,
        state="applying",
    )
    await session.refresh(new)
    assert (new.state, new.remote_kb_id) == ("applying", "original-kb")


async def test_racing_claims_and_recovery_after_reconnect(ledger):
    """Two independent transactions compete, then lose the sender after commit."""
    from bisheng.knowledge.domain.repositories.provider_operation_repository import ProviderOperationRepository

    engine, instance = ledger
    repo = ProviderOperationRepository()
    start = datetime(2026, 1, 2)
    async with AsyncSession(engine) as writer, writer.begin():
        target = {
            "tenant_id": 17,
            "operation_id": (await repo.accept(writer, intent(instance, uuid4().hex))).operation_id,
        }

    ready = asyncio.Barrier(2)

    async def compete():
        async with AsyncSession(engine) as session, session.begin():
            await session.connection()  # both connections checked out before either UPDATE
            await ready.wait()
            row = await repo.claim(session, **target, now=start, lease_seconds=10)
            return (row.lease_token, row.revision, row.state) if row else None

    async with asyncio.timeout(30), asyncio.TaskGroup() as racers:
        contestants = [racers.create_task(compete()) for _ in range(2)]
    (winner,) = [r.result() for r in contestants if r.result() is not None]
    old_token, old_rev, old_state = winner
    assert old_state == "sending"
    # No live session or pooled connection crosses this boundary. This is
    # ledger recovery only; no actual remote request or worker is started.
    await engine.dispose()
    now = start + timedelta(seconds=11)
    async with AsyncSession(engine) as recovery, recovery.begin():
        due = await repo.list_due(recovery, tenant_id=17, now=now, limit=10, kinds=["create_space"])
        assert [r.operation_id for r in due] == [target["operation_id"]]
        new = await repo.claim(recovery, **target, now=now, lease_seconds=10, expected_revision=old_rev)
        assert (new.state, new.remote_kb_id, new.attempt) == ("reconciling", "original-kb", 2)
        assert new.lease_token != old_token and new.revision > old_rev
        new_token, new_rev = new.lease_token, new.revision
    apply = dict(**target, generation=1, operation_epoch=4, now=now, state="applying")
    async with AsyncSession(engine) as callback, callback.begin():
        assert not await repo.apply(callback, **apply, lease_token=old_token, expected_revision=old_rev)
        assert await repo.apply(callback, **apply, lease_token=new_token, expected_revision=new_rev)
        assert not await repo.apply(callback, **apply, lease_token=new_token, expected_revision=new_rev)
    async with AsyncSession(engine) as reader:
        row = await reader.get(KnowledgeProviderOperation, target["operation_id"])
        assert (row.state, row.remote_kb_id, row.revision) == ("applying", "original-kb", new_rev + 1)
