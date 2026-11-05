"""T375: real knowledge target reads under exact source authority.

覆盖 AC: AC-37, AC-68, AC-89, AC-91, AC-92
Source authorization is a SQL-backed test port; target facts use real Owners.
"""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.database.models.assistant import Assistant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey, reference_set_digest
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
    payload_digest,
)
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification import test_source_read_scope as scopes

TABLES = [
    Assistant.__table__,
    Knowledge.__table__,
    KnowledgeFile.__table__,
    KnowledgeUnificationRun.__table__,
    BusinessReferenceSet.__table__,
    BusinessResourceReference.__table__,
    ResourceReferenceTombstone.__table__,
]
REQUEST = SourceReadRequest("assistant", "assistant-a", purpose="inspect")


def spec(kind, target, slot="selection"):
    return ReferenceSpec(slot, TargetKey(kind, str(target)))


def payload(refs):
    return canonical_payload_json(
        {"refs": [{"slot": r.slot_key, "kind": r.target.target_type.value, "id": r.target.target_id} for r in refs]}
    )


def extract(text):
    return tuple(spec(row["kind"], row["id"], row["slot"]) for row in json.loads(text)["refs"])


class SqlConfigurationOwner:
    async def _read(self, session, identity, *, lock):
        if not identity.allowed:
            raise ResourceReferenceInvalidError(reason="test_business_denied")
        statement = select(Assistant.tenant_id, Assistant.prompt).where(Assistant.id == "assistant-a")
        if lock:
            statement = statement.with_for_update()
        with session.no_autoflush, bypass_tenant_filter():
            row = (await session.execute(statement)).one()
        return AuthorizedSourceSnapshot(
            SourceKey(row.tenant_id, "assistant", "assistant-a", "current"),
            extract(row.prompt),
            "read-test-v1",
            payload_digest(row.prompt),
            row.prompt,
        )

    async def aresolve_source(self, session, request, identity):
        return await self._read(session, identity, lock=False)

    async def arevalidate_source(self, session, request, identity, expected):
        return await self._read(session, identity, lock=True)

    async def aresolve_transient(self, session, request, identity):
        source = await self._read(session, identity, lock=False)
        if not getattr(identity, "can_edit", True):
            raise ResourceReferenceInvalidError(reason="test_preview_not_editable")
        return AuthorizedTransientSnapshot(
            "workflow",
            request.resource_id,
            source.source_key.tenant_id,
            extract(request.payload_json),
            "read-test-v1",
            payload_digest(request.payload_json),
            request.payload_json,
        )

    async def arevalidate_transient(self, session, request, identity, expected):
        await self._read(session, identity, lock=True)
        return await self.aresolve_transient(session, request, identity)


@pytest.fixture(autouse=True)
def owner_tenant(monkeypatch):
    names = {table.name for table in TABLES}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    with scopes.tenant(101):
        yield


@pytest.fixture
async def knowledge_read_context(tmp_path):
    from bisheng.knowledge.application.reference_read_legacy_evidence import KnowledgeReferenceReadLegacyEvidence
    from bisheng.knowledge.application.source_read_target_owner import KnowledgeSourceReadTargetOwner

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'knowledge-read.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=TABLES))
    verifier = SourceReadVerifier(
        {"assistant": SqlConfigurationOwner(), "workflow_version": SqlConfigurationOwner()}, scopes.IdentityPort()
    )
    legacy = KnowledgeReferenceReadLegacyEvidence(verifier)
    ctx = SimpleNamespace(
        engine=engine,
        verifier=verifier,
        legacy=legacy,
        identity=SimpleNamespace(allowed=True, credential="original", request_nonce="request-1"),
    )
    ctx.knowledge = KnowledgeSourceReadTargetOwner(verifier, legacy_evidence=legacy)
    yield ctx
    await engine.dispose()


