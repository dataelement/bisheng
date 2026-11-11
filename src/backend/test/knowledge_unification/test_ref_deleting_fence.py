"""Deleting targets fence synchronous source writes until deletion completes.

覆盖 AC: AC-87, AC-89, AC-90, AC-91, AC-92
These are SQL rollback tests, not external Worker I/O race tests.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update
from sqlmodel import Session

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    DeletionEvidence,
    ReferenceSpec,
    SourceKey,
    TargetKey,
    TargetLockReceipt,
    TransactionIdentity,
    VerifiedReferenceSet,
    reference_set_digest,
)
from bisheng.resource_reference.application.target_state import resolve_target_state
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as ref_fixtures

tenant_events = ref_fixtures.tenant_events
metadata = MetaData()
business = Table(
    "test_deleting_reference_business",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("model_id", Integer, nullable=True),
    Column("description", String),
    Column("effective", Integer),
)
target_status = Table(
    "test_deleting_reference_target", metadata, Column("id", Integer, primary_key=True), Column("stage", String)
)
SOURCE = SourceKey(101, "assistant", "a1", "current")
TARGET = TargetKey("model", "1")
ORIGINAL = (ReferenceSpec("model", TARGET),)


class SqlTargetOwner:
    def _receipt(self, session, source_key, stage):
        evidence = DeletionEvidence("delete-plan-1", TARGET, 101, stage) if stage != "valid" else None
        observed = resolve_target_state(
            TARGET,
            exists=stage != "deleted",
            target_tenant_id=101,
            target_revision="r1",
            model_server_id="7",
            deletion_evidence=evidence,
        )
        return TargetLockReceipt(source_key, observed, TransactionIdentity.capture(session), self)

    def lock_and_verify(self, session, target_keys, source_key, operation):
        assert target_keys == (TARGET,)
        stage = session.execute(
            select(target_status.c.stage).where(target_status.c.id == 1).with_for_update()
        ).scalar_one()
        return (self._receipt(session, source_key, stage),)

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        assert target_keys == (TARGET,)
        stage = (
            await session.execute(select(target_status.c.stage).where(target_status.c.id == 1).with_for_update())
        ).scalar_one()
        return (self._receipt(session, source_key, stage),)


def replacement(session, verifier, refs, *, old=(), root_revision=0):
    keys = tuple(sorted({item.target for item in old + refs}, key=lambda key: key.lock_order_key))
    receipts = verifier.verify_targets(session, SOURCE, keys)
    context = BindingWriteContext(
        SOURCE,
        root_revision,
        root_revision,
        keys,
        reference_set_digest(old),
        receipts,
        TransactionIdentity.capture(session),
    )
    return VerifiedReferenceSet(refs, "fence-test-v1", context)


@pytest.fixture
def prepared(ref_fixtures_engine):
    return ref_fixtures_engine


@pytest.fixture
def ref_fixtures_engine(f118_engine):
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(f118_engine, tables=ref_fixtures.TABLES)
    metadata.create_all(f118_engine)
    owner = SqlTargetOwner()
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    bindings = ReferenceBindings(repo, verifier)
    with Session(f118_engine) as session, session.begin():
        session.execute(insert(target_status).values(id=1, stage="valid"))
        session.execute(insert(business).values(id=1, model_id=1, description="original", effective=1))
        bindings.replace_source_bindings(session, SOURCE, None, 1, replacement(session, verifier, ORIGINAL), True)
    return f118_engine, verifier, repo, bindings


@pytest.mark.parametrize("kind", ["retain", "remove", "source_delete"])
def test_deleting_target_blocks_all_source_writes_and_rolls_back_business(prepared, kind):
    engine, verifier, repo, bindings = prepared
    with engine.begin() as connection:
        connection.execute(update(target_status).values(stage="deleting"))
    refs = ORIGINAL if kind == "retain" else ()
    effective = kind != "source_delete"
    with pytest.raises(KnowledgeProcessingConflictError) as raised:
        with Session(engine) as session, session.begin():
            session.execute(
                update(business).values(model_id=1 if refs else None, description="changed", effective=int(effective))
            )
            bindings.replace_source_bindings(
                session, SOURCE, 1, 2, replacement(session, verifier, refs, old=ORIGINAL, root_revision=1), effective
            )
    assert raised.value.kwargs["reason"] == "reference_target_deleting"
    with Session(engine) as session:
        saved = session.execute(select(business)).one()
        assert (saved.model_id, saved.description, saved.effective) == (1, "original", 1)
        assert repo.get_root_guard(session, SOURCE).source_revision == 1
        assert repo.get_source_set(session, SOURCE).source_revision == 1
        assert [row.target_id for row in repo.list_source_references(session, SOURCE)] == ["1"]


@pytest.mark.parametrize("kind", ["retain", "remove", "source_delete"])
def test_completed_deletion_allows_original_slot_repair(prepared, kind):
    engine, verifier, repo, bindings = prepared
    with engine.begin() as connection:
        connection.execute(update(target_status).values(stage="deleted"))
    refs = ORIGINAL if kind == "retain" else ()
    effective = kind != "source_delete"
    with Session(engine) as session, session.begin():
        session.execute(
            update(business).values(model_id=1 if refs else None, description="repaired", effective=int(effective))
        )
        result = bindings.replace_source_bindings(
            session, SOURCE, 1, 2, replacement(session, verifier, refs, old=ORIGINAL, root_revision=1), effective
        )
        assert result.root_revision == result.source_revision == 2
        assert len(repo.list_source_references(session, SOURCE)) == len(refs)


def test_deleted_target_cannot_be_added_under_a_new_slot(prepared):
    engine, verifier, _repo, bindings = prepared
    with engine.begin() as connection:
        connection.execute(update(target_status).values(stage="deleted"))
    with Session(engine) as session, session.begin(), pytest.raises(ResourceReferenceInvalidError) as raised:
        bindings.replace_source_bindings(
            session,
            SOURCE,
            1,
            2,
            replacement(session, verifier, (ReferenceSpec("new-slot", TARGET),), old=ORIGINAL, root_revision=1),
            True,
        )
    assert raised.value.kwargs["reason"] == "new_invalid_reference"


def test_reading_deleting_target_still_reports_deleting(prepared):
    engine, verifier, _repo, _bindings = prepared
    with engine.begin() as connection:
        connection.execute(update(target_status).values(stage="deleting"))
    with Session(engine) as session, session.begin():
        receipt = verifier.verify_owner_targets(session, (TARGET,))[0]
        assert receipt.target.state == "deleting"
