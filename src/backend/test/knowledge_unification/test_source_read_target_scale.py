"""T957: actual source authority and scalar target reads have bounded work.

覆盖 AC: AC-37, AC-43, AC-68, AC-83, AC-85, AC-89, AC-91, AC-92
Only business authorization is a SQL-backed test port. SourceVerifier,
SourceRepository and both target repositories execute their real native SQL.
"""

from math import ceil

import pytest
from sqlalchemy import event, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.assistant import Assistant
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.application.source_contracts import (
    AuthorizedSourceSnapshot,
    ReadIdentityFacts,
    TransientTargetRequest,
    payload_digest,
)
from bisheng.resource_reference.application.source_verification import SourceReadVerifier
from test.knowledge_unification import test_knowledge_read_owner as knowledge
from test.knowledge_unification import test_model_read_owner as models

owner_tenant = knowledge.owner_tenant
knowledge_read_context = knowledge.knowledge_read_context
model_read_context = models.model_read_context


class SyncIdentity(knowledge.scopes.IdentityPort):
    def capture(self, identity):
        return ReadIdentityFacts(knowledge.scopes._resolve_tenant_id(), (identity.credential, identity.request_nonce))


class SyncConfigurationOwner(knowledge.SqlConfigurationOwner):
    """The existing SQL business test port with its synchronous entry points."""

    @staticmethod
    def _sync_read(session, identity, *, lock):
        if not identity.allowed:
            raise knowledge.ResourceReferenceInvalidError(reason="test_business_denied")
        query = select(Assistant.tenant_id, Assistant.prompt).where(Assistant.id == "assistant-a")
        with session.no_autoflush, bypass_tenant_filter():
            row = session.execute(query.with_for_update() if lock else query).one()
        return AuthorizedSourceSnapshot(
            SourceKey(row.tenant_id, "assistant", "assistant-a", "current"),
            knowledge.extract(row.prompt),
            "read-test-v1",
            payload_digest(row.prompt),
            row.prompt,
        )

    def resolve_source(self, session, request, identity):
        return self._sync_read(session, identity, lock=False)

    def revalidate_source(self, session, request, identity, expected):
        return self._sync_read(session, identity, lock=True)


async def prepare(ctx, kind, count, *, transient=False):
    keys = tuple(TargetKey(kind, str(i)) for i in range(1000, 1000 + count))
    refs = tuple(knowledge.spec(kind, key.target_id, f"slot-{key.target_id}-{j}") for key in keys for j in range(3))
    await knowledge.configure(
        ctx,
        () if transient else refs,
        cached_spaces=dict.fromkeys(keys, "1") if kind == "knowledge_file" else {},
    )
    async with AsyncSession(ctx.engine) as session, session.begin():
        if kind == "model":
            session.add_all(
                LLMModel(
                    id=int(key.target_id),
                    tenant_id=101,
                    server_id=1,
                    name=key.target_id,
                    model_name=key.target_id,
                    model_type="llm",
                )
                for key in keys
            )
        else:
            session.add(Knowledge(id=1, tenant_id=101, user_id=7, name="space", type=3))
            session.add_all(
                KnowledgeFile(id=int(key.target_id), tenant_id=101, knowledge_id=1, file_name=key.target_id)
                for key in keys
            )
    if not transient:
        await knowledge.tombstone(ctx, keys[0], "deleting")
        if kind == "knowledge_file":
            await knowledge.tombstone(ctx, TargetKey("knowledge_space", "1"), "deleting")
    return keys, refs


def record_candidates(monkeypatch, kind):
    if kind == "model":
        from bisheng.llm.domain.repositories import source_read_target_repository as module

        name = "_original"
    else:
        from bisheng.knowledge.domain.repositories import source_read_target_repository as module

        name = "original_for"
    original, sizes = getattr(module, name), []

    def observed(rows, key):
        sizes.append(len(rows))
        return original(rows, key)

    monkeypatch.setattr(module, name, observed)
    return sizes


