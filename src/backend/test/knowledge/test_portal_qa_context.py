"""QA request-local loading, pure filtering and fresh final authorization."""

from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.services.portal_qa_context import PortalQaContext
from bisheng.knowledge.domain.services.portal_qa_retrieval_service import PortalEntryAuthorizer
from test.knowledge.test_knowledge_retrieval_scope_resolver import (
    hit,
    make_document,
    make_entry,
    make_resolver,
    make_scope,
)


class ContextRepository:
    def __init__(self, data):
        self.data, self.calls = data, []

    async def load(self, kind, ids):
        self.calls.append((kind, tuple(ids)))
        return deepcopy({key: value for key, value in self.data.get(kind, {}).items() if key in ids})


def setup_context(level="public", *, phase="candidates"):
    entry = make_entry(1, space_id=10, entry_type="manager")
    entry.status, entry.file_type = 2, 1
    data = {
        "documents": {91: make_document()},
        "entries": {91: [entry]},
        "spaces": {10: SimpleNamespace(id=10, tenant_id=7, type=KnowledgeTypeEnum.SPACE.value, user_id=8)},
        "scopes": {10: SimpleNamespace(tenant_id=7, level=level, owner_type="department", owner_id=20)},
    }
    repo = ContextRepository(data)
    context = PortalQaContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo, phase=phase)
    return context, repo, entry


async def test_mapping_multiple_pages_loads_document_and_all_entries_once():
    context, repo, entry = setup_context()
    resolver, _, _, _ = make_resolver()
    owner = SimpleNamespace(login_user=SimpleNamespace(user_id=42, tenant_id=7))
    authorizer = PortalEntryAuthorizer(owner, context=context)
    try:
        for chunk in range(20):
            mapped = await resolver.map_and_authorize_hits(
                make_scope(space_ids=(10,)),
                [hit(chunk_index=chunk)],
                entry_batch_checker=authorizer,
                context=context,
                strict_explicit=True,
                skip_unready=True,
            )
            assert [row.entry_file_id for row in mapped] == [entry.id]
        assert Counter(kind for kind, _ in repo.calls) == {"documents": 1, "entries": 1, "spaces": 1, "scopes": 1}
        await context.ensure("documents", [999])
        calls = list(repo.calls)
        await context.ensure("documents", [91, 999])
        assert repo.calls == calls
        repo.load = AsyncMock(side_effect=AssertionError("filter must not load"))
        assert context.evaluate_entries([entry]) == {1: True}
    finally:
        await context.close()


@pytest.mark.parametrize("change", ["source_deleted", "delete", "version", "generation"])
async def test_final_context_does_not_reuse_candidate_facts(change):
    context, repo, entry = setup_context()
    resolver, _, _, _ = make_resolver()
    owner = SimpleNamespace(login_user=SimpleNamespace(user_id=42, tenant_id=7))

    async def mapped(ctx):
        return await resolver.map_and_authorize_hits(
            make_scope(space_ids=(10,)),
            [hit()],
            context=ctx,
            entry_batch_checker=PortalEntryAuthorizer(owner, context=ctx),
            skip_unready=True,
        )

    assert await mapped(context)
    if change == "delete":
        repo.data["entries"] = {}
    elif change == "version":
        repo.data["documents"][91].primary_version_id = 502
    elif change == "generation":
        other = make_entry(2, space_id=99, entry_type="share", desired_entry=2)
        repo.data["entries"][91].append(other)
    else:
        repo.data["spaces"] = {}
    final = PortalQaContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo, phase="final")
    try:
        assert not await mapped(final)
        assert await mapped(context)  # Candidate snapshot stays isolated.
    finally:
        await final.close()
        await context.close()


async def test_context_rejects_changed_scope_and_failed_load_is_not_cached():
    context, repo, _ = setup_context()
    resolver, _, _, _ = make_resolver()
    checker = AsyncMock(return_value={1: True})
    await resolver.map_and_authorize_hits(
        make_scope(space_ids=(10,)), [hit()], context=context, entry_batch_checker=checker
    )
    with pytest.raises(ValueError, match="scope|范围"):
        await resolver.map_and_authorize_hits(
            make_scope(space_ids=(20,)), [hit()], context=context, entry_batch_checker=checker
        )
    repo.load = AsyncMock(side_effect=RuntimeError("unavailable"))
    with pytest.raises(RuntimeError, match="unavailable"):
        await context.ensure("documents", [999])
    assert 999 not in context.loaded["documents"]
    await context.close()


