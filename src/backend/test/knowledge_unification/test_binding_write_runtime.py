"""T279: target-first preparation and business-owned atomic commit.

覆盖 AC: AC-87, AC-88, AC-89, AC-90, AC-91, AC-92
The target observer is a unit double; Owner SQL has separate production tests.
"""

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    ReferenceSpec,
    SourceKey,
    TargetDeleteStage,
    TargetKey,
    TargetType,
    VerifiedReferenceTarget,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as refs

engine = refs.engine
tenant_events = refs.tenant_events
metadata = MetaData()
business = Table("test_runtime_business", metadata, Column("id", Integer, primary_key=True), Column("value", Integer))
KEY = SourceKey(101, "assistant", "root-1", "current")
MODEL = ReferenceSpec("model", TargetKey("model", "1"))


class RecordingOwner(refs.ModelOwner):
    def __init__(self):
        self.events = []
        self.state = "valid"

    def observation(self, target):
        if self.state == "valid":
            return super().observation(target)
        stage = TargetDeleteStage.DELETING if self.state == "deleting" else TargetDeleteStage.DELETED
        evidence = DeletionEvidence("delete-1", target, 101, stage)
        return VerifiedReferenceTarget(target, 101, None, "1", self.state, "r2", evidence)

    def lock_and_verify(self, *args):
        self.events.append("targets")
        return super().lock_and_verify(*args)


def runtime():
    owner = RecordingOwner()
    verifier = ReferenceTargetVerifier({TargetType.MODEL: owner})
    repo = ReferenceRepository(verifier=verifier)
    return ReferenceBindingRuntime(repo, verifier), owner


def prepare(rt, owner, session, *, new_source=True, references=(MODEL,), effective=True, lock=None):
    def lock_root(_session):
        owner.events.append("root")
        if lock is not None:
            lock(_session)

    return rt.prepare_source_bindings(
        session,
        KEY,
        references,
        extractor_version="source-v1",
        lock_source_root=lock_root,
        new_source=new_source,
        effective=effective,
    )


def test_prepare_locks_targets_then_root_and_apply_joins_business_transaction(engine):
    metadata.create_all(engine)
    rt, owner = runtime()
    with Session(engine) as session:
        session.execute(insert(business).values(id=1, value=10))
        prepared = prepare(rt, owner, session)
        assert owner.events == ["targets", "root"]
        assert rt.repository.get_source_set(session, KEY) is None
        session.execute(update(business).where(business.c.id == 1).values(value=20))
        rt.apply_source_bindings(session, prepared)
        assert rt.repository.get_source_set(session, KEY).source_revision == 1
        session.rollback()
        assert rt.repository.get_source_set(session, KEY) is None
        assert session.execute(select(business)).first() is None


def test_existing_missing_index_cannot_be_silently_bootstrapped(engine):
    rt, owner = runtime()
    with Session(engine) as session, pytest.raises(ReferenceCoverageNotReadyError):
        prepare(rt, owner, session, new_source=False)
    assert owner.events == []


def test_new_source_flag_cannot_overwrite_an_existing_source(engine):
    rt, owner = runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, prepare(rt, owner, session))
        with pytest.raises(ResourceReferenceInvalidError):
            prepare(rt, owner, session, new_source=True)


def test_root_revision_change_between_candidate_and_lock_requires_retry(engine):
    rt, owner = runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, prepare(rt, owner, session))

        def change_root(s):
            rt.repository.advance_root_guard(s, KEY, expected_revision=1, new_revision=2)

        with pytest.raises(KnowledgeOperationPlanConflictError):
            prepare(rt, owner, session, new_source=False, lock=change_root)


def test_deleting_target_rejects_before_source_root_callback(engine):
    rt, owner = runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, prepare(rt, owner, session))
        owner.events.clear()
        owner.state = "deleting"
        with pytest.raises(KnowledgeProcessingConflictError):
            prepare(rt, owner, session, new_source=False)
        assert owner.events == ["targets"]
        assert rt.repository.get_root_guard(session, KEY).source_revision == 1


def test_prepared_write_cannot_cross_transaction_boundary(engine):
    rt, owner = runtime()
    with Session(engine) as session:
        prepared = prepare(rt, owner, session)
        session.commit()
        with session.begin(), pytest.raises(ResourceReferenceInvalidError):
            rt.apply_source_bindings(session, prepared)


async def test_native_async_prepare_apply_and_rollback():
    rt, owner = runtime()
    async_engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=refs.TABLES))
        with refs.tenant(101):
            async with AsyncSession(async_engine) as session:

                async def lock_root(_session):
                    owner.events.append("async-root")

                prepared = await rt.aprepare_source_bindings(
                    session,
                    KEY,
                    (MODEL,),
                    extractor_version="source-v1",
                    lock_source_root=lock_root,
                    new_source=True,
                )
                await rt.aapply_source_bindings(session, prepared)
                assert owner.events == ["targets", "async-root"]
                await session.rollback()
                assert await rt.repository.aget_source_set(session, KEY) is None
    finally:
        await async_engine.dispose()
