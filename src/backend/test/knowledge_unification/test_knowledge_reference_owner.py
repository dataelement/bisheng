"""T274: business-backed knowledge target verification.

覆盖 AC: AC-72, AC-87, AC-88, AC-89
SQLite proves transactional reads/rollback, not MySQL/DM8 lock scheduling.
"""

from dataclasses import replace

import pytest
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    ReferenceCoverageNotReadyError,
    ResourceReferenceConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.knowledge.domain.repositories.reference_target_repository import KnowledgeReferenceTargetRepository
from bisheng.resource_reference.application.contracts import LegacyEvidence, SourceKey, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification.test_ref_repo import tenant

TABLES = [
    Knowledge.__table__,
    KnowledgeFile.__table__,
    BusinessResourceReference.__table__,
    ResourceReferenceTombstone.__table__,
    KnowledgeUnificationRun.__table__,
]
SOURCE = SourceKey(101, "assistant", "a1", "current")


@pytest.fixture(autouse=True)
def owner_tenant(monkeypatch):
    names = {table.name for table in TABLES}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    with tenant(101):
        yield


@pytest.fixture
def engine(f118_engine):
    SQLModel.metadata.create_all(f118_engine, tables=TABLES)
    return f118_engine


def setup(session, *, kind=3):
    session.add(Knowledge(id=1, tenant_id=101, user_id=11, name="one", type=kind))
    session.add(Knowledge(id=2, tenant_id=101, user_id=11, name="two", type=3))
    session.add(KnowledgeFile(id=8, tenant_id=101, user_id=11, knowledge_id=1, file_name="file"))
    session.flush()


def verifier(owner):
    return ReferenceTargetVerifier({"knowledge_space": owner, "knowledge_file": owner})


def original(session, key, *, slot="slot", target_tenant_id=101, space_id=None, legacy=False):
    row = BusinessResourceReference(
        tenant_id=101,
        source_type=SOURCE.source_type.value,
        source_id=SOURCE.source_id,
        source_version=SOURCE.source_version,
        slot_key=slot,
        target_type=key.target_type.value,
        target_id=key.target_id,
        target_tenant_id=target_tenant_id,
        target_space_id=space_id,
        source_revision=1,
        legacy_invalid_reason="target_missing" if legacy else None,
        legacy_run_id="run-1" if legacy else None,
        legacy_evidence_key="target-evidence" if legacy else None,
    )
    session.add(row)
    session.flush()
    return row


def tombstone(session, key, *, stage="deleted"):
    session.add(
        ResourceReferenceTombstone(
            tenant_id=101,
            target_type=key.target_type.value,
            target_id=key.target_id,
            target_tenant_id=101,
            operation_id="delete-1",
            operation_type="force_delete",
            stage=stage,
            actor_type="user",
            actor_id="11",
        )
    )
    session.flush()


class LedgerEvidence:
    def resolve(self, session, source_key, target, *, run_id, evidence_key):
        row = session.exec(select(KnowledgeUnificationRun).where(KnowledgeUnificationRun.run_id == run_id)).one()
        assert row.tenant_id == source_key.tenant_id and target.target_id == "80"
        return LegacyEvidence(run_id, row.baseline_hash, evidence_key)

    async def aresolve(self, session, source_key, target, *, run_id, evidence_key):
        row = (
            await session.exec(select(KnowledgeUnificationRun).where(KnowledgeUnificationRun.run_id == run_id))
        ).one()
        return LegacyEvidence(run_id, row.baseline_hash, evidence_key)


@pytest.mark.parametrize("kind", [0, 1, 3])
def test_real_container_types_and_file_ownership_are_verified_in_one_batch(engine, kind):
    owner = KnowledgeReferenceTargetOwner()
    with Session(engine) as session, session.begin():
        setup(session, kind=kind)
        receipts = verifier(owner).verify_targets(
            session, SOURCE, (TargetKey("knowledge_file", "8"), TargetKey("knowledge_space", "1"))
        )
        assert len(receipts) == 2
        assert all(row.target.target_tenant_id == 101 and row.target.target_space_id == "1" for row in receipts)
        assert all(row.target.state == "valid" and row.issuer is owner for row in receipts)
        owner_receipts = verifier(owner).verify_owner_targets(session, (TargetKey("knowledge_space", "1"),))
        assert owner_receipts[0].source_key is None


