"""T309: one root, one target-lock plan, source-specific evidence and atomic batch.

覆盖 AC: AC-87, AC-88, AC-89, AC-90, AC-91, AC-92
SQLite verifies actual SQL state/rollback; production lock scheduling is separate.
"""

from dataclasses import replace

import pytest
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingConflictError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.batch import BatchReferenceBindings, SourceBindingRequest
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    LegacyEvidence,
    ReferenceSpec,
    SourceKey,
    TargetKey,
    TargetLockReceipt,
    TransactionIdentity,
    VerifiedReferenceTarget,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as refs

tenant_events = refs.tenant_events
metadata = MetaData()
roots = Table("test_batch_roots", metadata, Column("id", String, primary_key=True), Column("value", Integer))
versions = Table(
    "test_batch_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("root_id", String),
    Column("is_delete", Boolean, default=False),
)
targets = Table("test_batch_targets", metadata, Column("id", Integer, primary_key=True), Column("state", String))
KEYS = (SourceKey(101, "workflow_version", "root-1", "v1"), SourceKey(101, "workflow_version", "root-1", "v2"))


def ref(number, slot="model"):
    return ReferenceSpec(slot, TargetKey("model", str(number)))


class SqlOwner:
    def __init__(self, events):
        self.events, self.prelocked, self.batch_mode, self.async_only = events, None, False, False

    def _prelocked(self, keys, source_keys):
        self.events.append(("prelock", tuple(key.target_id for key in keys), source_keys))
        self.prelocked = frozenset(keys)

    def prelock_targets(self, session, keys, source_keys):
        if self.async_only:
            raise AssertionError("sync prelock in async batch")
        session.execute(
            select(targets)
            .where(targets.c.id.in_([int(key.target_id) for key in keys]))
            .order_by(targets.c.id)
            .with_for_update()
        ).all()
        self._prelocked(keys, source_keys)

    async def aprelock_targets(self, session, keys, source_keys):
        (
            await session.execute(
                select(targets)
                .where(targets.c.id.in_([int(key.target_id) for key in keys]))
                .order_by(targets.c.id)
                .with_for_update()
            )
        ).all()
        self._prelocked(keys, source_keys)

    def _issue(self, session, keys, source, states, originals):
        if self.batch_mode:
            assert self.prelocked is not None and set(keys) <= self.prelocked
        self.events.append(("verify", source.source_version, tuple(key.target_id for key in keys)))
        result = []
        for key in keys:
            state = states.get(int(key.target_id), "valid")
            evidence, owner = None, 101
            if state == "invalid_legacy":
                original = next(row for row in originals if row.target_id == key.target_id)
                evidence, owner = LegacyEvidence(original.legacy_run_id, "a" * 64, original.legacy_evidence_key), None
            elif state != "valid":
                evidence = DeletionEvidence("delete-1", key, 101, "deleting" if state == "deleting" else "deleted")
            fact = VerifiedReferenceTarget(key, owner, None, "1", state, "revision", evidence)
            result.append(TargetLockReceipt(source, fact, TransactionIdentity.capture(session), self))
        return tuple(result)

    @staticmethod
    def _originals(source):
        return select(BusinessResourceReference).where(
            BusinessResourceReference.source_type == source.source_type.value,
            BusinessResourceReference.source_id == source.source_id,
            BusinessResourceReference.source_version == source.source_version,
        )

    def lock_and_verify(self, session, keys, source, operation):
        if self.async_only:
            raise AssertionError("sync verification in async batch")
        states = dict(session.execute(select(targets.c.id, targets.c.state)).all())
        return self._issue(session, keys, source, states, session.execute(self._originals(source)).scalars().all())

    async def alock_and_verify(self, session, keys, source, operation):
        states = dict((await session.execute(select(targets.c.id, targets.c.state))).all())
        originals = (await session.execute(self._originals(source))).scalars().all()
        return self._issue(session, keys, source, states, originals)


@pytest.fixture
def engine(f118_engine):
    SQLModel.metadata.create_all(f118_engine, tables=refs.TABLES)
    metadata.create_all(f118_engine)
    return f118_engine


def components():
    events = []
    owner = SqlOwner(events)
    verifier = ReferenceTargetVerifier({"model": owner})
    repository = ReferenceRepository(verifier=verifier)
    return (
        owner,
        repository,
        ReferenceBindingRuntime(repository, verifier),
        BatchReferenceBindings(repository, verifier),
    )


