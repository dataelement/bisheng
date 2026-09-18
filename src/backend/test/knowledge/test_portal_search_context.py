"""请求阶段隔离、缺失资料与并发读取的回归。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.services.portal_search_context import PortalSearchContext
from bisheng.permission.domain.services.permission_read_context import PermissionReadContext


async def test_context_loads_only_missing_ids_and_copies_records():
    repo = SimpleNamespace(
        load=AsyncMock(side_effect=lambda kind, ids: {i: SimpleNamespace(id=i, tenant_id=7) for i in ids if i != 2})
    )
    context = PortalSearchContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo)
    first = await context.ensure("files", [1, 2])
    first[1].tenant_id = 99
    second = await context.ensure("files", [1, 2, 3])
    assert second[1].tenant_id == 7 and set(second) == {1, 3}
    assert [call.args[1] for call in repo.load.await_args_list] == [[1, 2], [3]]
    await context.start_validation_phase("response")
    await context.ensure("files", [1, 2])
    assert repo.load.await_count == 3
    with pytest.raises(ValueError):
        context.require_identity(tenant_id=8, user_id=42, routing_version=1)
    await context.close()


async def test_concurrent_tuple_waiters_share_read_and_individual_cancel_is_local():
    context = PermissionReadContext(tenant_id=7, user_id=42)
    started, release = asyncio.Event(), asyncio.Event()

    async def read():
        started.set()
        await release.wait()
        return []

    loader = AsyncMock(side_effect=read)
    first = asyncio.create_task(context.read(("tuple", "folder:1"), loader, io=True))
    await started.wait()
    second = asyncio.create_task(context.read(("tuple", "folder:1"), loader, io=True))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await second == []
    assert await context.read(("tuple", "folder:1"), loader, io=True) == []
    loader.assert_awaited_once()
    await context.close()


async def test_failed_read_is_not_cached_and_close_reaps_owned_task():
    context = PermissionReadContext(tenant_id=7, user_id=42)
    loader = AsyncMock(side_effect=[RuntimeError("unavailable"), [1]])
    with pytest.raises(RuntimeError):
        await context.read(("tuple", "file:1"), loader, io=True)
    assert await context.read(("tuple", "file:1"), loader, io=True) == [1]
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    waiter = asyncio.create_task(context.read(("tuple", "file:2"), pending, io=True))
    await started.wait()
    await context.close()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert cleaned.is_set()


@pytest.mark.parametrize("count", [1, 20, 241])
async def test_shared_candidates_do_not_reload_files_for_memory_filters(monkeypatch, count):
    from test.knowledge.test_portal_global_search_shared_retrieval import setup_search

    engine, owner, _, _ = setup_search(monkeypatch, tuple(range(10, 10 + count)))
    result = await engine.retrieve(tag_file_ids=None)
    candidates = list(owner._group_shougang_portal_chunks_by_file(result.chunks).values())
    calls_before = engine.context.repository.load.await_count
    for _ in range(2):
        visible, file_map = await engine.collect_candidates(candidates)
        assert len(visible) == len(file_map) == 1
    assert engine.context.repository.load.await_count == calls_before
    assert [call.args[0] for call in engine.context.repository.load.await_args_list] == ["documents", "entries"]
    await engine.context.close()


@pytest.mark.parametrize("change", ["delete", "inactive", "version", "generation", "membership", "move", "future_lane"])
async def test_validation_refresh_drops_changed_content_instead_of_using_old_snapshot(monkeypatch, change):
    from datetime import datetime

    from bisheng.knowledge.domain.services import portal_global_search_retrieval as module
    from test.knowledge.test_knowledge_retrieval_scope_resolver import hit
    from test.knowledge.test_portal_global_search_shared_retrieval import setup_search

    engine, owner, reader, _ = setup_search(monkeypatch)
    monkeypatch.setattr(module, "aresolve_space_shared_routing", AsyncMock(return_value=engine.snapshot))
    if change == "future_lane":
        reader.search_es.return_value = [hit(content_generation=2, membership_generation=2, text="未来正文")]
    result = await engine.retrieve(tag_file_ids=None)
    candidates = list(owner._group_shougang_portal_chunks_by_file(result.chunks).values())
    visible, file_map = await engine.collect_candidates(candidates)
    assert len(visible) == 1
    entry = owner.knowledge_file_repo.entries[0]
    document = owner.doc_repo.documents[0]
    if change == "delete":
        entry.deleted_at = datetime.now()
    elif change == "inactive":
        entry.entry_status = "invalid"
    elif change == "version":
        document.primary_version_id = 999
    elif change in {"generation", "future_lane"}:
        document.content_generation = 2
    elif change == "membership":
        entry.desired_entry_generation = 2
    else:
        entry.knowledge_id = 999
    assert await engine.recheck_content_candidates(visible, file_map) == []
    await engine.context.close()


async def test_real_permission_rules_share_ancestor_reads_and_keep_creator_semantics(monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.permission.domain.services import fine_grained_permission_service as module
    from bisheng.permission.domain.services.permission_service import PermissionService
    from test.knowledge.test_department_file_view_access import _file, _login_user

    cls = module.FineGrainedPermissionService
    monkeypatch.setattr(cls, "get_relation_models_map", AsyncMock(return_value={}))
    monkeypatch.setattr(module, "_get_bindings", AsyncMock(return_value=[]))
    monkeypatch.setattr(cls, "get_current_user_subject_strings", AsyncMock(return_value={"user:9"}))
    monkeypatch.setattr(cls, "get_binding_department_paths", AsyncMock(return_value={}))

    async def tuples(*, object):
        await asyncio.sleep(0)
        return [{"user": "user:9", "relation": "owner"}] if object == "folder:21" else []

    fga = SimpleNamespace(read_tuples=AsyncMock(side_effect=tuples))
    monkeypatch.setattr(PermissionService, "_get_fga", lambda: fga)
    creator_query = AsyncMock(side_effect=AssertionError("不应逐文件查询所属库创建者"))
    monkeypatch.setattr(PermissionService, "_get_resource_creator", creator_query)
    context = PermissionReadContext(tenant_id=1, user_id=9)
    files = [_file(file_id=i) for i in range(1, 21)]
    context.files = {file.id: file for file in files}
    context.spaces = {10: SimpleNamespace(id=10, user_id=77, type=KnowledgeTypeEnum.SPACE.value)}
    context.scopes = {10: SimpleNamespace(level="personal")}
    user = _login_user(9)
    results = await asyncio.gather(
        *[
            cls.get_effective_permission_ids_async(
                user,
                "knowledge_file",
                file.id,
                lineage=[("knowledge_file", str(file.id)), ("folder", "21"), ("knowledge_space", "10")],
                nearest_binding_wins=True,
                read_context=context,
            )
            for file in files
        ]
    )
    assert all("view_file" in permissions and "download_file" in permissions for permissions in results)
    calls = [call.kwargs["object"] for call in fga.read_tuples.await_args_list]
    assert calls.count("folder:21") == 1
    assert len(calls) == 21
    creator_query.assert_not_awaited()
    # 上传者不自动变成所属库 owner；预加载 owner 必须与原规则一致。
    assert context.creator("knowledge_file", "1") == (True, 77)
    await context.close()


async def test_repository_refresh_uses_a_new_session_and_negative_cache_is_phase_local(tmp_path):
    from contextlib import asynccontextmanager

    from sqlalchemy import event, update
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.repositories.implementations.portal_search_context_repository_impl import (
        PortalSearchContextRepositoryImpl,
    )
    from test.knowledge.test_knowledge_retrieval_scope_resolver import make_entry

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    sessions, queries = [], []

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            sessions.append(session)
            yield session

    try:
        async with engine.begin() as connection:
            await connection.run_sync(KnowledgeFile.__table__.create)
        async with session_factory() as session:
            session.add(make_entry(1, space_id=10, entry_type="share"))
            await session.commit()
        event.listen(engine.sync_engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
        repo = PortalSearchContextRepositoryImpl(42, session_factory=session_factory)
        context = PortalSearchContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo)
        rows = await context.ensure("files", [1, 2])
        original = rows[1].file_name
        async with session_factory() as session:
            await session.exec(update(KnowledgeFile).where(KnowledgeFile.id == 1).values(file_name="changed.pdf"))
            session.add(make_entry(2, space_id=10, entry_type="share"))
            await session.commit()
        cached = await context.ensure("files", [1, 2])
        assert cached[1].file_name == original and 2 not in cached
        await context.start_validation_phase("response")
        refreshed = await context.ensure("files", [1, 2])
        assert refreshed[1].file_name == "changed.pdf" and 2 in refreshed
        assert sum(query.startswith("SELECT") for query in queries) == 2
        assert len({id(session) for session in sessions}) == 4
        await context.close()
    finally:
        await engine.dispose()


async def test_department_data_shared_across_filters_and_grant_revocation_refreshes(monkeypatch):
    from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrantStatus
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileViewAccessService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services import fine_grained_permission_service as permissions
    from bisheng.permission.domain.services.permission_service import PermissionService
    from test.knowledge.test_department_file_view_access import _file, _login_user

    monkeypatch.setattr(permissions.FineGrainedPermissionService, "get_relation_models_map", AsyncMock(return_value={}))
    monkeypatch.setattr(permissions, "_get_bindings", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        permissions.FineGrainedPermissionService, "get_current_user_subject_strings", AsyncMock(return_value={"user:9"})
    )
    monkeypatch.setattr(PermissionService, "_get_fga", lambda: None)
    monkeypatch.setattr(PermissionService, "get_permission_level", AsyncMock(return_value=None))
    data = {
        "spaces": {
            sid: SimpleNamespace(id=sid, tenant_id=1, user_id=7, type=KnowledgeTypeEnum.SPACE.value) for sid in [10, 20]
        },
        "scopes": {
            sid: SimpleNamespace(space_id=sid, level="department", owner_type="department", owner_id=12, tenant_id=1)
            for sid in [10, 20]
        },
        "bindings": {sid: [SimpleNamespace(space_id=sid, department_id=12, tenant_id=1)] for sid in [10, 20]},
        "departments": {12: SimpleNamespace(id=12, status="active", is_deleted=0, path="/12/", tenant_id=1)},
        "grants": {
            101: [
                SimpleNamespace(
                    space_id=10, file_id=101, department_id=12, status=DepartmentFileViewGrantStatus.ACTIVE, tenant_id=1
                )
            ]
        },
    }
    repo = SimpleNamespace(
        load=AsyncMock(
            side_effect=lambda kind, ids: {key: value for key, value in data.get(kind, {}).items() if key in ids}
        )
    )
    ctx = PortalSearchContext(tenant_id=1, user_id=9, routing_version=1, space_ids=[10, 20], repository=repo)
    owner = object.__new__(KnowledgeSpaceService)
    owner.login_user = _login_user(9)
    owner.department_file_view_access_service = DepartmentFileViewAccessService(grant_repository=SimpleNamespace())
    files = [_file(file_id=101, space_id=10), _file(file_id=202, space_id=20)]
    for _ in range(2):
        assert await ctx.filter_visible(owner, files) == files
        assert owner._portal_file_access_decision_map[101].status == "allowed"
        assert owner._portal_file_access_decision_map[202].status == "approval_required"
    kinds = [call.args[0] for call in repo.load.await_args_list]
    assert len(kinds) == len(set(kinds))
    assert kinds.count("departments") == 1
    data["grants"] = {}
    await ctx.start_validation_phase("response")
    await ctx.filter_visible(owner, files)
    assert owner._portal_file_access_decision_map[101].status == "approval_required"
    assert repo.load.await_count == len(kinds) * 2
    await ctx.close()


async def test_phase_refresh_invalidates_cached_admin_role():
    from bisheng.database.constants import AdminRole
    from test.knowledge.test_department_file_view_access import _login_user

    admins = [SimpleNamespace(user_id=9)]
    repo = SimpleNamespace(load=AsyncMock(side_effect=lambda kind, ids: {AdminRole: list(admins)}))
    context = PortalSearchContext(tenant_id=1, user_id=9, routing_version=1, space_ids=[10], repository=repo)
    user = _login_user(9, admin=True)
    assert user.is_admin()
    assert (await context.phase_user(user)).is_admin()
    admins.clear()
    await context.start_validation_phase("response")
    assert not (await context.phase_user(user)).is_admin()
    assert user.is_admin()
    await context.close()


async def test_permission_io_is_bounded_and_empty_results_are_separate_by_type():
    context = PermissionReadContext(tenant_id=7, user_id=42)
    active = peak = 0

    async def read():
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0)
            return []
        finally:
            active -= 1

    await asyncio.gather(*[context.read(("tuples", f"folder:{i}"), read, io=True) for i in range(50)])
    assert 1 < peak <= 16
    assert context.stats["loads"] == 50
    await context.read(("tuples", "knowledge_file:1"), read, io=True)
    assert context.stats["loads"] == 51
    await context.close()


async def test_phase_switch_cancels_old_io_without_contaminating_new_phase():
    ctx = PortalSearchContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=SimpleNamespace())
    started = asyncio.Event()

    async def late_read():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return ["旧阶段结果"]

    old = ctx.permissions
    waiter = asyncio.create_task(old.read(("tuples", "folder:1"), late_read))
    await started.wait()
    await ctx.start_validation_phase("response")
    assert await waiter == ["旧阶段结果"]
    assert old.cache == {}
    assert await ctx.permissions.read(("tuples", "folder:1"), AsyncMock(return_value=[])) == []
    ctx.bind_filters("a")
    with pytest.raises(ValueError, match="筛选范围"):
        ctx.bind_filters("b")
    await ctx.close()


async def test_display_enrichment_reuses_loaded_versions_and_source_organization():
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

    repo = SimpleNamespace(load=AsyncMock(return_value={}))
    ctx = PortalSearchContext(tenant_id=7, user_id=42, routing_version=1, space_ids=[10], repository=repo)
    ctx.seed("versions", {5: SimpleNamespace(id=5, knowledge_file_id=101, is_primary=True)})
    ctx.seed("spaces", {10: SimpleNamespace(id=10, name="部门库", type=KnowledgeTypeEnum.SPACE.value)})
    ctx.seed("bindings", {10: [SimpleNamespace(department_id=20)]})
    ctx.seed("departments", {20: SimpleNamespace(name="技术部门", short_name="技术")})
    assert (await ctx.rows("primary_versions", [101]))[0].id == 5
    assert (await ctx.source_metadata([10]))[10][:3] == ("部门库", "技术部门", "技术")
    repo.load.assert_not_awaited()
    await ctx.close()


@pytest.mark.parametrize("sort", ["relevance", "updated_at_desc"])
async def test_search_without_rerank_has_only_response_refresh(monkeypatch, sort):
    from bisheng.knowledge.domain.services import portal_global_search_retrieval as module
    from test.knowledge.test_portal_global_search_shared_retrieval import setup_search

    engine, owner, reader, runtime = setup_search(monkeypatch)
    engine.req.retrieval_profile = "portal_global_shared"
    engine.req.sort = sort
    engine.req.rerank_model_id = None
    monkeypatch.setattr(module, "get_async_retrieval_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "SharedSpaceStorageReader", lambda **kw: reader)
    route = AsyncMock(return_value=engine.snapshot)
    monkeypatch.setattr(module, "aresolve_space_shared_routing", route)
    owner._search_portal_metadata_files = AsyncMock(return_value=[])
    owner._map_shougang_portal_candidate_items = AsyncMock(return_value=[])
    owner._rerank_shougang_portal_file_candidates = AsyncMock(side_effect=lambda **kw: kw["candidates"])
    await owner._semantic_search_shougang_portal_files(req=engine.req, spaces=engine.spaces, tag_file_ids=None)
    assert route.await_count == 2  # 初次路由及响应复核，无多余重排前刷新。
    assert len(owner._map_shougang_portal_candidate_items.call_args.kwargs["candidates"]) == 1


async def test_repository_keeps_membership_type_user_and_primary_version_constraints(tmp_path):
    from contextlib import asynccontextmanager

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.models.space_channel_member import BusinessTypeEnum, SpaceChannelMember, UserRoleEnum
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.repositories.implementations.portal_search_context_repository_impl import (
        PortalSearchContextRepositoryImpl,
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'members.db'}")

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    try:
        async with engine.begin() as connection:
            await connection.run_sync(SpaceChannelMember.__table__.create)
            await connection.run_sync(KnowledgeDocumentVersion.__table__.create)
        async with sessions() as session:
            session.add_all(
                [
                    SpaceChannelMember(
                        id=i, business_id="10", business_type=kind, user_id=uid, user_role=UserRoleEnum.MEMBER
                    )
                    for i, kind, uid in [
                        (1, BusinessTypeEnum.SPACE, 42),
                        (2, BusinessTypeEnum.CHANNEL, 42),
                        (3, BusinessTypeEnum.SPACE, 99),
                    ]
                ]
            )
            session.add_all(
                [
                    KnowledgeDocumentVersion(
                        id=i, document_id=1, knowledge_file_id=100 + i, version_no=i, is_primary=i == 2
                    )
                    for i in [1, 2]
                ]
            )
            await session.commit()
        statements = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
        repo = PortalSearchContextRepositoryImpl(42, session_factory=sessions)
        assert [row.id for row in (await repo.load("members", [10]))[10]] == [1]
        assert set(await repo.load("primary_versions", [101, 102])) == {102}
        assert await repo.load("versions", list(range(1000, 1501))) == {}
        assert len(statements) == 4  # 大于 500 的补缺集合分两批，不按空间扇出。
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("unavailable", [False, True])
async def test_ordinary_member_refresh_preserves_child_binding_override(monkeypatch, bound, unavailable):
    from bisheng.common.models.space_channel_member import UserRoleEnum
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
    from bisheng.permission.domain.services import fine_grained_permission_service as module
    from bisheng.permission.domain.services.permission_service import PermissionService
    from test.knowledge.test_department_file_view_access import _file, _login_user

    cls = module.FineGrainedPermissionService
    monkeypatch.setattr(
        cls, "get_relation_models_map", AsyncMock(return_value={"limited": {"permissions": ["view_file"]}})
    )
    monkeypatch.setattr(
        module,
        "_get_bindings",
        AsyncMock(
            return_value=[
                {
                    "resource_type": "knowledge_file",
                    "resource_id": "101",
                    "subject_type": "user",
                    "subject_id": 9,
                    "relation": "viewer",
                    "model_id": "limited",
                }
            ]
            if bound
            else []
        ),
    )
    monkeypatch.setattr(cls, "get_current_user_subject_strings", AsyncMock(return_value={"user:9"}))
    monkeypatch.setattr(
        cls, "get_current_user_department_paths", AsyncMock(side_effect=AssertionError("应复用部门路径"))
    )
    fga = SimpleNamespace(
        read_tuples=AsyncMock(
            side_effect=lambda **kw: (
                [{"user": "user:9", "relation": "viewer"}] if bound and kw["object"] == "knowledge_file:101" else []
            )
        )
    )
    if unavailable:
        fga.read_tuples.side_effect = module.FGAClientError("unavailable")
    monkeypatch.setattr(PermissionService, "_get_fga", lambda: fga)
    monkeypatch.setattr(PermissionService, "get_permission_level", AsyncMock(return_value=None))
    member = SimpleNamespace(is_active=True, user_role=UserRoleEnum.MEMBER)
    data = {
        "spaces": {10: SimpleNamespace(id=10, tenant_id=1, type=KnowledgeTypeEnum.SPACE.value, user_id=77)},
        "scopes": {10: SimpleNamespace(level="personal")},
        "members": {10: [member]},
    }
    ctx = PortalSearchContext(
        tenant_id=1,
        user_id=9,
        routing_version=1,
        space_ids=[10],
        repository=SimpleNamespace(load=AsyncMock(side_effect=lambda kind, ids: data.get(kind, {}))),
    )
    owner = object.__new__(KnowledgeSpaceService)
    owner.login_user = _login_user(9)
    owner.department_file_view_access_service = None
    file = _file(file_id=101)
    assert await ctx.filter_visible(owner, [file]) == [file]
    assert owner._portal_file_download_map[101] is (not bound)
    member.is_active = False
    await ctx.start_validation_phase("response")
    assert await ctx.filter_visible(owner, [file]) == ([file] if bound else [])
    await ctx.close()


@pytest.mark.parametrize("sort", ["relevance", "updated_at_asc", "updated_at_desc"])
@pytest.mark.parametrize("filters", ["none", "combined", "whitespace"])
async def test_memory_filters_match_existing_sql_and_stable_sort(monkeypatch, tmp_path, sort, filters):
    from contextlib import asynccontextmanager
    from datetime import datetime

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.knowledge.domain.models import knowledge_file as file_module
    from bisheng.knowledge.domain.services.knowledge_space_service import PortalFileCandidate
    from test.knowledge.test_knowledge_retrieval_scope_resolver import make_entry
    from test.knowledge.test_portal_global_search_shared_retrieval import setup_search

    entries = [make_entry(i, space_id=10, entry_type="share") for i in range(1, 66)]
    retriever, owner, _, _ = setup_search(monkeypatch, entries=entries)
    for i, entry in enumerate(entries):
        entry.update_time = datetime(2026, 1, 1 + i % 3)
        entry.file_name = f"资料{i}.PDF" if i % 2 else f"资料{i}.docx"
        entry.file_encoding = "SG-NEW-PP-001" if i % 3 else ""
        entry.file_subcategory_code = "A1" if i % 4 else None
    entries[-1].status = 1
    entries[-2].deleted_at = datetime(2026, 1, 1)
    entries[-3].knowledge_id = 99
    entries[-4].file_type = 0
    tags = None
    req = retriever.req
    req.sort = sort
    if filters == "combined":
        req.file_ext, req.document_type, req.file_subcategory_code, req.business_domain_code = (
            " .PDF ",
            "new",
            "a1",
            "pp",
        )
        tags = list(range(1, 45))
    elif filters == "whitespace":
        req.file_ext, req.file_subcategory_code = " ", " "
    retriever.tag_file_ids = set(tags) if tags is not None else None
    retriever.context.seed("files", {entry.id: entry for entry in entries})
    candidates = [
        PortalFileCandidate(file_id=row.id, knowledge_id=row.knowledge_id, canonical_document_id=row.id)
        for row in reversed(entries)
    ]
    database = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'filters.db'}")

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(database, expire_on_commit=False) as session:
            yield session

    try:
        async with database.begin() as connection:
            await connection.run_sync(file_module.KnowledgeFile.__table__.create)
        async with sessions() as session:
            session.add_all(entries)
            await session.commit()
        monkeypatch.setattr(file_module, "get_async_db_session", sessions)
        old, _ = await owner._collect_visible_shougang_portal_semantic_candidates(
            ranked_candidates=candidates,
            spaces=retriever.spaces,
            tag_file_ids=tags,
            file_ext=req.file_ext,
            document_type=req.document_type,
            file_subcategory_code=req.file_subcategory_code,
            business_domain_code=req.business_domain_code,
            sort=sort,
        )
        new, _ = await retriever.collect_candidates(candidates)
        assert [row.file_id for row in new] == [row.file_id for row in old]
        assert len(new) <= 50
        assert len(new) > 0
        retriever.context.repository.load.assert_not_awaited()
    finally:
        await retriever.context.close()
        await database.dispose()
