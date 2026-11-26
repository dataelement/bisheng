"""T331: revoked sharing retains only the original saved configuration identity.

覆盖 AC: AC-87, AC-88, AC-89, AC-91, AC-92
Real model/server, Flow/FlowVersion and reference rows share one transaction.
SQLite does not establish MySQL/DM8 lock scheduling behavior.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.database import tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.resource_reference.application.batch import BatchReferenceBindings, SourceBindingRequest
from bisheng.resource_reference.application.contracts import (
    DeletionEvidence,
    ReferenceSpec,
    SourceKey,
    TargetKey,
    VerifiedReferenceTarget,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_model_reference_owner as models
from test.knowledge_unification.test_ref_repo import tenant

TABLES = [*models.TABLES, BusinessReferenceSet.__table__, Flow.__table__, FlowVersion.__table__]
KEY = SourceKey(101, "workflow_version", "flow1", "1")
OLD = (ReferenceSpec("chat:model", TargetKey("model", "22")),)
OWN = (ReferenceSpec("chat:model", TargetKey("model", "11")),)


class DynamicSharing:
    def __init__(self, *, async_only=False):
        self.allowed, self.error, self.async_only = frozenset({2}), None, async_only

    def _get(self, tenant_id, server_ids):
        assert tenant_id == 101
        if self.error:
            raise self.error
        return self.allowed & frozenset(server_ids)

    def get_shared_server_ids(self, session, tenant_id, server_ids):
        if self.async_only:
            raise AssertionError("sync sharing invoked in async write")
        return self._get(tenant_id, server_ids)

    async def aget_shared_server_ids(self, session, tenant_id, server_ids):
        return self._get(tenant_id, server_ids)


@pytest.fixture(autouse=True)
def revoked_tenant(monkeypatch):
    names = {table.name for table in TABLES if "tenant_id" in table.columns}
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


def context(*, async_only=False, owner_type=ModelReferenceTargetOwner):
    sharing = DynamicSharing(async_only=async_only)
    owner = owner_type(sharing=sharing)
    verifier = ReferenceTargetVerifier({"model": owner})
    repository = ReferenceRepository(verifier=verifier)
    return SimpleNamespace(
        sharing=sharing,
        owner=owner,
        repository=repository,
        runtime=ReferenceBindingRuntime(repository, verifier),
        batch=BatchReferenceBindings(repository, verifier),
    )


def graph(model_id):
    return {"nodes": [], "edges": [], "model_id": str(model_id)}


def version_row(version, model_id=22, root="flow1"):
    return FlowVersion(id=int(version), flow_id=root, tenant_id=101, user_id=7, name="saved", data=graph(model_id))


def lock_root(session):
    session.exec(select(Flow).where(Flow.id == "flow1").with_for_update()).one()
    return session.exec(select(FlowVersion).where(FlowVersion.id == 1).with_for_update()).one()


async def alock_root(session):
    (await session.exec(select(Flow).where(Flow.id == "flow1").with_for_update())).one()
    return (await session.exec(select(FlowVersion).where(FlowVersion.id == 1).with_for_update())).one()


def seed(session, ctx, *, second=False):
    models.setup(session)
    session.add(Flow(id="flow1", tenant_id=101, user_id=7, name="actual source", data=graph(22)))
    session.add(version_row(1))
    if second:
        session.add(version_row(2, 11))
    session.flush()
    for key, references in [(KEY, OLD), *([(replace(KEY, source_version="2"), OWN)] if second else [])]:
        prepared = ctx.runtime.prepare_source_bindings(
            session, key, references, extractor_version="wf-v1", lock_source_root=lock_root, new_source=True
        )
        ctx.runtime.apply_source_bindings(session, prepared)


async def aseed(session, ctx, *, second=False):
    await session.run_sync(models.setup)  # Fixture INSERTs, not a runtime verification fallback.
    session.add(Flow(id="flow1", tenant_id=101, user_id=7, name="actual source", data=graph(22)))
    session.add(version_row(1))
    if second:
        session.add(version_row(2, 11))
    await session.flush()
    for key, references in [(KEY, OLD), *([(replace(KEY, source_version="2"), OWN)] if second else [])]:
        prepared = await ctx.runtime.aprepare_source_bindings(
            session, key, references, extractor_version="wf-v1", lock_source_root=alock_root, new_source=True
        )
        await ctx.runtime.aapply_source_bindings(session, prepared)


def desired(operation):
    return OLD if operation == "retain" else OWN if operation == "replace" else ()


def mutate(row, operation):
    if operation == "delete":
        row.is_delete = 1
    else:
        row.data = (
            graph(22 if operation == "retain" else 11)
            if operation in {"retain", "replace"}
            else {"nodes": [], "edges": []}
        )


@pytest.mark.parametrize("operation", ["retain", "replace", "clear", "delete"])
def test_revocation_allows_only_original_slot_retention_or_removal(engine, operation):
    ctx = context()
    with Session(engine) as session, session.begin():
        seed(session, ctx)
    ctx.sharing.allowed = frozenset()
    with Session(engine) as session, session.begin():
        prepared = ctx.runtime.prepare_source_bindings(
            session,
            KEY,
            desired(operation),
            extractor_version="wf-v1",
            lock_source_root=lock_root,
            effective=operation != "delete",
        )
        old_receipt = next(row for row in prepared.verified.context.receipts if row.target.key == OLD[0].target)
        assert old_receipt.target.state == "valid" and old_receipt.target.new_binding_allowed is False
        assert old_receipt.target.evidence is None
        mutate(session.get(FlowVersion, 1), operation)
        result = ctx.runtime.apply_source_bindings(session, prepared)
        assert result.retained_invalid == (1 if operation == "retain" else 0)
    with Session(engine) as session:
        actual = ctx.repository.list_source_references(session, KEY)
        assert [(row.slot_key, row.target_id) for row in actual] == [
            (ref.slot_key, ref.target.target_id) for ref in desired(operation)
        ]
        assert all(row.legacy_invalid_reason is None for row in actual)
        assert ctx.repository.get_source_set(session, KEY).effective is (operation != "delete")
        assert ctx.repository.get_root_guard(session, KEY).source_revision == 2
        assert not session.exec(select(ResourceReferenceTombstone)).all()
        if operation == "retain":
            with pytest.raises(ResourceReferenceInvalidError):
                ctx.runtime.require_source_valid(session, KEY)


@pytest.mark.parametrize("destination", ["new_slot", "copy", "new_version"])
def test_original_reference_never_authorizes_new_identity_after_revocation(engine, destination):
    ctx = context()
    with Session(engine) as session, session.begin():
        seed(session, ctx)
    ctx.sharing.allowed = frozenset()
    with pytest.raises(ResourceReferenceInvalidError), Session(engine) as session, session.begin():
        references, key = OLD, KEY
        if destination == "new_slot":
            references = (*OLD, ReferenceSpec("another:model", OLD[0].target))
        elif destination == "copy":
            session.add(Flow(id="copy", tenant_id=101, user_id=7, name="copy", data=graph(22)))
            session.add(version_row(3, root="copy"))
            key = replace(KEY, source_id="copy", source_version="3")
        else:
            session.add(version_row(2))
            key = replace(KEY, source_version="2")
        session.flush()
        prepared = ctx.runtime.prepare_source_bindings(
            session,
            key,
            references,
            extractor_version="wf-v1",
            lock_source_root=lock_root,
            new_source=destination != "new_slot",
        )
        ctx.runtime.apply_source_bindings(session, prepared)
    with Session(engine) as session:
        assert session.get(Flow, "copy") is None and session.get(FlowVersion, 2) is None
        assert ctx.repository.get_source_set(session, KEY).source_revision == 1
        assert [row.target_id for row in ctx.repository.list_source_references(session, KEY)] == ["22"]


@pytest.mark.parametrize("borrow", [False, True])
def test_batch_checks_the_original_reference_per_source_version(engine, borrow):
    ctx = context()
    second = replace(KEY, source_version="2")
    with Session(engine) as session, session.begin():
        seed(session, ctx, second=True)
    ctx.sharing.allowed = frozenset()

    def root(session, expected):
        session.exec(select(Flow).where(Flow.id == "flow1").with_for_update()).one()
        session.exec(
            select(FlowVersion).where(FlowVersion.flow_id == "flow1").order_by(FlowVersion.id).with_for_update()
        ).all()
        return KEY, second

    if borrow:
        with pytest.raises(ResourceReferenceInvalidError), Session(engine) as session, session.begin():
            ctx.batch.prepare_source_batch(
                session,
                (SourceBindingRequest(KEY, OLD, "wf-v1"), SourceBindingRequest(second, OLD, "wf-v1")),
                lock_source_root=root,
            )
    else:
        with Session(engine) as session, session.begin():
            prepared = ctx.batch.prepare_source_batch(
                session,
                tuple(SourceBindingRequest(key, (), "wf-v1", effective=False) for key in (KEY, second)),
                lock_source_root=root,
            )
            for row in session.exec(select(FlowVersion)).all():
                row.is_delete = 1
            ctx.batch.apply_source_batch(session, prepared)
    with Session(engine) as session:
        assert ctx.repository.get_root_guard(session, KEY).source_revision == (2 if borrow else 4)
        assert ctx.repository.get_source_set(session, KEY).effective is borrow
        assert ctx.repository.get_source_set(session, second).effective is borrow


@pytest.mark.parametrize("operation", ["retain", "replace", "clear", "delete"])
async def test_native_async_revoked_share_repair_and_execution_gate(operation):
    database = create_async_engine("sqlite+aiosqlite://")
    ctx = context(async_only=True)
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        async with AsyncSession(database) as session, session.begin():
            await aseed(session, ctx)
        ctx.sharing.allowed = frozenset()
        async with AsyncSession(database) as session, session.begin():
            prepared = await ctx.runtime.aprepare_source_bindings(
                session,
                KEY,
                desired(operation),
                extractor_version="wf-v1",
                lock_source_root=alock_root,
                effective=operation != "delete",
            )
            mutate(await session.get(FlowVersion, 1), operation)
            await ctx.runtime.aapply_source_bindings(session, prepared)
        async with AsyncSession(database) as session:
            rows = await ctx.repository.alist_source_references(session, KEY)
            assert [row.target_id for row in rows] == [ref.target.target_id for ref in desired(operation)]
            assert (await ctx.repository.aget_root_guard(session, KEY)).source_revision == 2
            if operation == "retain":
                with pytest.raises(ResourceReferenceInvalidError):
                    await ctx.runtime.arequire_source_valid(session, KEY)
    finally:
        await database.dispose()


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_sharing_lookup_failure_is_not_reinterpreted_as_retention_permission(engine, asynchronous):
    ctx = context(async_only=asynchronous)
    failure = RuntimeError("sharing lookup unavailable")
    if not asynchronous:
        with Session(engine) as session, session.begin():
            seed(session, ctx)
        ctx.sharing.error = failure
        with Session(engine) as session, session.begin(), pytest.raises(RuntimeError) as caught:
            ctx.runtime.prepare_source_bindings(
                session, KEY, OWN, extractor_version="wf-v1", lock_source_root=lock_root
            )
        assert caught.value is failure
        return
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        async with AsyncSession(database) as session, session.begin():
            await aseed(session, ctx)
        ctx.sharing.error = failure
        async with AsyncSession(database) as session, session.begin():
            with pytest.raises(RuntimeError) as caught:
                await ctx.runtime.aprepare_source_bindings(
                    session, KEY, OWN, extractor_version="wf-v1", lock_source_root=alock_root
                )
            assert caught.value is failure
    finally:
        await database.dispose()


class RetainOnlySqlOwner(ModelReferenceTargetOwner):
    """R2 contract double: real SQL observations, only eligibility is injected."""

    retain_only = False

    @staticmethod
    def _receipt(session, source_key, observation, legacy, issuer):
        receipt = ModelReferenceTargetOwner._receipt(session, source_key, observation, legacy, issuer)
        if issuer.retain_only and observation.target_tenant_id == 1:
            return replace(receipt, target=replace(receipt.target, new_binding_allowed=False))
        return receipt


def test_r2_eligibility_marker_is_bound_to_the_original_slot_and_cannot_be_forged(engine):
    ctx = context(owner_type=RetainOnlySqlOwner)
    with Session(engine) as session, session.begin():
        seed(session, ctx)
        ctx.owner.retain_only = True
        prepared = ctx.runtime.prepare_source_bindings(
            session, KEY, OLD, extractor_version="wf-v1", lock_source_root=lock_root
        )
        receipt = prepared.verified.context.receipts[0]
        forged = replace(receipt, target=replace(receipt.target, new_binding_allowed=True))
        bad = replace(
            prepared,
            verified=replace(prepared.verified, context=replace(prepared.verified.context, receipts=(forged,))),
        )
        with pytest.raises(ResourceReferenceInvalidError):
            ctx.runtime.apply_source_bindings(session, bad)
        expanded = ctx.runtime.prepare_source_bindings(
            session,
            KEY,
            (*OLD, ReferenceSpec("new:model", OLD[0].target)),
            extractor_version="wf-v1",
            lock_source_root=lock_root,
        )
        with pytest.raises(ResourceReferenceInvalidError):
            ctx.runtime.apply_source_bindings(session, expanded)
        assert ctx.runtime.apply_source_bindings(session, prepared).retained_invalid == 1


@pytest.mark.parametrize("kind,state", [("knowledge_space", "valid"), ("model", "invalid_deleted")])
def test_eligibility_restriction_is_only_a_live_model_fact(kind, state):
    key = TargetKey(kind, "22")
    evidence = DeletionEvidence("delete", key, 1, "deleted") if state == "invalid_deleted" else None
    with pytest.raises(ValueError):
        VerifiedReferenceTarget(
            key,
            1,
            "22" if kind == "knowledge_space" else None,
            "2" if kind == "model" else None,
            state,
            "r1",
            evidence,
            new_binding_allowed=False,
        )


def test_owned_model_owner_query_keeps_full_binding_eligibility(engine):
    ctx = context()
    with Session(engine) as session, session.begin():
        seed(session, ctx)
    ctx.sharing.allowed = frozenset()
    with tenant(1), Session(engine) as session, session.begin():
        receipt = ctx.runtime.verifier.verify_owner_targets(session, (OLD[0].target,))[0]
        assert receipt.target.new_binding_allowed is True


@pytest.mark.parametrize("destination", ["new_slot", "copy", "new_version"])
async def test_async_new_identity_cannot_borrow_the_original_reference(destination):
    ctx = context(async_only=True)
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        async with AsyncSession(database) as session, session.begin():
            await aseed(session, ctx)
        ctx.sharing.allowed = frozenset()
        async with AsyncSession(database) as session:
            with pytest.raises(ResourceReferenceInvalidError):
                async with session.begin():
                    key, references = KEY, OLD
                    if destination == "new_slot":
                        references = (*OLD, ReferenceSpec("another:model", OLD[0].target))
                    elif destination == "copy":
                        session.add(Flow(id="copy", tenant_id=101, user_id=7, name="copy", data=graph(22)))
                        session.add(version_row(3, root="copy"))
                        key = replace(KEY, source_id="copy", source_version="3")
                    else:
                        session.add(version_row(2))
                        key = replace(KEY, source_version="2")
                    await session.flush()
                    prepared = await ctx.runtime.aprepare_source_bindings(
                        session,
                        key,
                        references,
                        extractor_version="wf-v1",
                        lock_source_root=alock_root,
                        new_source=destination != "new_slot",
                    )
                    await ctx.runtime.aapply_source_bindings(session, prepared)
        async with AsyncSession(database) as session:
            assert (await ctx.repository.aget_root_guard(session, KEY)).source_revision == 1
            assert await session.get(Flow, "copy") is None and await session.get(FlowVersion, 2) is None
    finally:
        await database.dispose()


@pytest.mark.parametrize("borrow", [False, True])
async def test_async_batch_uses_each_sources_own_saved_binding(borrow):
    ctx = context(async_only=True)
    second = replace(KEY, source_version="2")
    database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with database.begin() as connection:
            await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
        async with AsyncSession(database) as session, session.begin():
            await aseed(session, ctx, second=True)
        ctx.sharing.allowed = frozenset()

        async def root(session, expected):
            (await session.exec(select(Flow).where(Flow.id == "flow1").with_for_update())).one()
            (
                await session.exec(
                    select(FlowVersion).where(FlowVersion.flow_id == "flow1").order_by(FlowVersion.id).with_for_update()
                )
            ).all()
            return KEY, second

        async with AsyncSession(database) as session:
            try:
                async with session.begin():
                    values = (
                        (SourceBindingRequest(KEY, OLD, "wf-v1"), SourceBindingRequest(second, OLD, "wf-v1"))
                        if borrow
                        else tuple(SourceBindingRequest(key, (), "wf-v1", effective=False) for key in (KEY, second))
                    )
                    prepared = await ctx.batch.aprepare_source_batch(session, values, lock_source_root=root)
                    for row in (await session.exec(select(FlowVersion))).all():
                        row.is_delete = 1
                    await ctx.batch.aapply_source_batch(session, prepared)
            except ResourceReferenceInvalidError:
                assert borrow
            else:
                assert not borrow
        async with AsyncSession(database) as session:
            assert (await ctx.repository.aget_root_guard(session, KEY)).source_revision == (2 if borrow else 4)
            assert (await ctx.repository.aget_source_set(session, second)).effective is borrow
    finally:
        await database.dispose()


@pytest.mark.parametrize("value", [0, None, "false"])
def test_new_binding_allowed_requires_a_boolean(value):
    with pytest.raises(ValueError):
        VerifiedReferenceTarget(OLD[0].target, 1, None, "2", "valid", "r1", new_binding_allowed=value)


def test_malformed_sharing_result_does_not_enable_original_slot_retention(engine):
    ctx = context()
    with Session(engine) as session, session.begin():
        seed(session, ctx)

    class MalformedSharing:
        def get_shared_server_ids(self, *args):
            return frozenset({True})

    ctx.owner.sharing = MalformedSharing()
    with Session(engine) as session, session.begin(), pytest.raises(ResourceReferenceInvalidError):
        ctx.runtime.prepare_source_bindings(session, KEY, OWN, extractor_version="wf-v1", lock_source_root=lock_root)