def seed(session, runtime, *, legacy=False):
    session.execute(insert(roots).values(id="root-1", value=10))
    session.execute(
        insert(versions), [{"id": key.source_version, "root_id": key.source_id, "is_delete": False} for key in KEYS]
    )
    session.execute(insert(targets), [{"id": number, "state": "valid"} for number in [1, 2, 3, 80]])
    for index, key in enumerate(KEYS):
        prepared = runtime.prepare_source_bindings(
            session,
            key,
            (ref(80 if legacy else 2 - index),),
            extractor_version="wf-v1",
            lock_source_root=lambda _: None,
            new_source=True,
        )
        runtime.apply_source_bindings(session, prepared)
    if legacy:
        for key in KEYS:
            session.execute(
                update(BusinessResourceReference)
                .where(
                    BusinessResourceReference.source_version == key.source_version,
                    BusinessResourceReference.tenant_id == 101,
                )
                .values(
                    target_tenant_id=None,
                    legacy_invalid_reason="target_missing",
                    legacy_run_id="run-1",
                    legacy_evidence_key="evidence-" + key.source_version,
                )
            )
        session.execute(update(targets).where(targets.c.id == 80).values(state="invalid_legacy"))


def requests(*, delete_source=False, legacy=False):
    return tuple(
        SourceBindingRequest(
            key, () if delete_source else (ref(80 if legacy else index + 1),), "wf-v1", effective=not delete_source
        )
        for index, key in enumerate(KEYS)
    )