def test_foreign_targets_and_foreign_sources_do_not_issue_capabilities(engine):
    owner = KnowledgeReferenceTargetOwner()
    with Session(engine) as session, session.begin():
        setup(session)
        session.add(Knowledge(id=3, tenant_id=202, user_id=11, name="foreign", type=3))
        session.add(KnowledgeFile(id=9, tenant_id=202, user_id=11, knowledge_id=3, file_name="foreign"))
        session.flush()
        for key in (TargetKey("knowledge_space", "3"), TargetKey("knowledge_file", "9")):
            with pytest.raises(ResourceReferenceInvalidError):
                verifier(owner).verify_targets(session, SOURCE, (key,))
        with pytest.raises(ResourceReferenceInvalidError):
            owner.lock_and_verify(session, (TargetKey("knowledge_space", "1"),), replace(SOURCE, tenant_id=202), "bind")


def test_file_space_candidate_drift_requires_whole_transaction_rollback(engine):
    with Session(engine) as session, session.begin():
        setup(session)
    observed = []

    def move_before_locked_file_read(state):
        if state.is_select and state.statement._for_update_arg is not None:
            names = {description.get("entity") for description in state.statement.column_descriptions}
            if KnowledgeFile in names and not observed:
                observed.append(True)
                state.session.execute(update(KnowledgeFile).where(KnowledgeFile.id == 8).values(knowledge_id=2))

    with Session(engine) as session:
        event.listen(session, "do_orm_execute", move_before_locked_file_read)
        with pytest.raises(ResourceReferenceConflictError), session.begin():
            verifier(KnowledgeReferenceTargetOwner()).verify_targets(
                session, SOURCE, (TargetKey("knowledge_file", "8"),)
            )
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 8).knowledge_id == 1 and observed


@pytest.mark.parametrize("stage,state", [("deleting", "deleting"), ("deleted", "invalid_deleted")])
def test_missing_original_file_uses_real_ancestor_deletion_evidence(engine, stage, state):
    key = TargetKey("knowledge_file", "80")
    with Session(engine) as session, session.begin():
        original(session, key, space_id="1")
        tombstone(session, TargetKey("knowledge_space", "1"), stage=stage)
        receipt = verifier(KnowledgeReferenceTargetOwner()).verify_targets(session, SOURCE, (key,))[0]
        assert receipt.target.state == state
        assert receipt.target.evidence.target == key and receipt.target.evidence.operation_id == "delete-1"
        assert receipt.target.target_tenant_id == 101


def test_unexplained_missing_and_other_sources_evidence_are_rejected(engine):
    key = TargetKey("knowledge_space", "80")
    with Session(engine) as session, session.begin():
        row = original(session, key, legacy=True)
        row.source_id = "someone-else"
        session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            verifier(KnowledgeReferenceTargetOwner()).verify_targets(session, SOURCE, (key,))


def test_legacy_requires_ledger_port_and_keeps_unknown_target_owner(engine):
    key = TargetKey("knowledge_file", "80")
    with Session(engine) as session, session.begin():
        original(session, key, legacy=True, target_tenant_id=None)
        session.add(KnowledgeUnificationRun(tenant_id=101, run_id="run-1", baseline_hash="a" * 64))
        session.flush()
        with pytest.raises(ReferenceCoverageNotReadyError):
            verifier(KnowledgeReferenceTargetOwner()).verify_targets(session, SOURCE, (key,))
        receipt = verifier(KnowledgeReferenceTargetOwner(legacy_evidence=LedgerEvidence())).verify_targets(
            session, SOURCE, (key,)
        )[0]
        assert receipt.target.state == "invalid_legacy" and receipt.target.target_tenant_id is None
        assert receipt.target.evidence.baseline_hash == "a" * 64
        assert not session.exec(select(ResourceReferenceTombstone)).all()


