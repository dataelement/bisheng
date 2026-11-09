"""T969: native direct deletion reference facts are complete, not authority.

覆盖 AC: AC-12, AC-28, AC-29, AC-72, AC-89, AC-90, AC-91, AC-94
Only persisted Coverage status is isolated; D1, Owner, receipts and stream are real.
"""

import asyncio
import importlib
from dataclasses import FrozenInstanceError, fields, is_dataclass
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.knowledge.application.reference_target_owner import KnowledgeReferenceTargetOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.knowledge.domain.repositories.knowledge_space_delete_repository import KnowledgeSpaceDeleteRepository
from bisheng.resource_reference.application.contracts import (
    CoverageStatus,
    GlobalCoverageStatus,
    SourceKey,
    SourceType,
    TargetKey,
    TargetLockReceipt,
    tenant_inventory_digest,
)
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as SourceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from bisheng.resource_reference.domain.models.resource_reference_tombstone import (
    ResourceReferenceTombstone as Tombstone,
)
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from bisheng.resource_reference.domain.repositories.reference_repository import OwnerTargetScope, ReferenceRepository
from test.knowledge_unification import test_direct_delete_scope as original

# Reuse actual D1's complete history, external sibling, DIR, unknown and empty rows.
deletion_tenant = original.deletion_tenant
db = original.db
selections = original.selections


def api():
    return importlib.import_module("bisheng.knowledge.application.direct_delete_reference_query")


class SqlStatus:
    """Same-session SQL test status port, never a permissive production adapter."""

    def __init__(self, session, ctx):
        self.session, self.ctx = session, ctx
        self.global_reads, self.local_reads = 0, 0

    async def aget_status(self, tenant_id, source_type, version):
        self.local_reads += 1
        self.ctx.events.append(("local", source_type))
        assert self.session.in_transaction()
        await self.session.execute(sa.select(Knowledge.id).where(Knowledge.id == 1).prefix_with("/*test-coverage*/"))
        if self.local_reads == 12 and getattr(self.ctx, "tail", None) is not None:
            await self.ctx.tail(self.session)
        ready = not (self.ctx.failure == "local" or (self.ctx.failure == "local_tail" and self.local_reads > 6))
        return CoverageStatus(tenant_id, source_type, version, ready, None if ready else "test-gap")

    async def aget_global_status(self, version):
        self.global_reads += 1
        self.ctx.events.append(("global", self.global_reads))
        with bypass_tenant_filter():
            await self.session.execute(sa.select(Knowledge.tenant_id).distinct().prefix_with("/*test-coverage*/"))
        epoch = 2 if self.ctx.failure == "epoch" and self.global_reads == 2 else 1
        ids = (101,) if self.ctx.failure == "observed" else (101, 202)
        if self.ctx.failure == "inventory" and self.global_reads == 2:
            ids = (101, 202, 303)
        return GlobalCoverageStatus(
            self.ctx.failure != "global",
            version,
            tuple(SourceType),
            tenant_inventory_digest(ids),
            epoch,
            ids,
            "test-gap" if self.ctx.failure == "global" else None,
        )


@pytest.fixture
async def context(db, monkeypatch):
    tables = (SourceSet, Binding, Tombstone)
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables | {model.__tablename__ for model in tables},
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: Knowledge.metadata.create_all(conn, tables=[model.__table__ for model in tables])
        )
    verifier = ReferenceTargetVerifier({"knowledge_file": KnowledgeReferenceTargetOwner()})
    repository = ReferenceRepository(verifier=verifier)
    ctx = SimpleNamespace(
        db=db,
        events=[],
        failure=None,
        ledgers=[],
        scope=KnowledgeSpaceDeleteRepository(),
        runtime=ReferenceBindingRuntime(repository, verifier),
    )

    def factory(session):
        ctx.events.append(("factory", session))
        port = SqlStatus(session, ctx)
        ctx.ledgers.append(port)
        return CoverageRepository(port, global_port=port)

    ctx.factory = factory
    ctx.db.statements.clear()
    return ctx


