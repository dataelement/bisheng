"""Reference storage preserves version, transaction and tenant boundaries.

覆盖 AC: AC-72, AC-87, AC-88, AC-89
SQLite exercises SQL storage semantics only, not MySQL/DM8 lock behavior.
"""

from contextlib import contextmanager
from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    ReferenceState,
    SourceKey,
    TargetKey,
    TargetLockReceipt,
    TargetType,
    TransactionIdentity,
    VerifiedReferenceTarget,
    reference_set_digest,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository

TABLES = [BusinessReferenceSet.__table__, BusinessResourceReference.__table__, ResourceReferenceTombstone.__table__]


class ModelOwner:
    """Pure observation double; SQL-backed verification is covered separately."""

    def observation(self, target):
        return VerifiedReferenceTarget(target, 101, None, "1", ReferenceState.VALID, "r1")

    def lock_and_verify(self, session, target_keys, source_key, operation):
        return tuple(
            TargetLockReceipt(source_key, self.observation(target), TransactionIdentity.capture(session), self)
            for target in target_keys
        )

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        # No SQL in this fixture. Native async Owner I/O has its own regression.
        return self.lock_and_verify(session, target_keys, source_key, operation)


@contextmanager
def tenant(tenant_id):
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest.fixture(autouse=True)
def tenant_events(monkeypatch):
    """Use the real isolation hook, without importing deployment dependencies."""
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


def source(version="current", tenant_id=101, source_id="assistant-1"):
    return SourceKey(tenant_id, "assistant", source_id, version)


def target(target_id="1"):
    return TargetKey("model", target_id)


def row(key, target_id="1", revision=1, slot="model", **kwargs):
    return BusinessResourceReference(
        tenant_id=key.tenant_id,
        source_type=key.source_type.value,
        source_id=key.source_id,
        source_version=key.source_version,
        slot_key=slot,
        target_type="model",
        target_id=target_id,
        target_tenant_id=101,
        source_revision=revision,
        **kwargs,
    )


def write(repo, session, key, rows, expected=None, revision=1):
    refs = tuple(ReferenceSpec(r.slot_key, TargetKey(r.target_type, r.target_id)) for r in rows)
    return repo.replace_source_set(
        session,
        key,
        expected_revision=expected,
        new_revision=revision,
        references=rows,
        extractor_version="test-v1",
        digest=reference_set_digest(refs),
        effective=True,
    )


def test_repeated_save_preserves_row_identity_and_zero_reference_set(engine):
    repo = ReferenceRepository()
    key = source()
    with Session(engine) as session, session.begin():
        write(repo, session, key, (row(key),))
        original_id = repo.list_source_references(session, key)[0].id
        write(repo, session, key, (row(key, revision=2),), expected=1, revision=2)
        assert [r.id for r in repo.list_source_references(session, key)] == [original_id]
        write(repo, session, key, (), expected=2, revision=3)
        assert repo.list_source_references(session, key) == ()
        saved = repo.get_source_set(session, key)
        assert saved.source_revision == 3 and saved.ready
        assert saved.digest == reference_set_digest(())


def test_versions_are_independent_and_stale_cas_is_rejected(engine):
    repo = ReferenceRepository()
    current, old = source("v2"), source("v1")
    with Session(engine) as session, session.begin():
        write(repo, session, current, (row(current),))
        write(repo, session, old, (row(old, "2"),))
        write(repo, session, current, (), expected=1, revision=2)
        assert [r.target_id for r in repo.list_source_references(session, old)] == ["2"]
        with pytest.raises(ResourceReferenceInvalidError) as raised:
            write(repo, session, current, (), expected=1, revision=3)
        assert raised.value.kwargs["reason"] == "source_revision_conflict"


def test_repository_never_commits_the_owners_transaction(engine):
    repo = ReferenceRepository()
    key = source()
    with Session(engine) as session:
        write(repo, session, key, (row(key),))
        session.rollback()
    with Session(engine) as session:
        assert repo.get_source_set(session, key) is None
        assert repo.list_source_references(session, key) == ()