def observe_sql(engine):
    statements = []

    def record(conn, cursor, sql, parameters, context, many):
        statements.append((sql, len(parameters)))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    return statements, record


def assert_budget(statements, *, kind, count):
    assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql, _ in statements)
    tombstones = [(sql, n) for sql, n in statements if "resource_reference_tombstone" in sql]
    tuples = count + (kind == "knowledge_file")
    assert len(tombstones) == ceil(tuples / 200), (len(tombstones), count)
    assert max(n for _, n in statements) <= 250
    assert all("ORDER BY" in sql for sql, _ in tombstones)


@pytest.mark.parametrize("kind,synchronous", [("knowledge_file", False), ("model", False), ("model", True)])
@pytest.mark.parametrize("count", [401, 1001])
async def test_saved_real_source_targets_use_once_grouped_evidence_and_bounded_scalar_reads(
    model_read_context, monkeypatch, kind, synchronous, count
):
    ctx = model_read_context
    keys, _ = await prepare(ctx, kind, count)
    candidates = record_candidates(monkeypatch, kind)
    repository = ctx.model.repository if kind == "model" else ctx.knowledge.repository
    async with AsyncSession(ctx.engine) as session:
        if synchronous:
            from bisheng.llm.domain.repositories.source_read_target_repository import ModelSourceReadTargetRepository

            verifier = SourceReadVerifier({"assistant": SyncConfigurationOwner()}, SyncIdentity())
            repository = ModelSourceReadTargetRepository(verifier)

            def read(native):
                scope = verifier.issue_scope(native, knowledge.REQUEST, ctx.identity)
                return repository.lock_targets(native, scope, keys, identity=ctx.identity)

            statements, record = observe_sql(ctx.engine)
            try:
                plan = await session.run_sync(read)
            finally:
                event.remove(ctx.engine.sync_engine, "before_cursor_execute", record)
        else:
            scope = await ctx.verifier.aissue_scope(session, knowledge.REQUEST, ctx.identity)
            statements, record = observe_sql(ctx.engine)
            try:
                plan = await repository.alock_targets(session, scope, keys, identity=ctx.identity)
            finally:
                event.remove(ctx.engine.sync_engine, "before_cursor_execute", record)
        rows = plan.observations if kind == "model" else plan
        assert len(rows) == count and all(row.exists for row in rows)
        by_key = {row.key: row for row in rows}
        assert by_key[keys[0]].deletion.stage == "deleting"
        if kind == "knowledge_file":
            assert all(row.ancestor_deletion.stage == "deleting" for row in rows)
        assert not session.sync_session.identity_map and not session.new and not session.dirty
        assert knowledge.scopes._resolve_tenant_id() == 101
    assert sum(candidates) == count * 3, (sum(candidates), count * 3)
    assert_budget(statements, kind=kind, count=count)


@pytest.mark.parametrize("kind", ["knowledge_file", "model"])
async def test_transient_10001_real_targets_keep_original_authority_with_bounded_queries(model_read_context, kind):
    ctx, count = model_read_context, 10001
    keys, refs = await prepare(ctx, kind, count, transient=True)
    repository = ctx.model.repository if kind == "model" else ctx.knowledge.repository
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_transient_scope(
            session, TransientTargetRequest("workflow", "workflow-a", knowledge.payload(refs)), ctx.identity
        )
        statements, record = observe_sql(ctx.engine)
        try:
            plan = await repository.alock_targets(session, scope, keys, identity=ctx.identity, transient=True)
        finally:
            event.remove(ctx.engine.sync_engine, "before_cursor_execute", record)
        rows = plan.observations if kind == "model" else plan
        assert len(rows) == count and all(row.exists and row.original is None for row in rows)
        assert not session.sync_session.identity_map and not session.new and not session.dirty
        assert knowledge.scopes._resolve_tenant_id() == 101
    assert_budget(statements, kind=kind, count=count)