@pytest.mark.parametrize("change", ["revoke", "private"])
async def test_real_permission_evaluator_reuses_facts_but_final_reloads(monkeypatch, change):
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services import fine_grained_permission_service as module
    from bisheng.permission.domain.services.permission_service import PermissionService

    context, repo, entry = setup_context("public" if change == "private" else "personal")
    evaluator = module.FineGrainedPermissionService
    monkeypatch.setattr(evaluator, "get_relation_models_map", AsyncMock(return_value={}))
    monkeypatch.setattr(module, "_get_bindings", AsyncMock(return_value=[]))
    monkeypatch.setattr(evaluator, "get_current_user_subject_strings", AsyncMock(return_value={"user:42"}))
    monkeypatch.setattr(
        PermissionService, "_get_resource_creator", AsyncMock(side_effect=AssertionError("file reread"))
    )
    monkeypatch.setattr(
        evaluator,
        "_public_knowledge_space_viewer_permission_ids",
        AsyncMock(side_effect=AssertionError("space reread")),
    )
    allowed = True
    fga = SimpleNamespace(
        read_tuples=AsyncMock(side_effect=lambda **kw: [{"user": "user:42", "relation": "viewer"}] if allowed else [])
    )
    monkeypatch.setattr(PermissionService, "_get_fga", lambda: fga)
    owner = KnowledgeSpaceService(None, SimpleNamespace(user_id=42, tenant_id=7))
    owner.department_file_view_access_service = None
    authorizer = PortalEntryAuthorizer(owner, context=context)
    files = [make_entry(i, space_id=10, entry_type="manager", file_level_path="/99") for i in range(1, 21)]
    for file in files:
        file.status, file.file_type = 2, 1
    assert all((await authorizer(files)).values())
    calls = fga.read_tuples.await_count
    assert calls == (0 if change == "private" else 20)  # Nearest file binding stops ancestor reads.
    await authorizer(files)
    assert fga.read_tuples.await_count == calls
    allowed = False
    repo.data["scopes"][10].level = "personal"
    final = PortalQaContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo, phase="final")
    try:
        assert not any((await PortalEntryAuthorizer(owner, context=final)(files)).values())
        objects = [call.kwargs["object"] for call in fga.read_tuples.await_args_list[calls:]]
        assert len(objects) == 22  # 20 files, one shared folder and one shared space.
        assert final.permissions.stats["fga.tuples.calls"] == 22
        PermissionService._get_resource_creator.assert_not_awaited()
        evaluator._public_knowledge_space_viewer_permission_ids.assert_not_awaited()
        repo.load = AsyncMock(side_effect=AssertionError("pure filter performed I/O"))
        assert not any(final.evaluate_entries(files).values())
    finally:
        await final.close()
        await context.close()


async def test_close_cancels_load_and_prevents_late_cache_fill():
    import asyncio

    context, repo, _ = setup_context()
    started = asyncio.Event()

    async def load(kind, ids):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {1: "late result"}

    repo.load = load
    task = asyncio.create_task(context.ensure("documents", [1]))
    await started.wait()
    await context.close()
    with pytest.raises(RuntimeError, match="关闭"):
        await task
    assert not context.loads and not context.data and not context.decisions


async def test_sql_queries_are_per_unique_facts_and_final_session_is_fresh(tmp_path):
    from contextlib import asynccontextmanager
    from sqlalchemy import DefaultClause, MetaData, event, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
    from bisheng.knowledge.domain.repositories.implementations.portal_search_context_repository_impl import (
        PortalSearchContextRepositoryImpl,
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'qa-context.db'}")

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    _, _, entry = setup_context()
    contexts = []
    try:
        async with engine.begin() as connection:
            metadata = MetaData()
            for model in [Knowledge, KnowledgeFile, KnowledgeDocument, KnowledgeSpaceScope]:
                table = model.__table__.to_metadata(metadata)
                if model is KnowledgeSpaceScope:
                    # SQLite cannot execute the existing MySQL ON UPDATE default.
                    table.c.update_time.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
            await connection.run_sync(metadata.create_all)
        async with sessions() as session:
            session.add_all(
                [
                    Knowledge(id=10, name="public", tenant_id=7, type=KnowledgeTypeEnum.SPACE.value),
                    KnowledgeSpaceScope(
                        space_id=10, tenant_id=7, level="public", owner_type="user", owner_id=8, created_by=8
                    ),
                    entry,
                    make_document(),
                ]
            )
            await session.commit()
        statements = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

        def context(phase):
            result = PortalQaContext(
                tenant_id=7,
                user_id=42,
                routing_version=1,
                space_ids=[10],
                phase=phase,
                repository=PortalSearchContextRepositoryImpl(42, session_factory=sessions),
            )
            contexts.append(result)
            return result

        candidate = context("candidates")
        resolver, _, _, _ = make_resolver()
        owner = SimpleNamespace(login_user=SimpleNamespace(user_id=42, tenant_id=7))

        async def retrieve(ctx, chunk=0):
            return await resolver.map_and_authorize_hits(
                make_scope(space_ids=(10,)),
                [hit(chunk_index=chunk)],
                context=ctx,
                entry_batch_checker=PortalEntryAuthorizer(owner, context=ctx),
                skip_unready=True,
            )

        for chunk in range(20):
            assert await retrieve(candidate, chunk)
        assert len(statements) == 4  # Document, all entries, space and scope, once each.
        assert sum(candidate.repository.query_counts.values()) == 4
        async with sessions() as session:
            row = await session.get(KnowledgeDocument, 91)
            row.primary_version_id = 502
            await session.commit()
        final = context("final")
        assert not await retrieve(final)
        assert sum(final.repository.query_counts.values()) == 2  # Reject before any permission loading.
        assert await retrieve(candidate)
    finally:
        for ctx in contexts:
            await ctx.close()
        await engine.dispose()