def test_explicit_other_source_tenant_cannot_be_written(engine):
    repo = ReferenceRepository()
    foreign = source(tenant_id=202)
    with Session(engine) as session:
        with pytest.raises(ResourceReferenceInvalidError) as raised:
            write(repo, session, foreign, (row(foreign),))
        assert raised.value.kwargs["reason"] == "source_tenant_mismatch"
        session.rollback()


def test_root_guard_is_shared_across_versions_and_not_a_source(engine):
    repo = ReferenceRepository()
    with Session(engine) as session, session.begin():
        assert repo.advance_root_guard(session, source("v1"), expected_revision=0, new_revision=1) == 1
        assert repo.get_root_guard(session, source("v2")).source_revision == 1
        assert repo.advance_root_guard(session, source("v2"), expected_revision=1, new_revision=2) == 2
        assert repo.list_source_sets(session, source_type="assistant") == ()
        with pytest.raises(ResourceReferenceInvalidError):
            repo.advance_root_guard(session, source("v1"), expected_revision=1, new_revision=3)


def test_normal_reads_are_source_tenant_scoped_and_owner_reads_need_exact_capability(engine):
    owner = ModelOwner()
    verifier = ReferenceTargetVerifier({TargetType.MODEL: owner})
    repo = ReferenceRepository(verifier=verifier)
    with Session(engine) as session, session.begin():
        write(repo, session, source(), (row(source()),))
    with tenant(202), Session(engine) as session, session.begin():
        key = source(tenant_id=202)
        write(repo, session, key, (row(key),))
        assert len(repo.list_inbound_targets(session, (target(),))) == 1
        with pytest.raises(ResourceReferenceInvalidError):
            repo.get_source_set(session, source())
    with Session(engine) as session, session.begin():
        assert len(repo.list_inbound_targets(session, (target(),))) == 1
        receipts = verifier.verify_owner_targets(session, (target(),))
        scope = repo.target_owner_scope(session, receipts)
        assert {r.tenant_id for r in repo.list_inbound_for_owner(session, scope)} == {101, 202}
        assert repo.list_inbound_targets(session, (target("2"),)) == ()
        with pytest.raises(ResourceReferenceInvalidError):
            repo.target_owner_scope(session, (replace(receipts[0], issuer=object()),))
    with Session(engine) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            repo.list_inbound_for_owner(session, scope)


def test_storage_failure_propagates_instead_of_reporting_no_references(engine, monkeypatch):
    repo = ReferenceRepository()
    with Session(engine) as session:
        monkeypatch.setattr(
            session, "execute", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("storage unavailable"))
        )
        with pytest.raises(RuntimeError, match="storage unavailable"):
            repo.list_inbound_targets(session, (target(),))


def test_target_owner_capability_cannot_be_forged_retargeted_or_emptied(engine):
    owner = ModelOwner()
    verifier = ReferenceTargetVerifier({TargetType.MODEL: owner})
    repo = ReferenceRepository(verifier=verifier)
    with Session(engine) as session, session.begin():
        with pytest.raises(ResourceReferenceInvalidError):
            ReferenceRepository().target_owner_scope(session, ())
        scope = repo.target_owner_scope(session, verifier.verify_owner_targets(session, (target(),)))
        for forged in [replace(scope, targets=()), replace(scope, targets=(target("2"),))]:
            with pytest.raises(ResourceReferenceInvalidError):
                repo.list_inbound_for_owner(session, forged)


async def test_async_equivalent_supports_empty_set_and_external_rollback():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
    repo = ReferenceRepository()
    key = source()
    try:
        async with AsyncSession(engine) as session:
            await repo.areplace_source_set(
                session,
                key,
                expected_revision=None,
                new_revision=1,
                references=(),
                extractor_version="test-v1",
                digest=reference_set_digest(()),
                effective=True,
            )
            assert (await repo.aget_source_set(session, key)).ready
            await session.rollback()
        async with AsyncSession(engine) as session:
            assert await repo.aget_source_set(session, key) is None
    finally:
        await engine.dispose()


