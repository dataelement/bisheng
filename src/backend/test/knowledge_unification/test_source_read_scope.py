"""T371: actual Owner calls, private scope issuance and request isolation.

覆盖 AC: AC-79, AC-83, AC-87, AC-89
SQLite exercises the protocol, not MySQL/DM8 lock scheduling.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import tenant_filter
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.database.models.assistant import Assistant
from bisheng.resource_reference.application.contracts import ReferenceSpec, SourceKey, TargetKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    AuthorizedTransientSnapshot,
    ReadIdentityFacts,
    ReferenceTargetReadFact,
    SourceReadRequest,
    TransientTargetRequest,
    canonical_payload_json,
    payload_digest,
)
from test.knowledge_unification.test_ref_repo import tenant

REFS = (ReferenceSpec("model_name", TargetKey("model", "11")),)
REQUEST = SourceReadRequest("assistant", "assistant-a")


def snapshot(*, tenant_id=101, model="11"):
    payload = canonical_payload_json({"model_name": model})
    return AuthorizedSourceSnapshot(
        SourceKey(tenant_id, "assistant", "assistant-a", "current"),
        (ReferenceSpec("model_name", TargetKey("model", model)),),
        "assistant-v1",
        payload_digest(payload),
        payload,
    )


class IdentityPort:
    async def acapture(self, identity):
        return ReadIdentityFacts(_resolve_tenant_id(), (identity.credential, identity.request_nonce))


class SqlSourceOwner:
    """Business Owner double; observations come from real business SQL rows."""

    def __init__(self):
        self.calls = []

    async def _read(self, session, identity, *, lock):
        self.calls.append("root" if lock else "candidate")
        if not identity.allowed:
            raise ResourceReferenceInvalidError(reason="test_source_not_authorized")
        statement = select(Assistant.id, Assistant.tenant_id, Assistant.model_name).where(Assistant.id == "assistant-a")
        if lock:
            statement = statement.with_for_update()
        with session.no_autoflush, bypass_tenant_filter():
            row = (await session.exec(statement)).one()
        return snapshot(tenant_id=row.tenant_id, model=row.model_name)

    async def aresolve_source(self, session, request, identity):
        return await self._read(session, identity, lock=False)

    async def arevalidate_source(self, session, request, identity, expected):
        return await self._read(session, identity, lock=True)

    async def aresolve_transient(self, session, request, identity):
        self.calls.append("preview")
        if not identity.allowed:
            raise ResourceReferenceInvalidError(reason="test_preview_not_editable")
        return AuthorizedTransientSnapshot(
            "workflow",
            request.resource_id,
            101,
            REFS,
            "workflow-v1",
            payload_digest(request.payload_json),
            request.payload_json,
        )

    async def arevalidate_transient(self, session, request, identity, expected):
        self.calls.append("preview_root")
        return expected


class ReadTargetOwner:
    def __init__(self, calls):
        self.calls = calls

    async def ainspect_source_targets(self, session, scope, target_keys, *, identity):
        self.calls.append("targets")
        return tuple(ReferenceTargetReadFact(key, "valid", True, 101) for key in target_keys)

    async def ainspect_transient_targets(self, session, scope, target_keys, *, identity):
        return await self.ainspect_source_targets(session, scope, target_keys, identity=identity)


@pytest.fixture(autouse=True)
def source_tenant(monkeypatch):
    names = {Assistant.__tablename__}
    monkeypatch.setattr(tenant_filter, "_force_import_all_models", lambda: None)
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    tenant_filter.register_tenant_filter_events()
    with tenant(101):
        yield


@pytest.fixture
async def source_context(tmp_path):
    from bisheng.resource_reference.application.source_verification import SourceReadVerifier

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=[Assistant.__table__]))
    async with AsyncSession(engine) as session, session.begin():
        session.add(Assistant(id="assistant-a", tenant_id=101, user_id=7, name="real", model_name="11"))
    owner = SqlSourceOwner()
    verifier = SourceReadVerifier({"assistant": owner, "workflow_version": owner}, IdentityPort())
    context = SimpleNamespace(
        engine=engine,
        owner=owner,
        verifier=verifier,
        identity=SimpleNamespace(credential="PAT:7:OWNED", request_nonce="request-1", allowed=True),
    )
    yield context
    await engine.dispose()


async def test_private_issuance_calls_actual_owner_and_root_requires_actual_target_plan(source_context):
    ctx = source_context
    ctx.verifier._install_target_owners({"model": ReadTargetOwner(ctx.owner.calls)})
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        assert (await ctx.verifier.aget_source_snapshot(session, scope, ctx.identity)) == snapshot()
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.verifier.arevalidate_scope(session, scope, ctx.identity)
        assert ctx.owner.calls == ["candidate"]
        await ctx.verifier._ainspect_targets(session, scope, ctx.identity)
        await ctx.verifier.arevalidate_scope(session, scope, ctx.identity)
        assert ctx.owner.calls == ["candidate", "targets", "root"]


@pytest.mark.parametrize(
    "case", ["copy", "equality_copy", "purpose", "identity", "credential", "tenant", "bypass", "verifier"]
)
async def test_scope_cannot_be_copied_or_rebound(source_context, case):
    from bisheng.resource_reference.application.source_verification import SourceReadVerifier

    ctx = source_context
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        identity, verifier = ctx.identity, ctx.verifier
        if case == "copy":
            scope = replace(scope)
        elif case == "equality_copy":
            original = scope

            class EqualScope(type(original)):
                def __hash__(self):
                    return hash(original)

                def __eq__(self, other):
                    return other is original or other is self

            scope = EqualScope(original.snapshot, original.purpose, original._nonce)
        elif case == "purpose":
            scope = replace(scope, purpose="inspect")
        elif case == "identity":
            identity = SimpleNamespace(**vars(identity))
        elif case == "credential":
            identity.credential = "PAT:7:ALL"
        elif case == "verifier":
            verifier = SourceReadVerifier({"assistant": ctx.owner}, IdentityPort())
        with pytest.raises(ResourceReferenceInvalidError):
            if case == "tenant":
                with tenant(202):
                    await verifier.aget_source_snapshot(session, scope, identity)
            elif case == "bypass":
                with bypass_tenant_filter():
                    await verifier.aget_source_snapshot(session, scope, identity)
            else:
                await verifier.aget_source_snapshot(session, scope, identity)


@pytest.mark.parametrize("ending", ["commit", "rollback", "other_session", "savepoint"])
async def test_scope_is_bound_to_the_active_transaction(source_context, ending):
    ctx = source_context
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            if ending == "other_session":
                async with AsyncSession(ctx.engine) as other, other.begin():
                    await ctx.verifier.aget_source_snapshot(other, scope, ctx.identity)
            elif ending == "savepoint":
                async with session.begin_nested():
                    await ctx.verifier.aget_source_snapshot(session, scope, ctx.identity)
            else:
                await getattr(session, ending)()
                async with session.begin():
                    await ctx.verifier.aget_source_snapshot(session, scope, ctx.identity)


async def test_denial_and_unregistered_source_fail_without_a_scope(source_context):
    ctx = source_context
    async with AsyncSession(ctx.engine) as session:
        ctx.identity.allowed = False
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        with pytest.raises(ReferenceCoverageNotReadyError):
            await ctx.verifier.aissue_scope(session, SourceReadRequest("knowledge", "1"), ctx.identity)


async def test_revalidation_detects_changed_business_configuration(source_context):
    ctx = source_context
    ctx.verifier._install_target_owners({"model": ReadTargetOwner(ctx.owner.calls)})
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, REQUEST, ctx.identity)
        await ctx.verifier._ainspect_targets(session, scope, ctx.identity)
        await session.execute(Assistant.__table__.update().where(Assistant.id == "assistant-a").values(model_name="22"))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await ctx.verifier.arevalidate_scope(session, scope, ctx.identity)


async def test_transient_scope_has_no_saved_source_and_uses_its_real_owner(source_context):
    ctx = source_context
    ctx.verifier._install_target_owners({"model": ReadTargetOwner(ctx.owner.calls)})
    request = TransientTargetRequest("workflow", "workflow-a", canonical_payload_json({"nodes": []}))
    async with AsyncSession(ctx.engine) as session, session.begin():
        scope = await ctx.verifier.aissue_transient_scope(session, request, ctx.identity)
        with pytest.raises(ResourceReferenceInvalidError):
            await ctx.verifier.aget_source_snapshot(session, scope, ctx.identity)
        assert (await ctx.verifier.aget_transient_snapshot(session, scope, ctx.identity)).owner_tenant_id == 101
        await ctx.verifier._ainspect_targets(session, scope, ctx.identity)
        await ctx.verifier.arevalidate_transient_scope(session, scope, ctx.identity)
        assert ctx.owner.calls == ["preview", "targets", "preview_root"]
