"""T373: scoped index reads are exact, projected and never write.

覆盖 AC: AC-87, AC-89
"""

from dataclasses import replace

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_source_read_scope as scopes

source_tenant = scopes.source_tenant
source_context = scopes.source_context


def source_set(tenant_id, *, version="current", root=False, empty=False):
    return BusinessReferenceSet(
        tenant_id=tenant_id,
        source_type="assistant",
        source_id="assistant-a",
        source_version="__root__" if root else version,
        record_kind="root_guard" if root else "source",
        source_revision=4 if root else 3,
        extractor_version="root-guard-v1" if root else "assistant-v1",
        digest=reference_set_digest(()) if root or empty else reference_set_digest(scopes.REFS),
        effective=not root,
        ready=True,
    )


def reference(tenant_id, *, version="current", target="11"):
    return BusinessResourceReference(
        tenant_id=tenant_id,
        source_type="assistant",
        source_id="assistant-a",
        source_version=version,
        slot_key="model_name",
        target_type="model",
        target_id=target,
        target_tenant_id=tenant_id,
        source_revision=3,
    )


@pytest.fixture
async def read_context(source_context, monkeypatch):
    from bisheng.resource_reference.domain.repositories.source_read_repository import SourceReadRepository

    ctx = source_context
    tables = [BusinessReferenceSet.__table__, BusinessResourceReference.__table__]
    monkeypatch.setattr(
        scopes.tenant_filter,
        "_tenant_aware_tables",
        scopes.tenant_filter._tenant_aware_tables | {table.name for table in tables},
    )
    async with ctx.engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    ctx.repository = SourceReadRepository(ctx.verifier)
    return ctx


async def seed(ctx, *, tenant_id=101, empty=False, missing_set=False):
    async with AsyncSession(ctx.engine) as session, session.begin():
        with bypass_tenant_filter():
            await session.execute(
                scopes.Assistant.__table__.update()
                .where(scopes.Assistant.id == "assistant-a")
                .values(tenant_id=tenant_id)
            )
            session.add(source_set(tenant_id, root=True))
            if not missing_set:
                session.add(source_set(tenant_id, empty=empty))
            if not empty:
                session.add(reference(tenant_id))
            session.add_all([source_set(202, root=True), source_set(202), reference(202, target="99")])
            session.add(reference(tenant_id, version="other", target="88"))


@pytest.mark.parametrize("tenant_id", [101, 1])
async def test_exact_scope_projects_all_rows_without_cross_tenant_identity_map(read_context, tenant_id):
    ctx = read_context
    await seed(ctx, tenant_id=tenant_id)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        value = await ctx.repository.aread_source(session, scope, ctx.identity, for_update=True)
        assert value.root.source_revision == 4 and value.source.source_revision == 3
        assert value.source.tenant_id == tenant_id
        assert [(row.tenant_id, row.target_id) for row in value.references] == [(tenant_id, "11")]
        assert not session.sync_session.identity_map
        with pytest.raises((AttributeError, TypeError)):
            value.references[0].target_id = "99"


@pytest.mark.parametrize("case", ["zero", "missing_set"])
async def test_zero_reference_sets_and_orphan_raw_rows_are_not_filtered_away(read_context, case):
    ctx = read_context
    await seed(ctx, empty=case == "zero", missing_set=case == "missing_set")
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        value = await ctx.repository.aread_source(session, scope, ctx.identity)
        if case == "zero":
            assert value.source.ready and not value.references
        else:
            assert value.source is None and len(value.references) == 1


async def test_current_reads_lock_guard_then_source_then_complete_raw_projection(read_context):
    ctx = read_context
    await seed(ctx)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        statements = []

        def observe(state):
            if state.is_select:
                statements.append(state.statement)

        event.listen(session.sync_session, "do_orm_execute", observe)
        await ctx.repository.aread_source(session, scope, ctx.identity, for_update=True)
        assert len(statements) == 3 and all(statement._for_update_arg is not None for statement in statements)
        assert "business_reference_set" in str(statements[0]) and "business_resource_reference" in str(statements[-1])


async def test_read_does_not_autoflush_pending_business_changes(read_context):
    ctx = read_context
    await seed(ctx)
    async with AsyncSession(ctx.engine) as session:
        session.add(scopes.Assistant(id="pending", tenant_id=101, name="unsaved", user_id=7))

        def forbid(*args):
            raise AssertionError("read authority flushed the caller's pending writes")

        event.listen(session.sync_session, "before_flush", forbid)
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        await ctx.repository.aread_source(session, scope, ctx.identity)
        assert len(session.new) == 1


@pytest.mark.parametrize("case", ["copy", "credential", "bypass"])
async def test_repository_validates_authority_before_any_cross_scope_sql(read_context, case):
    ctx = read_context
    await seed(ctx)
    async with AsyncSession(ctx.engine) as session:
        scope = await ctx.verifier.aissue_scope(session, scopes.REQUEST, ctx.identity)
        if case == "copy":
            scope = replace(scope)
        elif case == "credential":
            ctx.identity.credential = "another credential"
        queries = []
        event.listen(session.sync_session, "do_orm_execute", queries.append)
        with pytest.raises(ResourceReferenceInvalidError):
            if case == "bypass":
                with bypass_tenant_filter():
                    await ctx.repository.aread_source(session, scope, ctx.identity)
            else:
                await ctx.repository.aread_source(session, scope, ctx.identity)
        assert not queries