def test_root_inventory_is_exact_tenant_type_id_includes_inactive_and_refreshes_current_rows(engine):
    repo = ReferenceRepository()
    first, second = source("v1"), source("v2")
    with Session(engine) as session, session.begin():
        repo.advance_root_guard(session, first, expected_revision=0, new_revision=1)
        write(repo, session, second, (row(second),))
        write(repo, session, first, ())
        write(repo, session, source("v999"), ())
        write(repo, session, source("v1", source_id="unrelated"), ())
        write(repo, session, SourceKey(101, "knowledge", first.source_id, "v1"), ())
        cached = repo.get_source_set(session, first)
        from sqlalchemy import update

        session.execute(
            update(BusinessReferenceSet)
            .where(BusinessReferenceSet.id == cached.id, BusinessReferenceSet.tenant_id == 101)
            .values(effective=False)
            .execution_options(synchronize_session=False)
        )
        actual = repo.list_source_sets_for_root(session, first, for_update=True)
        assert [item.source_version for item in actual] == ["v1", "v2", "v999"]
        assert [item.effective for item in actual] == [False, True, True]
        assert all(item.record_kind == "source" for item in actual)
    with tenant(202), Session(engine) as session, session.begin():
        foreign = source("v3", tenant_id=202)
        write(repo, session, foreign, ())
        assert [item.source_version for item in repo.list_source_sets_for_root(session, foreign)] == ["v3"]
        with pytest.raises(ResourceReferenceInvalidError):
            repo.list_source_sets_for_root(session, first)
    with Session(engine) as session:
        assert [item.source_version for item in repo.list_source_sets_for_root(session, second)] == ["v1", "v2", "v999"]


async def test_native_async_exact_root_inventory_keeps_inactive_and_external_rollback():
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        repo = ReferenceRepository()
        async with AsyncSession(database) as session:
            for version, effective in [("v2", True), ("v1", False)]:
                await repo.areplace_source_set(
                    session,
                    source(version),
                    expected_revision=None,
                    new_revision=1,
                    references=(),
                    extractor_version="test-v1",
                    digest=reference_set_digest(()),
                    effective=effective,
                )
            rows = await repo.alist_source_sets_for_root(session, source(), for_update=True)
            assert [(row.source_version, row.effective) for row in rows] == [("v1", False), ("v2", True)]
            await session.rollback()
            assert await repo.alist_source_sets_for_root(session, source()) == ()
    finally:
        await database.dispose()


def equality_owner_scope_copy(original):
    class EqualScope(type(original)):
        def __hash__(self):
            return hash(original)

        def __eq__(self, other):
            return other is original or other is self

    return EqualScope(
        original.transaction, original.owner_tenant_id, original.targets, original._receipts, original._authority
    )


def test_owner_scope_requires_the_original_object_even_when_a_clone_compares_equal(engine):
    owner = ModelOwner()
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    with Session(engine) as session, session.begin():
        write(repo, session, source(), (row(source()),))
        issued = verifier.verify_owner_targets(session, (target(),))
        scope = repo.target_owner_scope(session, issued)
        assert len(repo.list_inbound_for_owner(session, scope)) == 1
        forged = equality_owner_scope_copy(scope)
        assert forged is not scope
        with pytest.raises(ResourceReferenceInvalidError):
            repo.list_inbound_for_owner(session, forged)


async def test_async_owner_query_rejects_an_equality_clone_but_accepts_the_original():
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=TABLES))
        owner = ModelOwner()
        verifier = ReferenceTargetVerifier({"model": owner})
        repo = ReferenceRepository(verifier=verifier)
        async with AsyncSession(database) as session, session.begin():
            key = source()
            await repo.areplace_source_set(
                session,
                key,
                expected_revision=None,
                new_revision=1,
                references=(row(key),),
                extractor_version="test-v1",
                digest=reference_set_digest((ReferenceSpec("model", target()),)),
                effective=True,
            )
            receipts = await verifier.averify_owner_targets(session, (target(),))
            scope = repo.target_owner_scope(session, receipts)
            assert len(await repo.alist_inbound_for_owner(session, scope)) == 1
            with pytest.raises(ResourceReferenceInvalidError):
                await repo.alist_inbound_for_owner(session, equality_owner_scope_copy(scope))
    finally:
        await database.dispose()