async def seed(ctx, *rows):
    """Rows: target id, source tenant/type/id/version/slot, optional target type."""
    groups = {}
    for ident, tenant, kind, source, version, slot, *target_type in rows:
        groups.setdefault((tenant, kind, source, version), []).append(
            (ident, slot, target_type[0] if target_type else "knowledge_file")
        )
    async with ctx.db.sessions() as session:
        with bypass_tenant_filter():
            for (tenant, kind, source, version), refs in groups.items():
                session.add(
                    SourceSet(
                        tenant_id=tenant,
                        source_type=kind,
                        source_id=source,
                        source_version=version,
                        source_revision=3,
                        extractor_version="native",
                        digest="a" * 64,
                        ready=True,
                        effective=True,
                    )
                )
                session.add_all(
                    Binding(
                        tenant_id=tenant,
                        source_type=kind,
                        source_id=source,
                        source_version=version,
                        source_revision=3,
                        slot_key=slot,
                        target_type=target_type,
                        target_id=str(ident),
                        target_tenant_id=101,
                        target_space_id="1",
                    )
                    for ident, slot, target_type in refs
                )
            await session.flush()
        await session.commit()
    ctx.db.statements.clear()


def query(ctx, **kwargs):
    return api().DirectDeleteReferenceQuery(
        runtime=ctx.runtime, coverage_factory=ctx.factory, scope_repository=ctx.scope, **kwargs
    )


async def collect(ctx, *keys, space_id=1):
    async with ctx.db.sessions() as session, session.begin():
        result = await query(ctx).acollect(session, space_id=space_id, selections=selections(*keys))
        assert ctx.events[0] == ("factory", session)
        assert not session.new and not session.dirty and not session.deleted
        return result


def assert_ready(ctx):
    port = ctx.ledgers[-1]
    assert port.global_reads == 2 and port.local_reads == 12
    assert [kind for label, kind in ctx.events if label == "local"] == list(SourceType) * 2
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in ctx.db.statements)


