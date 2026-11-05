"""Only actual Owner verification can issue reference capabilities.

覆盖 AC: AC-72, AC-87, AC-89
Owner doubles read real isolated SQL rows; caller claims are never authority.
"""

from dataclasses import replace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.bindings import ReferenceBindings
from bisheng.resource_reference.application.contracts import (
    BindingWriteContext,
    ReferenceSpec,
    SourceKey,
    TargetKey,
    TargetLockReceipt,
    TransactionIdentity,
    VerifiedReferenceSet,
    VerifiedReferenceTarget,
    reference_set_digest,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as ref_fixtures

tenant_events = ref_fixtures.tenant_events
metadata = MetaData()
targets = Table(
    "test_reference_targets",
    metadata,
    Column("kind", String, primary_key=True),
    Column("id", Integer, primary_key=True),
    Column("tenant_id", Integer),
    Column("space_id", Integer),
)


class SqlOwner:
    def __init__(self, *, deny=False):
        self.deny, self.calls = deny, []

    def _observed(self, session, target_keys, source_key, operation, rows):
        self.calls.append((target_keys, source_key, operation))
        if self.deny:
            raise ResourceReferenceInvalidError(reason="owner_refused")
        receipts = []
        for key, row in zip(target_keys, rows, strict=True):
            if row is None or (source_key is None and row.tenant_id != ReferenceRepository.current_tenant_id()):
                raise ResourceReferenceInvalidError(reason="target_owner_denied")
            observed = VerifiedReferenceTarget(
                key,
                row.tenant_id,
                str(row.space_id) if row.space_id else None,
                "7" if key.target_type == "model" else None,
                "valid",
                "r1",
            )
            receipts.append(TargetLockReceipt(source_key, observed, TransactionIdentity.capture(session), self))
        return tuple(receipts)

    def lock_and_verify(self, session, target_keys, source_key, operation):
        rows = [
            session.execute(
                select(targets)
                .where(targets.c.kind == key.target_type, targets.c.id == int(key.target_id))
                .with_for_update()
            ).first()
            for key in target_keys
        ]
        return self._observed(session, target_keys, source_key, operation, rows)

    async def alock_and_verify(self, session, target_keys, source_key, operation):
        rows = []
        for key in target_keys:
            rows.append(
                (
                    await session.execute(
                        select(targets)
                        .where(targets.c.kind == key.target_type, targets.c.id == int(key.target_id))
                        .with_for_update()
                    )
                ).first()
            )
        return self._observed(session, target_keys, source_key, operation, rows)


@pytest.fixture
def engine(f118_engine):
    SQLModel.metadata.create_all(f118_engine, tables=ref_fixtures.TABLES)
    metadata.create_all(f118_engine)
    return f118_engine


def forged(session, owner, *, source_key=None, tenant_id=101):
    key = TargetKey("model", "1")
    claimed = VerifiedReferenceTarget(key, tenant_id, None, "7", "valid", "r1")
    return TargetLockReceipt(source_key, claimed, TransactionIdentity.capture(session), owner)


def binding_set(session, source_key, receipts):
    refs = (ReferenceSpec("model", TargetKey("model", "1")),)
    context = BindingWriteContext(
        source_key, 0, 0, (refs[0].target,), reference_set_digest(()), receipts, TransactionIdentity.capture(session)
    )
    return VerifiedReferenceSet(refs, "test-v1", context)


def test_self_reported_owner_cannot_query_another_tenants_inbound_rows(engine):
    owner = SqlOwner()
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    with engine.begin() as connection:
        connection.execute(insert(targets).values(kind="model", id=1, tenant_id=202))
    with ref_fixtures.tenant(202), Session(engine) as session, session.begin():
        key = ref_fixtures.source(tenant_id=202)
        bound = ref_fixtures.row(key)
        bound.target_tenant_id = 202
        ref_fixtures.write(repo, session, key, (bound,))
    with Session(engine) as session, session.begin():
        fake = forged(session, owner, tenant_id=101)
        with pytest.raises(ResourceReferenceInvalidError):
            repo.target_owner_scope(session, (fake,))
        with pytest.raises(ResourceReferenceInvalidError):
            verifier.verify_owner_targets(session, (TargetKey("model", "1"),))
        assert len(owner.calls) == 1 and owner.calls[0][2] == "owner_query"


def test_self_minted_receipt_cannot_bypass_an_owner_that_refuses_binding(engine):
    owner = SqlOwner(deny=True)
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    bindings = ReferenceBindings(repo, verifier)
    source = SourceKey(101, "assistant", "a1", "current")
    with engine.begin() as connection:
        connection.execute(insert(targets).values(kind="model", id=1, tenant_id=101))
    with Session(engine) as session, session.begin():
        candidate = binding_set(session, source, (forged(session, owner, source_key=source),))
        with pytest.raises(ResourceReferenceInvalidError):
            bindings.replace_source_bindings(session, source, None, 1, candidate, True)
        with pytest.raises(ResourceReferenceInvalidError):
            verifier.verify_targets(session, source, (TargetKey("model", "1"),))
        assert len(owner.calls) == 1
        assert repo.get_source_set(session, source) is None and repo.get_root_guard(session, source) is None


def test_valid_owner_issuance_is_required_for_binding_query_and_receipt_identity(engine):
    owner = SqlOwner()
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    bindings = ReferenceBindings(repo, verifier)
    source = SourceKey(101, "assistant", "a1", "current")
    with engine.begin() as connection:
        connection.execute(insert(targets).values(kind="model", id=1, tenant_id=101))
    with Session(engine) as session, session.begin():
        issued = verifier.verify_targets(session, source, (TargetKey("model", "1"),))
        with pytest.raises(ResourceReferenceInvalidError):
            bindings.replace_source_bindings(
                session, source, None, 1, binding_set(session, source, (replace(issued[0]),)), True
            )
        assert (
            bindings.replace_source_bindings(session, source, None, 1, binding_set(session, source, issued), True).added
            == 1
        )
        with pytest.raises(ResourceReferenceInvalidError):
            repo.target_owner_scope(session, issued)  # bind receipts are not owner-query capabilities
        queried = verifier.verify_owner_targets(session, (TargetKey("model", "1"),))
        scope = repo.target_owner_scope(session, queried)
        assert len(repo.list_inbound_for_owner(session, scope)) == 1
        with pytest.raises(ResourceReferenceInvalidError):
            repo.target_owner_scope(session, (replace(queried[0]),))
        other = ReferenceTargetVerifier({"model": owner})
        with pytest.raises(ResourceReferenceInvalidError):
            ReferenceRepository(verifier=other).target_owner_scope(session, queried)


def test_same_owner_receives_space_and_file_keys_as_one_batch(engine):
    model_owner, knowledge_owner = SqlOwner(), SqlOwner()
    verifier = ReferenceTargetVerifier(
        {"model": model_owner, "knowledge_space": knowledge_owner, "knowledge_file": knowledge_owner}
    )
    with engine.begin() as connection:
        connection.execute(
            insert(targets),
            [
                {"kind": "model", "id": 1, "tenant_id": 101, "space_id": None},
                {"kind": "knowledge_space", "id": 3, "tenant_id": 101, "space_id": 3},
                {"kind": "knowledge_file", "id": 9, "tenant_id": 101, "space_id": 3},
            ],
        )
    with Session(engine) as session, session.begin():
        result = verifier.verify_owner_targets(
            session, (TargetKey("knowledge_file", "9"), TargetKey("model", "1"), TargetKey("knowledge_space", "3"))
        )
        assert len(result) == 3 and len(model_owner.calls) == len(knowledge_owner.calls) == 1
        assert [key.target_type.value for key in knowledge_owner.calls[0][0]] == ["knowledge_space", "knowledge_file"]


async def test_async_verification_uses_async_owner_and_same_transaction():
    class AsyncOnlyOwner(SqlOwner):
        def lock_and_verify(self, *args, **kwargs):
            raise AssertionError("sync Owner called in async execution")

    owner = AsyncOnlyOwner()
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    bindings = ReferenceBindings(repo, verifier)
    database = create_async_engine("sqlite+aiosqlite://")
    async with database.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=ref_fixtures.TABLES))
        await connection.run_sync(metadata.create_all)
        await connection.execute(insert(targets).values(kind="model", id=1, tenant_id=101))
    source = SourceKey(101, "assistant", "a1", "current")
    try:
        async with AsyncSession(database) as session, session.begin():
            issued = await verifier.averify_targets(session, source, (TargetKey("model", "1"),))
            candidate = binding_set(session, source, issued)
            result = await bindings.areplace_source_bindings(
                session, source, None, 1, candidate, True
            )
            assert result.added == 1 and len(owner.calls) == 1
        async with AsyncSession(database) as session, session.begin():
            with pytest.raises(ResourceReferenceInvalidError):
                await bindings.areplace_source_bindings(
                    session, source, 1, 2, candidate, True
                )
    finally:
        await database.dispose()
