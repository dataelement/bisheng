"""Atomic business configuration and reference-index replacement.

覆盖 AC: AC-87, AC-88, AC-89, AC-91, AC-92
SQLite CAS/rollback tests do not prove production database lock scheduling.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    DeletionEvidence,
    ReferenceSpec,
    ReferenceState,
    SourceKey,
    TargetDeleteStage,
    TargetKey,
    TargetLockReceipt,
    TargetType,
    TransactionIdentity,
    VerifiedReferenceSet,
    VerifiedReferenceTarget,
    reference_set_digest,
)
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as ref_fixtures

TABLES = ref_fixtures.TABLES
engine = ref_fixtures.engine
tenant_events = ref_fixtures.tenant_events

metadata = MetaData()
business = Table("test_reference_business", metadata, Column("id", Integer, primary_key=True), Column("value", String))


def spec(target_id, slot="model"):
    return ReferenceSpec(slot, TargetKey("model", target_id))


def verified_set(session, owner, key, new, *, old=(), root_revision=0, states=None, locked=None):
    states = states or {}
    identity = TransactionIdentity.capture(session)
    targets = locked if locked is not None else {reference.target for reference in old + new}
    targets = tuple(sorted(targets, key=lambda key: key.lock_order_key))
    receipts = []
    for target in targets:
        state = states.get(target.target_id, ReferenceState.VALID)
        evidence = None
        if state != ReferenceState.VALID:
            evidence = DeletionEvidence("force-1", target, 101, TargetDeleteStage.DELETED)
        verified = VerifiedReferenceTarget(target, 101, None, "1", state, "r1", evidence)
        receipts.append(TargetLockReceipt(key, verified, identity, owner))
    context = BindingWriteContext(
        key, root_revision, root_revision, targets, reference_set_digest(old), tuple(receipts), identity
    )
    return VerifiedReferenceSet(new, "test-v1", context)


def components(repo=None):
    owner = object()
    repo = repo or ReferenceRepository()
    return owner, repo, ReferenceBindings(repo, {TargetType.MODEL: owner})


def test_reference_failure_rolls_back_business_and_root_guard(engine, monkeypatch):
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(business).values(id=1, value="original"))
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    with pytest.raises(RuntimeError, match="injected failure"):
        with Session(engine) as session, session.begin():
            session.execute(update(business).values(value="changed"))
            refs = verified_set(session, owner, key, (spec("1"),))
            monkeypatch.setattr(
                repo, "replace_source_set", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("injected failure"))
            )
            bindings.replace_source_bindings(session, key, None, 1, refs, True)
    with Session(engine) as session:
        assert session.execute(select(business.c.value)).scalar_one() == "original"
        assert repo.get_root_guard(session, key) is None
        assert repo.get_source_set(session, key) is None


def test_versions_update_independently_and_stale_root_cas_cannot_commit(engine):
    owner, repo, bindings = components()
    first, second = SourceKey(101, "workflow_version", "flow1", "v1"), SourceKey(101, "workflow_version", "flow1", "v2")
    with Session(engine) as session, session.begin():
        bindings.replace_source_bindings(
            session, first, None, 1, verified_set(session, owner, first, (spec("1"),)), True
        )
        bindings.replace_source_bindings(
            session, second, None, 1, verified_set(session, owner, second, (spec("2"),), root_revision=1), True
        )
        assert repo.get_root_guard(session, first).source_revision == 2
        stale = verified_set(session, owner, first, (), old=(spec("1"),), root_revision=1)
        with pytest.raises(ResourceReferenceInvalidError) as raised:
            bindings.replace_source_bindings(session, first, 1, 2, stale, False)
        assert raised.value.kwargs["reason"] == "root_revision_conflict"
        assert [row.target_id for row in repo.list_source_references(session, first)] == ["1"]
        assert [row.target_id for row in repo.list_source_references(session, second)] == ["2"]


def test_partial_repair_preserves_other_original_invalid_slot(engine):
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    old = (spec("1", "first"), spec("2", "second"))
    new = (old[0], spec("3", "second"))
    with Session(engine) as session, session.begin():
        bindings.replace_source_bindings(session, key, None, 1, verified_set(session, owner, key, old), True)
        original_id = repo.list_source_references(session, key)[0].id
        refs = verified_set(
            session, owner, key, new, old=old, root_revision=1, states={"1": ReferenceState.INVALID_DELETED}
        )
        result = bindings.replace_source_bindings(session, key, 1, 2, refs, True)
        actual = {row.slot_key: row for row in repo.list_source_references(session, key)}
        assert actual["first"].id == original_id and actual["first"].target_id == "1"
        assert actual["second"].target_id == "3"
        assert result.added == 1 and result.removed == 1 and result.retained_invalid == 1


def test_copy_or_new_slot_cannot_borrow_an_original_invalid_reference(engine):
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    with Session(engine) as session, session.begin():
        bindings.replace_source_bindings(session, key, None, 1, verified_set(session, owner, key, (spec("1"),)), True)
        for destination, previous, root_revision in [
            (SourceKey(101, "assistant", "copy", "current"), (), 0),
            (key, (spec("1"),), 1),
        ]:
            refs = verified_set(
                session,
                owner,
                destination,
                (spec("1", "new-slot"),),
                old=previous,
                root_revision=root_revision,
                states={"1": ReferenceState.INVALID_DELETED},
            )
            with pytest.raises(ResourceReferenceInvalidError) as raised:
                bindings.replace_source_bindings(session, destination, None if not previous else 1, 2, refs, True)
            assert raised.value.kwargs["reason"] == "new_invalid_reference"


def test_wrong_issuer_incomplete_lock_set_and_foreign_source_are_rejected(engine):
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    with Session(engine) as session, session.begin():
        bad = verified_set(session, object(), key, (spec("1"),))
        with pytest.raises(ResourceReferenceInvalidError):
            bindings.replace_source_bindings(session, key, None, 1, bad, True)
        bindings.replace_source_bindings(session, key, None, 1, verified_set(session, owner, key, (spec("1"),)), True)
        incomplete = verified_set(
            session, owner, key, (spec("2"),), old=(spec("1"),), root_revision=1, locked=(TargetKey("model", "2"),)
        )
        with pytest.raises(KnowledgeOperationPlanConflictError):
            bindings.replace_source_bindings(session, key, 1, 2, incomplete, True)
        foreign = SourceKey(202, "assistant", "foreign", "current")
        with pytest.raises(ResourceReferenceInvalidError) as raised:
            bindings.replace_source_bindings(
                session, foreign, None, 1, verified_set(session, owner, foreign, (spec("1"),)), True
            )
        assert raised.value.kwargs["reason"] == "source_tenant_mismatch"


def test_receipt_cannot_be_replayed_after_transaction_completion(engine):
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    with Session(engine) as session:
        with session.begin():
            refs = verified_set(session, owner, key, ())
        with session.begin(), pytest.raises(ResourceReferenceInvalidError):
            bindings.replace_source_bindings(session, key, None, 1, refs, True)


def test_deletion_evidence_cannot_be_reused_for_other_target_or_phase():
    target = TargetKey("model", "1")
    for evidence in [
        DeletionEvidence("op1", TargetKey("model", "2"), 101, "deleted"),
        DeletionEvidence("op1", target, 202, "deleted"),
        DeletionEvidence("op1", target, 101, "deleting"),
    ]:
        with pytest.raises(ValueError):
            VerifiedReferenceTarget(target, 101, None, None, "invalid_deleted", "r1", evidence)


async def test_async_replacement_is_in_the_business_transaction():
    owner, repo, bindings = components()
    key = SourceKey(101, "assistant", "a1", "current")
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                refs = verified_set(session, owner, key, (spec("1"),))
                result = await bindings.areplace_source_bindings(session, key, None, 1, refs, True)
                assert result.root_revision == 1
                await session.rollback()
        async with AsyncSession(engine) as session:
            assert await repo.aget_source_set(session, key) is None
    finally:
        await engine.dispose()