def detached(value):
    assert not isinstance(value, (TargetLockReceipt, OwnerTargetScope)) and not hasattr(value, "_sa_instance_state")
    if is_dataclass(value):
        for item in fields(value):
            detached(getattr(value, item.name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            detached(item)
    elif isinstance(value, dict):
        for item in value.values():
            detached(item)


async def test_actual_primary_folder_external_history_and_all_directory_targets_have_exact_source_unit_counts(context):
    ctx = context
    await seed(
        ctx,
        (20, 101, "assistant", "private-a", "current", "directory"),
        (30, 101, "assistant", "private-a", "current", "primary"),
        (31, 101, "assistant", "private-a", "current", "external-history"),
        (60, 101, "assistant", "private-a", "current", "other-unit"),
        (31, 202, "workflow_version", "foreign-secret", "v1", "history-1"),
        (60, 202, "workflow_version", "foreign-secret", "v2", "history-2"),
        (1, 101, "channel_sync", "space-only", "current", "space", "knowledge_space"),
        (40, 101, "channel_sync", "outside", "current", "unselected"),
    )
    result = await collect(ctx, ("folder", 20), ("knowledge_file", 60))
    assert [unit.resource_ids for unit in result.scope.units] == [(20, 30, 31), (60,)]
    assert len(result.references) == 6 and len(result.sources) == 3
    assert dict(result.source_counts) == {
        kind.value: {"assistant": 1, "workflow_version": 2}.get(kind.value, 0) for kind in SourceType
    }
    assert dict(result.slot_counts)["assistant"] == 4 and dict(result.slot_counts)["workflow_version"] == 2
    assert [dict(counts)["assistant"] for counts in result.unit_source_counts] == [1, 1]
    assert [dict(counts)["assistant"] for counts in result.unit_slot_counts] == [3, 1]
    assert [dict(counts)["workflow_version"] for counts in result.unit_source_counts] == [1, 1]
    assert result.observed_source_tenant_ids == (101, 202)
    assert {row.target.target_id for row in result.references} == {"20", "30", "31", "60"}
    assert all(row.source_revision == 3 and row.reference_id > 0 for row in result.references)
    assert {row.unit_index for row in result.references if row.target.target_id == "60"} == {1}
    assert result.inventory_hash == tenant_inventory_digest((101, 202)) and result.coverage_epoch == 1
    assert "private-a" not in repr(result) and "foreign-secret" not in repr(result.references[0])
    assert not {"can_delete", "can_execute", "can_force_delete", "receipt", "owner_scope"} & {
        f.name for f in fields(result)
    }
    detached(result)
    with pytest.raises(FrozenInstanceError):
        result.coverage_epoch = 2
    assert_ready(ctx)


async def test_historical_single_and_space_only_binding_do_not_expand_the_direct_targets(context):
    ctx = context
    await seed(
        ctx,
        (30, 101, "assistant", "primary", "current", "primary"),
        (1, 101, "channel_sync", "whole-space", "current", "space", "knowledge_space"),
    )
    result = await collect(ctx, ("knowledge_file", 31))
    assert result.scope.units[0].resource_ids == (31,) and not result.references and not result.sources
    assert {row.id for row in result.scope.versions} == {300, 301}
    assert all(count == 0 for _, count in result.source_counts + result.slot_counts)
    assert_ready(ctx)


@pytest.mark.parametrize("mode", ["empty", "issues", "mixed"])
async def test_empty_and_mixed_preserve_issues_and_still_verify_coverage_without_an_empty_owner_scope(
    context, monkeypatch, mode
):
    ctx, calls = context, []
    original_verify = ctx.runtime.verifier.averify_owner_targets

    async def verify(session, targets):
        assert targets
        calls.append(targets)
        return await original_verify(session, targets)

    monkeypatch.setattr(ctx.runtime.verifier, "averify_owner_targets", verify)
    keys = [] if mode == "empty" else [("knowledge_file", 999999), ("folder", 31)]
    if mode == "mixed":
        keys += [("knowledge_file", 61), ("knowledge_file", 62)]
    result = await collect(ctx, *keys, space_id=888 if mode == "empty" else 1)
    assert len(result.scope.issues) == (0 if mode == "empty" else 2)
    assert len(calls) == (1 if mode == "mixed" else 0)
    assert not result.references
    if mode == "empty":
        assert not result.scope.cleanup_identity
    if mode == "mixed":
        assert {row.status for row in result.scope.resources} == {None, 999}
    assert_ready(ctx)


async def test_legacy_paused_history_raw_bindings_remain_blocking_facts_without_guessing_owner(context):
    ctx = context
    await seed(ctx, (31, 101, "workflow_version", "paused-history", "v-old", "old-slot"))
    async with ctx.db.sessions() as session:
        await session.execute(
            sa.update(Binding).values(
                target_tenant_id=None,
                legacy_invalid_reason="target_missing",
                legacy_run_id="original",
                legacy_evidence_key="proof",
            )
        )
        await session.commit()
    ctx.db.statements.clear()
    result = await collect(ctx, ("knowledge_file", 31))
    assert len(result.references) == 1 and dict(result.source_counts)["workflow_version"] == 1
    assert result.references[0].source == SourceKey(101, "workflow_version", "paused-history", "v-old")
    assert_ready(ctx)


@pytest.mark.parametrize("failure", ["global", "local", "local_tail", "epoch", "inventory", "observed"])
async def test_coverage_failures_never_return_partial_or_zero_success_facts(context, failure):
    ctx = context
    ctx.failure = failure
    await seed(ctx, (31, 202, "assistant", "foreign", "current", "ref"))
    with pytest.raises(ReferenceCoverageNotReadyError):
        await collect(ctx, ("knowledge_file", 31))


@pytest.mark.parametrize("failure", ["missing", "revision", "inactive", "last_page", "source_type"])
async def test_actual_left_join_or_late_source_failure_prevents_any_collector_result(context, failure):
    ctx = context
    await seed(ctx, *((31, 101, "assistant", "a", "current", f"slot-{n}") for n in range(201)))
    async with ctx.db.sessions() as session:
        if failure == "missing":
            await session.execute(sa.delete(SourceSet))
        elif failure == "inactive":
            await session.execute(sa.update(SourceSet).values(effective=False))
        elif failure == "source_type":
            await session.execute(sa.update(SourceSet).values(source_type="unknown_source"))
            await session.execute(sa.update(Binding).values(source_type="unknown_source"))
        else:
            query = sa.update(Binding)
            if failure == "last_page":
                query = query.where(Binding.slot_key == "slot-200")
            await session.execute(query.values(source_revision=2))
        await session.commit()
    ctx.db.statements.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await collect(ctx, ("knowledge_file", 31))


@pytest.mark.parametrize("bad", ["runtime", "issuer", "coverage"])
async def test_explicit_actual_runtime_and_real_coverage_facade_are_required(context, bad):
    ctx = context
    if bad == "runtime":
        with pytest.raises((TypeError, ValueError)):
            api().DirectDeleteReferenceQuery(runtime=object(), coverage_factory=ctx.factory)
    elif bad == "issuer":
        other = ReferenceTargetVerifier({"knowledge_file": KnowledgeReferenceTargetOwner()})
        ctx.runtime.verifier = other
        with pytest.raises((TypeError, ValueError)):
            api().DirectDeleteReferenceQuery(runtime=ctx.runtime, coverage_factory=ctx.factory)
    else:
        async with ctx.db.sessions() as session, session.begin():
            collector = api().DirectDeleteReferenceQuery(runtime=ctx.runtime, coverage_factory=lambda active: None)
            with pytest.raises(ReferenceCoverageNotReadyError):
                await collector.acollect(session, space_id=1, selections=())


@pytest.mark.parametrize("bad", ["no_tx", "pending", "dirty", "deleted", "bypass", "selection", "space"])
async def test_native_clean_typed_context_is_required_before_any_sql(context, bad):
    ctx = context
    collector = query(ctx)
    async with ctx.db.sessions() as session:
        if bad != "no_tx":
            await session.begin()
        if bad == "pending":
            pending = File(tenant_id=101, knowledge_id=1, file_name="pending")
            session.add(pending)
        if bad in ("dirty", "deleted"):
            cached = await session.get(File, 31)
            if bad == "dirty":
                cached.remark = "caller pending"
            else:
                await session.delete(cached)
        ctx.db.statements.clear()
        with pytest.raises((ValueError, ResourceReferenceInvalidError)):
            if bad == "bypass":
                with bypass_tenant_filter():
                    await collector.acollect(session, space_id=1, selections=())
            else:
                await collector.acollect(
                    session,
                    space_id=True if bad == "space" else 1,
                    selections=[("folder", 20)] if bad == "selection" else (),
                )
        assert not ctx.db.statements
        if bad == "pending":
            assert pending in session.new and pending.id is None
        if bad == "dirty":
            assert cached in session.dirty and cached.remark == "caller pending"
        if bad == "deleted":
            assert cached in session.deleted
        await session.rollback()


async def test_collection_never_opens_a_session_calls_fga_disclosure_or_flushes(context, monkeypatch):
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.permission.application import business_authorization
    from bisheng.resource_reference.application.source_disclosure import SourceDisclosureRuntime

    ctx = context
    await seed(ctx, (31, 101, "assistant", "private", "current", "ref"))

    def unexpected(*args, **kwargs):
        raise AssertionError("SQL collector crossed its session or external IO boundary")

    async with ctx.db.sessions() as session, session.begin():
        monkeypatch.setattr(AsyncSession, "__init__", unexpected)
        monkeypatch.setattr(session, "flush", unexpected)
        monkeypatch.setattr(business_authorization, "require_business_action", unexpected)
        monkeypatch.setattr(SourceDisclosureRuntime, "adisclose_sources", unexpected)
        result = await query(ctx).acollect(session, space_id=1, selections=selections(("knowledge_file", 31)))
        assert len(result.references) == 1
    assert_ready(ctx)


@pytest.mark.parametrize("ancestor", [False, True])
async def test_actual_owner_deleting_receipt_cannot_become_zero_reference_success(context, ancestor):
    ctx = context
    async with ctx.db.sessions() as session:
        session.add(
            Tombstone(
                tenant_id=101,
                target_type="knowledge_space" if ancestor else "knowledge_file",
                target_id="1" if ancestor else "31",
                target_tenant_id=101,
                stage="deleting",
                operation_id="prior-delete",
                operation_type="force_delete",
                actor_type="user",
                actor_id="7",
            )
        )
        await session.commit()
    ctx.db.statements.clear()
    with pytest.raises(ResourceReferenceInvalidError) as failure:
        await collect(ctx, ("knowledge_file", 31))
    assert failure.value.kwargs["reason"] == "delete_reference_target_unavailable"
    assert all("LEFT OUTER JOIN business_reference_set" not in sql for sql, _ in ctx.db.statements)


@pytest.mark.parametrize("change", ["transaction", "tenant", "cancel"])
async def test_tail_context_or_cancellation_change_cannot_return_already_aggregated_facts(context, change):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

    ctx = context
    await seed(ctx, (31, 101, "assistant", "a", "current", "slot"))
    token = []

    async def tail(session):
        if change == "transaction":
            await session.rollback()
            await session.begin()
        elif change == "tenant":
            token.append(set_current_tenant_id(202))
        else:
            asyncio.current_task().cancel()
            await asyncio.sleep(0)

    ctx.tail = tail

    async def run():
        async with ctx.db.sessions() as session:
            await session.begin()
            try:
                return await query(ctx).acollect(session, space_id=1, selections=selections(("knowledge_file", 31)))
            finally:
                if token:
                    current_tenant_id.reset(token.pop())

    task = asyncio.create_task(run())
    with pytest.raises(asyncio.CancelledError if change == "cancel" else ResourceReferenceInvalidError):
        await task
    assert ctx.ledgers[-1].global_reads == 2 and ctx.ledgers[-1].local_reads == 12
    assert any("LEFT OUTER JOIN" in sql for sql, _ in ctx.db.statements)


async def test_real_coverage_facade_without_global_adapter_fails_closed_even_for_empty_selection(context):
    ctx = context
    async with ctx.db.sessions() as session, session.begin():
        collector = api().DirectDeleteReferenceQuery(
            runtime=ctx.runtime, coverage_factory=lambda active: CoverageRepository(SqlStatus(active, ctx))
        )
        with pytest.raises(ReferenceCoverageNotReadyError) as failure:
            await collector.acollect(session, space_id=1, selections=())
    assert failure.value.kwargs["reason"] == "global_coverage_port_missing"


@pytest.mark.parametrize("status", [1, 4, 5])
async def test_busy_history_still_contributes_its_exact_binding_for_later_app_classification(context, status):
    ctx = context
    await seed(ctx, (31, 101, "assistant", "busy-history", "current", "slot"))
    async with ctx.db.sessions() as session:
        await session.execute(sa.update(File).where(File.id == 31).values(status=status))
        await session.commit()
    ctx.db.statements.clear()
    result = await collect(ctx, ("folder", 20))
    assert result.scope.units[0].processing_file_ids == (31,)
    assert len(result.references) == 1 and result.references[0].target == TargetKey("knowledge_file", 31)
    assert dict(result.slot_counts)["assistant"] == 1
    assert_ready(ctx)


@pytest.mark.parametrize("corruption", ["foreign_owner", "wrong_space", "missing_space", "legacy", "unknown_owner"])
async def test_actual_inbound_metadata_must_match_verified_physical_target_before_complete(context, corruption):
    ctx = context
    await seed(ctx, (30, 101, "assistant", "a", "current", "selected"))
    values = {
        "foreign_owner": {"target_tenant_id": 202},
        "wrong_space": {"target_space_id": "2"},
        "missing_space": {"target_space_id": None},
        "legacy": {
            "legacy_invalid_reason": "target_missing",
            "legacy_run_id": "old-run",
            "legacy_evidence_key": "old-evidence",
        },
        "unknown_owner": {
            "target_tenant_id": None,
            "legacy_invalid_reason": "target_missing",
            "legacy_run_id": "old-run",
            "legacy_evidence_key": "old-evidence",
        },
    }[corruption]
    async with ctx.db.sessions() as session, session.begin():
        await session.execute(sa.update(Binding).where(Binding.target_id == "30").values(**values))
    ctx.db.statements.clear()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await collect(ctx, ("knowledge_file", 30))
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in ctx.db.statements)