async def configure(ctx, refs, *, tenant_id=101, cached_owners=None, cached_spaces=None, legacy=None):
    text = payload(refs)
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add(Assistant(id="assistant-a", tenant_id=tenant_id, user_id=7, name="real", prompt=text))
            session.add_all(
                [
                    BusinessReferenceSet(
                        tenant_id=tenant_id,
                        source_type="assistant",
                        source_id="assistant-a",
                        source_version="__root__",
                        record_kind="root_guard",
                        source_revision=1,
                        extractor_version="root-guard-v1",
                        digest=reference_set_digest(()),
                        ready=False,
                        effective=False,
                    ),
                    BusinessReferenceSet(
                        tenant_id=tenant_id,
                        source_type="assistant",
                        source_id="assistant-a",
                        source_version="current",
                        source_revision=1,
                        extractor_version="read-test-v1",
                        digest=reference_set_digest(refs),
                        ready=True,
                        effective=True,
                    ),
                ]
            )
            for ref in refs:
                evidence = (legacy or {}).get(ref.target)
                session.add(
                    BusinessResourceReference(
                        tenant_id=tenant_id,
                        source_type="assistant",
                        source_id="assistant-a",
                        source_version="current",
                        slot_key=ref.slot_key,
                        target_type=ref.target.target_type.value,
                        target_id=ref.target.target_id,
                        target_tenant_id=(cached_owners or {}).get(ref.target, tenant_id),
                        target_space_id=(cached_spaces or {}).get(ref.target),
                        source_revision=1,
                        legacy_invalid_reason="target_missing" if evidence else None,
                        legacy_run_id=evidence[0] if evidence else None,
                        legacy_evidence_key=evidence[1] if evidence else None,
                    )
                )


async def insert_knowledge(ctx, *, tenant_id=101, kind=3):
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            session.add_all(
                [Knowledge(id=i, tenant_id=tenant_id, user_id=7, name=f"space-{i}", type=kind) for i in (1, 2)]
            )
            session.add(KnowledgeFile(id=8, tenant_id=tenant_id, knowledge_id=1, file_name="file"))


async def tombstone(ctx, key, stage, tenant_id=101):
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(
            ResourceReferenceTombstone(
                tenant_id=tenant_id,
                target_type=key.target_type.value,
                target_id=key.target_id,
                target_tenant_id=tenant_id,
                stage=stage,
                operation_id="original-delete",
                operation_type="force_delete",
                actor_type="user",
                actor_id="7",
            )
        )


@pytest.mark.parametrize("kind", [0, 1, 3])
@pytest.mark.parametrize("tenant_id", [101, 1])
async def test_real_space_file_group_uses_source_owner_tenant_without_polluting_session(
    knowledge_read_context, tenant_id, kind
):
    ctx = knowledge_read_context
    refs = (spec("knowledge_space", 1), spec("knowledge_file", 8))
    await configure(ctx, refs, tenant_id=tenant_id, cached_spaces={refs[1].target: "1"})
    await insert_knowledge(ctx, tenant_id=tenant_id, kind=kind)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        facts = await ctx.knowledge.ainspect_source_targets(
            session, scope, tuple(ref.target for ref in refs), identity=ctx.identity
        )
        assert all(fact.is_valid and fact.target_tenant_id == tenant_id for fact in facts)
        assert {fact.target_space_id for fact in facts} == {1}
        assert not session.sync_session.identity_map and scopes._resolve_tenant_id() == 101