def root_lock(events, *, add_version=False):
    def lock(session, expected):
        events.append(("root", expected))
        session.execute(select(roots).where(roots.c.id == "root-1").with_for_update()).one()
        if add_version:
            session.execute(insert(versions).values(id="v3", root_id="root-1", is_delete=False))
        rows = (
            session.execute(
                select(versions.c.id)
                .where(versions.c.root_id == "root-1", versions.c.is_delete == 0)
                .order_by(versions.c.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        return tuple(replace(KEYS[0], source_version=value) for value in rows)

    return lock


def test_all_targets_prelock_once_before_any_source_receipt_or_root_and_apply_root_sequence(engine):
    owner, repository, runtime, batch = components()
    with Session(engine) as session, session.begin():
        seed(session, runtime)
        owner.events.clear()
        owner.batch_mode = True
        prepared = batch.prepare_source_batch(
            session, tuple(reversed(requests())), lock_source_root=root_lock(owner.events)
        )
        assert prepared.source_keys == KEYS and prepared.base_root_revision == 2
        assert [item.verified.context.expected_root_revision for item in prepared.sources] == [2, 3]
        assert [event[0] for event in owner.events] == ["prelock", "verify", "verify", "root"]
        assert owner.events[0][1] == ("1", "2")
        assert [event[1] for event in owner.events[1:3]] == ["v1", "v2"]
        results = batch.apply_source_batch(session, prepared)
        assert [result.root_revision for result in results] == [3, 4]
        assert [repository.list_source_references(session, key)[0].target_id for key in KEYS] == ["1", "2"]


def test_second_source_failure_rolls_back_first_source_and_business_change(engine):
    owner, repository, runtime, batch = components()
    with Session(engine) as session, session.begin():
        seed(session, runtime)
        session.execute(update(targets).where(targets.c.id == 3).values(state="invalid_deleted"))
    broken = (requests()[0], replace(requests()[1], references=(ref(3),)))
    with pytest.raises(ResourceReferenceInvalidError), Session(engine) as session, session.begin():
        owner.batch_mode = True
        prepared = batch.prepare_source_batch(session, broken, lock_source_root=root_lock(owner.events))
        session.execute(update(roots).values(value=20))
        batch.apply_source_batch(session, prepared)
    with Session(engine) as session:
        assert session.execute(select(roots.c.value)).scalar_one() == 10
        assert repository.get_root_guard(session, KEYS[0]).source_revision == 2
        assert [repository.get_source_set(session, key).source_revision for key in KEYS] == [1, 1]


def test_legacy_proof_is_resolved_separately_for_each_real_source_version(engine):
    owner, repository, runtime, batch = components()
    with Session(engine) as session, session.begin():
        seed(session, runtime, legacy=True)
        owner.batch_mode = True
        prepared = batch.prepare_source_batch(session, requests(legacy=True), lock_source_root=root_lock(owner.events))
        assert [item.verified.context.receipts[0].target.evidence.evidence_key for item in prepared.sources] == [
            "evidence-v1",
            "evidence-v2",
        ]
        results = batch.apply_source_batch(session, prepared)
        assert [result.retained_invalid for result in results] == [1, 1]
        assert repository.get_root_guard(session, KEYS[0]).source_revision == 4


def test_real_root_manifest_change_rejects_and_rolls_back_new_version(engine):
    owner, repository, runtime, batch = components()
    with Session(engine) as session, session.begin():
        seed(session, runtime)
    with pytest.raises(KnowledgeOperationPlanConflictError), Session(engine) as session, session.begin():
        batch.prepare_source_batch(
            session, requests(delete_source=True), lock_source_root=root_lock(owner.events, add_version=True)
        )
    with Session(engine) as session:
        assert session.execute(select(versions.c.id)).scalars().all() == ["v1", "v2"]
        assert repository.get_root_guard(session, KEYS[0]).source_revision == 2


def test_deleting_any_old_target_fences_entire_batch_before_root_callback(engine):
    owner, repository, runtime, batch = components()
    with Session(engine) as session, session.begin():
        seed(session, runtime)
        session.execute(update(targets).where(targets.c.id == 1).values(state="deleting"))
        owner.events.clear()
        with pytest.raises(KnowledgeProcessingConflictError):
            batch.prepare_source_batch(session, requests(delete_source=True), lock_source_root=root_lock(owner.events))
        assert not any(event[0] == "root" for event in owner.events)
        assert repository.get_root_guard(session, KEYS[0]).source_revision == 2


@pytest.mark.parametrize("orphan_effective", [False, True])
def test_batch_root_inventory_keeps_extra_indexed_versions_visible_to_the_business_owner(engine, orphan_effective):
    owner, repository, runtime, batch = components()
    orphan = replace(KEYS[0], source_version="v999")
    with Session(engine) as session, session.begin():
        seed(session, runtime)
        repository.replace_source_set(
            session,
            orphan,
            expected_revision=None,
            new_revision=1,
            references=(),
            extractor_version="wf-v1",
            digest=refs.reference_set_digest(()),
            effective=orphan_effective,
        )
        prepared = batch.prepare_source_batch(
            session, requests(delete_source=True), lock_source_root=root_lock(owner.events)
        )
        assert prepared.source_keys == KEYS
        inventory = repository.list_source_sets_for_root(session, KEYS[0], for_update=True)
        indexed = {row.source_version: row for row in inventory}
        assert tuple(indexed) == ("v1", "v2", "v999") and indexed["v999"].effective is orphan_effective
        business_versions = set(session.execute(select(versions.c.id)).scalars())
        assert set(indexed) - business_versions == {"v999"}
        # The WF Owner can now reject orphan evidence before applying soft delete.
        assert repository.get_root_guard(session, KEYS[0]).source_revision == 2


@pytest.mark.parametrize(
    "malformed",
    [(), (replace(KEYS[1], tenant_id=202),), (KEYS[0], replace(KEYS[1], source_id="other-root")), (KEYS[0], KEYS[0])],
)
def test_batch_rejects_empty_duplicate_foreign_or_mixed_roots_before_prelock(engine, malformed):
    owner, _, _, batch = components()
    with Session(engine) as session, session.begin(), pytest.raises((ValueError, ResourceReferenceInvalidError)):
        values = tuple(SourceBindingRequest(key, (), "wf-v1", new_source=True) for key in malformed)
        batch.prepare_source_batch(session, values, lock_source_root=root_lock(owner.events))
    assert owner.events == []


@pytest.mark.parametrize("fail_second", [False, True])
async def test_native_async_batch_is_atomic_and_has_no_sync_owner_fallback(fail_second):
    owner, repository, runtime, batch = components()
    owner.async_only = True
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=refs.TABLES))
            await connection.run_sync(metadata.create_all)
        with refs.tenant(101):
            async with AsyncSession(database) as session, session.begin():
                await session.execute(insert(roots).values(id="root-1", value=10))
                await session.execute(
                    insert(versions),
                    [{"id": key.source_version, "root_id": key.source_id, "is_delete": False} for key in KEYS],
                )
                await session.execute(
                    insert(targets),
                    [
                        {"id": number, "state": "invalid_deleted" if fail_second and number == 3 else "valid"}
                        for number in [1, 2, 3]
                    ],
                )

                async def initial_root(_session):
                    return None

                for index, key in enumerate(KEYS):
                    item = await runtime.aprepare_source_bindings(
                        session,
                        key,
                        (ref(2 - index),),
                        extractor_version="wf-v1",
                        lock_source_root=initial_root,
                        new_source=True,
                    )
                    await runtime.aapply_source_bindings(session, item)

            async def lock(session, expected):
                owner.events.append(("root", expected))
                await session.execute(select(roots).where(roots.c.id == "root-1").with_for_update())
                return tuple(
                    replace(KEYS[0], source_version=value)
                    for value in (
                        await session.execute(select(versions.c.id).order_by(versions.c.id).with_for_update())
                    ).scalars()
                )

            owner.events.clear()
            owner.batch_mode = True
            async with AsyncSession(database) as session:
                try:
                    async with session.begin():
                        values = (
                            (requests()[0], replace(requests()[1], references=(ref(3),)))
                            if fail_second
                            else requests(delete_source=True)
                        )
                        prepared = await batch.aprepare_source_batch(session, values, lock_source_root=lock)
                        await session.execute(update(roots).values(value=20))
                        await batch.aapply_source_batch(session, prepared)
                except ResourceReferenceInvalidError:
                    assert fail_second
                else:
                    assert not fail_second
            async with AsyncSession(database) as session:
                assert (await session.execute(select(roots.c.value))).scalar_one() == (10 if fail_second else 20)
                assert (await repository.aget_root_guard(session, KEYS[0])).source_revision == (2 if fail_second else 4)
                assert [event[0] for event in owner.events] == ["prelock", "verify", "verify", "root"]
    finally:
        await database.dispose()
