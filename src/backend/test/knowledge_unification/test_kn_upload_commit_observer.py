"""The single native commit observer preserves original upload ACK evidence."""

import asyncio
import importlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.resource_reference.application.contracts import TransactionIdentity
from test.knowledge_unification import test_kn_upload_registration_repository as original

native = original.native
database = original.database


def observer():
    return importlib.import_module(
        "bisheng.knowledge.domain.repositories.upload_commit_observer"
    ).UploadCommitObserver()


async def test_exact_native_root_ack_retires_only_owned_listeners_synchronously(database):
    one, two, calls = observer(), observer(), []
    async with AsyncSession(database.engine) as session:
        await session.begin()
        transaction = TransactionIdentity.capture(session)
        one.observe(transaction)
        two.observe(transaction)

        def caller(_session):
            calls.append(1)

        sa.event.listen(session.sync_session, "after_commit", caller)
        await session.commit()
        assert calls == [1]
        one.acknowledge((transaction,))
        assert len(session.sync_session.dispatch.after_commit) == 2
        two.acknowledge((transaction,))
        assert len(session.sync_session.dispatch.after_commit) == 1
        assert sa.event.contains(session.sync_session, "after_commit", caller)
        sa.event.remove(session.sync_session, "after_commit", caller)


@pytest.mark.parametrize(
    "case", ["active", "savepoint_only", "rollback", "rollback_then_empty_commit", "other_session"]
)
async def test_uncommitted_or_other_root_cannot_supply_native_ack(database, case):
    seen = observer()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        transaction = TransactionIdentity.capture(session)
        seen.observe(transaction)
        if case == "savepoint_only":
            async with session.begin_nested():
                pass
        elif case.startswith("rollback"):
            await session.rollback()
            if case == "rollback_then_empty_commit":
                await session.commit()
        elif case == "other_session":
            async with AsyncSession(database.engine) as other:
                await other.commit()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            seen.acknowledge((transaction,))


@pytest.mark.parametrize("nested_rollback", [False, True])
async def test_original_all_savepoint_ancestors_need_commit_evidence(database, nested_rollback):
    seen = observer()
    async with AsyncSession(database.engine) as session:
        await session.begin()
        first, second = await session.begin_nested(), await session.begin_nested()
        transaction = TransactionIdentity.capture(session)
        seen.observe(transaction)
        if nested_rollback:
            await second.rollback()
        await session.commit()
        assert not first.is_active and not second.is_active
        if nested_rollback:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                seen.acknowledge((transaction,))
        else:
            seen.acknowledge((transaction,))
            assert not session.sync_session.dispatch.after_commit


async def test_later_native_caller_select_one_does_not_mutate_listener_dispatch(database):
    seen, calls = observer(), []
    async with AsyncSession(database.engine) as session:
        await session.begin()
        transaction = TransactionIdentity.capture(session)
        seen.observe(transaction)

        def caller(native_session, current):
            if current.parent is None:
                with Session(native_session.get_bind()) as audit:
                    calls.append(audit.execute(sa.text("SELECT 1")).scalar_one())

        sa.event.listen(session.sync_session, "after_transaction_end", caller)
        try:
            await session.commit()
            seen.acknowledge((transaction,))
            assert calls == [1]
            assert sa.event.contains(session.sync_session, "after_transaction_end", caller)
        finally:
            sa.event.remove(session.sync_session, "after_transaction_end", caller)


@pytest.mark.parametrize("outcome", ["rollback", "unknown"])
async def test_unacknowledged_root_listeners_survive_yield_until_owner_task_done(database, outcome):
    seen, ready, release, sessions = observer(), asyncio.Event(), asyncio.Event(), []

    async def owner():
        async with AsyncSession(database.engine) as session:
            await session.begin()
            seen.observe(TransactionIdentity.capture(session))
            sessions.append(session.sync_session)
            if outcome == "rollback":
                await session.rollback()
            else:

                def fail(_session):
                    raise OSError("commit ACK unknown")

                sa.event.listen(session.sync_session, "after_commit", fail)
                try:
                    with pytest.raises(OSError):
                        await session.commit()
                finally:
                    sa.event.remove(session.sync_session, "after_commit", fail)
            ready.set()
            await release.wait()

    task = asyncio.create_task(owner())
    try:
        await ready.wait()
        await asyncio.sleep(0)
        assert len(sessions[0].dispatch.after_commit) == len(sessions[0].dispatch.after_transaction_end) == 1
    finally:
        release.set()
        await task
    assert not sessions[0].dispatch.after_commit and not sessions[0].dispatch.after_transaction_end


async def test_ack_batch_validates_every_root_before_retiring_any_listener(database):
    seen = observer()
    async with AsyncSession(database.engine) as first, AsyncSession(database.engine) as second:
        await first.begin()
        await second.begin()
        one, two = TransactionIdentity.capture(first), TransactionIdentity.capture(second)
        seen.observe(one)
        seen.observe(two)
        await first.commit()
        with pytest.raises(KnowledgeOperationPlanConflictError):
            seen.acknowledge((one, two))
        assert len(first.sync_session.dispatch.after_commit) == 1
        await second.commit()
        seen.acknowledge((one, two))
        assert not first.sync_session.dispatch.after_commit and not second.sync_session.dispatch.after_commit