@pytest.mark.parametrize(
    "ancestor,stage", [(False, "deleted"), (False, "deleting"), (True, "deleted"), (True, "deleting")]
)
async def test_original_file_and_ancestor_deletion_evidence_are_read_exactly(knowledge_read_context, ancestor, stage):
    ctx = knowledge_read_context
    ref = spec("knowledge_file", 8)
    await configure(ctx, (ref,), cached_spaces={ref.target: "1"})
    await insert_knowledge(ctx)
    if stage == "deleted":
        async with AsyncSession(ctx.engine) as session, session.begin():
            await session.execute(delete(KnowledgeFile).where(KnowledgeFile.tenant_id == 101, KnowledgeFile.id == 8))
            if ancestor:
                await session.execute(delete(Knowledge).where(Knowledge.tenant_id == 101, Knowledge.id == 1))
    await tombstone(ctx, TargetKey("knowledge_space", "1") if ancestor else ref.target, stage)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        fact = (await ctx.knowledge.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity))[0]
        assert fact.state == ("invalid_deleted" if stage == "deleted" else "deleting") and not fact.is_valid


async def test_foreign_knowledge_and_copied_scope_cannot_expand_the_target_read(knowledge_read_context):
    ctx = knowledge_read_context
    ref = spec("knowledge_space", 1)
    await configure(ctx, (ref,))
    await insert_knowledge(ctx, tenant_id=1)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.knowledge.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.knowledge.ainspect_source_targets(session, replace(scope), (ref.target,), identity=ctx.identity)


async def test_file_parent_plan_change_refuses_without_late_parent_lock(knowledge_read_context):
    ctx = knowledge_read_context
    ref = spec("knowledge_file", 8)
    await configure(ctx, (ref,), cached_spaces={ref.target: "1"})
    await insert_knowledge(ctx)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        changed = []

        def move(state):
            if (
                state.is_select
                and state.statement._for_update_arg is not None
                and not changed
                and "knowledge_file" in str(state.statement)
            ):
                changed.append(True)
                state.session.execute(
                    update(KnowledgeFile)
                    .where(KnowledgeFile.tenant_id == 101, KnowledgeFile.id == 8)
                    .values(knowledge_id=2)
                )

        event.listen(session.sync_session, "do_orm_execute", move)
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx.knowledge.ainspect_source_targets(session, scope, (ref.target,), identity=ctx.identity)
        assert changed


async def test_unsaved_preview_never_borrows_original_missing_target_evidence(knowledge_read_context):
    ctx = knowledge_read_context
    ref = spec("knowledge_space", 90)
    await configure(ctx, (ref,))
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_transient_scope(
            session, TransientTargetRequest("workflow", "workflow-a", payload((ref,))), ctx.identity
        )
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.knowledge.ainspect_transient_targets(session, scope, (ref.target,), identity=ctx.identity)


@pytest.mark.parametrize("conflicting", [False, True])
async def test_actual_legacy_reader_keeps_unknown_owner_and_rejects_conflicting_slots(
    knowledge_read_context, conflicting
):
    ctx = knowledge_read_context
    refs = (spec("knowledge_space", 90, "first"), spec("knowledge_space", 90, "second"))
    await configure(
        ctx, refs, cached_owners={refs[0].target: None}, legacy={refs[0].target: ("run-original", "target-proof")}
    )
    async with AsyncSession(ctx.engine) as session, session.begin():
        session.add(
            KnowledgeUnificationRun(
                tenant_id=101,
                run_id="run-original",
                phase="verified",
                baseline_hash="a" * 64,
                plan_hash="b" * 64,
                baseline_ref={"object_key": "101/baseline", "sha256": "a" * 64},
                plan_ref={"object_key": "101/plan", "sha256": "b" * 64},
            )
        )
        if conflicting:
            await session.execute(
                update(BusinessResourceReference)
                .where(BusinessResourceReference.tenant_id == 101, BusinessResourceReference.slot_key == "second")
                .values(legacy_evidence_key="other-proof")
            )
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        if conflicting:
            with pytest.raises(ResourceReferenceInvalidError):
                await ctx.knowledge.ainspect_source_targets(session, scope, (refs[0].target,), identity=ctx.identity)
        else:
            fact = (
                await ctx.knowledge.ainspect_source_targets(session, scope, (refs[0].target,), identity=ctx.identity)
            )[0]
            assert fact.state == "invalid_legacy" and fact.target_tenant_id is None and not fact.is_valid