def test_conflicting_multislot_legacy_evidence_is_not_arbitrarily_selected(engine):
    key = TargetKey("knowledge_file", "80")
    with Session(engine) as session, session.begin():
        original(session, key, legacy=True, slot="one")
        row = original(session, key, legacy=True, slot="two")
        row.legacy_evidence_key = "different-evidence"
        session.flush()
        with pytest.raises(ResourceReferenceInvalidError):
            verifier(KnowledgeReferenceTargetOwner(legacy_evidence=LedgerEvidence())).verify_targets(
                session, SOURCE, (key,)
            )


async def test_native_async_owner_reads_sql_without_sync_fallback():
    class AsyncOnlyRepository(KnowledgeReferenceTargetRepository):
        def lock_targets(self, *args, **kwargs):
            raise AssertionError("sync SQL used in async Owner")

    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=TABLES))
        async with AsyncSession(database) as session, session.begin():
            session.add(Knowledge(id=1, tenant_id=101, user_id=11, name="one", type=3))
            session.add(KnowledgeFile(id=8, tenant_id=101, user_id=11, knowledge_id=1, file_name="file"))
            await session.flush()
            owner = KnowledgeReferenceTargetOwner(AsyncOnlyRepository())
            await owner.aprelock_targets(session, (TargetKey("knowledge_file", "8"),), (SOURCE,))
            receipts = await verifier(owner).averify_targets(session, SOURCE, (TargetKey("knowledge_file", "8"),))
            assert receipts[0].target.target_space_id == "1" and receipts[0].target.state == "valid"
            await session.rollback()
        async with AsyncSession(database) as session:
            assert not (await session.exec(select(Knowledge))).all()
    finally:
        await database.dispose()


def test_physical_prelock_unions_missing_file_parents_without_merging_version_evidence(engine):
    source_keys = (replace(SOURCE, source_version="v1"), replace(SOURCE, source_version="v2"))
    key = TargetKey("knowledge_file", "80")
    observed = []
    with Session(engine) as session, session.begin():
        setup(session)
        for index, source in enumerate(source_keys):
            row = original(session, key, slot=str(index), space_id=str(index + 1), legacy=True, target_tenant_id=None)
            row.source_version, row.legacy_evidence_key = source.source_version, "evidence-" + source.source_version
            session.flush()
        session.add(KnowledgeUnificationRun(tenant_id=101, run_id="run-1", baseline_hash="a" * 64))
        session.flush()

        def lock_read(state):
            if state.is_select and state.statement._for_update_arg is not None:
                entities = {row.get("entity") for row in state.statement.column_descriptions}
                if Knowledge in entities or KnowledgeFile in entities:
                    observed.append(
                        ("space" if Knowledge in entities else "file", state.statement.compile().params.get("id_1"))
                    )

        event.listen(session, "do_orm_execute", lock_read)
        owner = KnowledgeReferenceTargetOwner(legacy_evidence=LedgerEvidence())
        assert owner.prelock_targets(session, (key, TargetKey("knowledge_file", "8")), source_keys) is None
        assert observed[:2] == [("space", [1, 2]), ("file", [8, 80])]
        receipts = [verifier(owner).verify_targets(session, source, (key,))[0] for source in source_keys]
        assert [row.target.evidence.evidence_key for row in receipts] == ["evidence-v1", "evidence-v2"]
        assert [row.target.target_space_id for row in receipts] == ["1", "2"]


def test_prelocked_owner_refuses_new_parent_before_taking_a_late_space_lock(engine):
    with Session(engine) as session, session.begin():
        setup(session)
    late_space_locks = []
    with pytest.raises(ResourceReferenceConflictError), Session(engine) as session, session.begin():
        owner = KnowledgeReferenceTargetOwner()
        key = TargetKey("knowledge_file", "8")
        owner.prelock_targets(session, (key,), (SOURCE,))
        session.get(KnowledgeFile, 8).knowledge_id = 2
        session.flush()

        def observe(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and Knowledge in {row.get("entity") for row in state.statement.column_descriptions}
            ):
                late_space_locks.append(state.statement.compile().params.get("id_1"))

        event.listen(session, "do_orm_execute", observe)
        verifier(owner).verify_targets(session, SOURCE, (key,))
    assert late_space_locks == []
    with Session(engine) as session:
        assert session.get(KnowledgeFile, 8).knowledge_id == 1