async def test_concurrent_authorization_is_deduplicated_and_failure_never_caches_allow(monkeypatch):
    import asyncio
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

    context, repo, entry = setup_context("personal")
    owner = KnowledgeSpaceService(None, SimpleNamespace(user_id=42, tenant_id=7))
    permissions = AsyncMock(return_value=({"view_file"}, False))
    monkeypatch.setattr(FineGrainedPermissionService, "get_effective_permission_ids_async", permissions)
    authorizer = PortalEntryAuthorizer(owner, context=context)
    try:
        assert await asyncio.gather(authorizer([entry]), authorizer([entry])) == [{1: True}, {1: True}]
        permissions.assert_awaited_once()
        other = PortalQaContext(tenant_id=7, user_id=43, routing_version=1, space_ids=[10], repository=repo)
        other_owner = KnowledgeSpaceService(None, SimpleNamespace(user_id=43, tenant_id=7))
        permissions.side_effect = RuntimeError("permission unavailable")
        try:
            with pytest.raises(RuntimeError, match="permission unavailable"):
                await PortalEntryAuthorizer(other_owner, context=other)([entry])
            assert not other.decisions
            with pytest.raises(ValueError, match="身份"):
                await PortalEntryAuthorizer(owner, context=other)([entry])
        finally:
            await other.close()
    finally:
        await context.close()


@pytest.mark.parametrize("grant_department", [None, 20, 99])
async def test_ordinary_and_department_permissions_are_not_computed_twice(monkeypatch, grant_department):
    from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileViewAccessService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
    from bisheng.common.models.space_channel_member import UserRoleEnum

    context, repo, ordinary = setup_context("personal")
    department = make_entry(2, space_id=20, entry_type="manager")
    department.status, department.file_type = 2, 1
    repo.data["spaces"][20] = SimpleNamespace(id=20, tenant_id=7, type=KnowledgeTypeEnum.SPACE.value, user_id=8)
    repo.data["scopes"][20] = SimpleNamespace(tenant_id=7, level="department", owner_type="department", owner_id=20)
    repo.data["bindings"] = {20: [SimpleNamespace(tenant_id=7, department_id=20)]}
    repo.data["departments"] = {20: SimpleNamespace(tenant_id=7, id=20, path="/20")}
    repo.data["members"] = {10: [SimpleNamespace(is_active=True, user_role=UserRoleEnum.MEMBER)]}
    context.space_ids = frozenset([10, 20])
    owner = KnowledgeSpaceService(None, SimpleNamespace(user_id=42, tenant_id=7))
    owner.department_file_view_access_service = DepartmentFileViewAccessService(
        grant_repository=SimpleNamespace(),
        persist_stale_grant_revalidation=True,
    )
    invalidate = AsyncMock()
    monkeypatch.setattr(owner.department_file_view_access_service, "_invalidate_stale_grants", invalidate)
    if grant_department is not None:
        repo.data["grants"] = {
            2: [
                SimpleNamespace(
                    tenant_id=7,
                    status="active",
                    space_id=20,
                    file_id=2,
                    department_id=grant_department,
                )
            ]
        }
    ordinary_permissions = AsyncMock(return_value=(set(), False))
    dept_permissions = AsyncMock(return_value={"2": set()})
    monkeypatch.setattr(FineGrainedPermissionService, "get_effective_permission_ids_async", ordinary_permissions)
    monkeypatch.setattr(FineGrainedPermissionService, "get_effective_permission_ids_batch_async", dept_permissions)
    authorizer = PortalEntryAuthorizer(owner, context=context)
    expected = {1: True, 2: grant_department == 20}
    assert await authorizer([ordinary, department]) == expected
    assert await authorizer([ordinary, department]) == expected
    ordinary_permissions.assert_awaited_once()
    assert ordinary_permissions.call_args.kwargs["use_permission_level_fallback"] is False
    assert dept_permissions.call_args.args[2] == [2]
    dept_permissions.assert_awaited_once()
    assert invalidate.await_count == (1 if grant_department == 99 else 0)
    if grant_department == 99:
        assert invalidate.call_args.kwargs["resources"] == {(20, 2): 20}
    await context.close()
