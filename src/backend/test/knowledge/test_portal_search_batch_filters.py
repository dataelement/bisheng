"""验证批量过滤的查询次数、范围隔离和并发任务回收。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagLink
from bisheng.knowledge.domain.contracts.errors import SharedStorageContractError
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLink
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFileSearchReq
from bisheng.knowledge.domain.services.department_file_view_access_service import DepartmentFileViewAccessService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services import fine_grained_permission_service as permission_module
from test.knowledge.test_department_file_view_access import _file, _login_user, _resource
from test.knowledge.test_knowledge_retrieval_scope_resolver import (
    hit,
    make_document,
    make_entry,
    make_resolver,
    make_scope,
)


@pytest.mark.parametrize("changed_identity", [{"tenant_id": 8}, {"user_id": "99"}, {"routing_version": 2}])
async def test_mapping_batch_rejects_mixed_request_identity_before_io(changed_identity):
    resolver, _, _, _ = make_resolver(
        entries=[make_entry(1, space_id=20, entry_type="manager")], documents=[make_document()]
    )
    resolver.document_repository.find_by_ids = AsyncMock()
    scope = make_scope()
    with pytest.raises(SharedStorageContractError):
        await resolver.map_and_authorize_hit_batches([(scope, [hit()]), (replace(scope, **changed_identity), [hit()])])
    resolver.document_repository.find_by_ids.assert_not_awaited()


@pytest.mark.parametrize("space_count", [1, 20, 241])
async def test_tag_filter_uses_three_queries_for_whole_scope(space_count):
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            for model in (Tag, TagLink, KnowledgeTagLibraryLink):
                await conn.run_sync(model.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    KnowledgeTagLibraryLink(knowledge_id=i, tag_library_id=500, tenant_id=1)
                    for i in range(1, space_count + 1)
                ]
            )
            session.add_all(
                [
                    Tag(id=1, name="安全", business_type="knowledge_space", business_id="1"),
                    Tag(id=2, name="安全", business_type="tag_library", business_id="500"),
                    Tag(id=3, name="安全", business_type="tag_library", business_id="999"),
                    Tag(id=4, name="安全", business_type="knowledge_space", business_id="999"),
                    Tag(id=5, name="无关", business_type="tag_library", business_id="500"),
                ]
            )
            session.add_all(
                [
                    TagLink(tag_id=tag_id, resource_id=file_id, resource_type=resource_type)
                    for tag_id, file_id, resource_type in [
                        (1, "101", ResourceTypeEnum.SPACE_FILE.value),
                        (2, "101", ResourceTypeEnum.SPACE_FILE.value),
                        (2, "102", ResourceTypeEnum.SPACE_FILE.value),
                        (2, "bad-id", ResourceTypeEnum.SPACE_FILE.value),
                        (2, "103", -1),
                        (3, "104", ResourceTypeEnum.SPACE_FILE.value),
                        (4, "105", ResourceTypeEnum.SPACE_FILE.value),
                        (5, "106", ResourceTypeEnum.SPACE_FILE.value),
                    ]
                ]
            )
            await session.commit()
            statements = []
            event.listen(engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
            repo = KnowledgeFileRepositoryImpl(session)
            assert await repo.find_portal_tag_file_ids(list(range(1, space_count + 1)), " 安全 ") == [101, 102]
            assert len(statements) == 3
            statements.clear()
            assert await repo.find_portal_tag_file_ids([1], "不存在") == []
            assert len(statements) == 2
            statements.clear()
            assert await repo.find_portal_tag_file_ids([], "安全") == []
            assert statements == []
    finally:
        await engine.dispose()


async def test_portal_shared_profile_uses_batch_tag_repository():
    service = object.__new__(KnowledgeSpaceService)
    spaces = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    service._get_shougang_portal_request_spaces = AsyncMock(return_value=spaces)
    service.knowledge_file_repo = SimpleNamespace(find_portal_tag_file_ids=AsyncMock(return_value=[101]))
    service._get_shougang_portal_tag_file_ids = AsyncMock(side_effect=AssertionError("不能逐库解析标签"))
    service._semantic_search_shougang_portal_files = AsyncMock(return_value={"data": []})
    req = ShougangPortalFileSearchReq(
        q="安全", tag="安全", retrieval_profile="portal_global_shared", discovery_scope="portal_configured"
    )
    assert await service._search_shougang_portal_files_impl(req) == {"data": []}
    service.knowledge_file_repo.find_portal_tag_file_ids.assert_awaited_once_with([1, 2], "安全")
    assert service._semantic_search_shougang_portal_files.await_args.kwargs["tag_file_ids"] == [101]


@pytest.mark.parametrize("batch_failure", [False, True])
async def test_department_access_batches_spaces_after_explicit_grant_crop(batch_failure):
    service = object.__new__(KnowledgeSpaceService)
    service.login_user = _login_user(9)
    service._get_shougang_portal_public_space_ids = AsyncMock(return_value={30})
    service._get_valid_department_space_ids = AsyncMock(return_value={10, 20})
    service._portal_grant_parent_space_ids = {20}
    service._portal_explicit_file_ids = {202}
    service._portal_file_access_decision_map = {}
    service._portal_file_download_map = {}
    service._public_space_viewer_permission_ids = AsyncMock(return_value={"view_file"})
    decision = lambda status: SimpleNamespace(status=status, can_download=False)
    service.department_file_view_access_service = SimpleNamespace(
        evaluate_files=AsyncMock(
            return_value={101: decision("allowed"), 202: decision("approval_required")},
        )
    )
    files = [_file(file_id=fid, space_id=sid) for fid, sid in [(101, 10), (202, 20), (203, 20), (301, 30)]]
    if batch_failure:
        service.department_file_view_access_service.evaluate_files.side_effect = [
            RuntimeError("批量失败"),
            {101: decision("allowed")},
            RuntimeError("库 20 不可用"),
        ]
    visible = await service._filter_shougang_portal_visible_files(files)
    assert [file.id for file in visible] == ([101, 301] if batch_failure else [101, 202, 301])
    calls = service.department_file_view_access_service.evaluate_files.await_args_list
    assert [call.kwargs["files"] for call in calls] == (
        [files[:2], files[:1], files[1:2]] if batch_failure else [files[:2]]
    )


async def test_permission_and_database_io_overlap_but_session_queries_remain_serial():
    permission_started, approval_started = asyncio.Event(), asyncio.Event()
    events = []
    file = _file()

    async def permissions(*args):
        permission_started.set()
        await approval_started.wait()
        return {11: {"view_file", "download_file"}}

    async def approvers(*args):
        approval_started.set()
        await permission_started.wait()
        events.append("approvers_done")
        return {}

    async def grants(**kwargs):
        assert events == ["approvers_done"]
        events.append("grants_done")
        return {}

    service = DepartmentFileViewAccessService(
        resource_loader=AsyncMock(return_value={11: _resource(file)}),
        permission_resolver=permissions,
        approver_resolver=approvers,
        grant_repository=SimpleNamespace(list_active_by_user_and_files=grants),
    )
    result = await asyncio.wait_for(service.evaluate_files(login_user=_login_user(9), files=[file]), 1)
    assert result[11].status == "allowed"
    assert result[11].can_download
    assert events == ["approvers_done", "grants_done"]


@pytest.mark.parametrize("cancel", [False, True])
async def test_access_failure_or_cancellation_reaps_sibling(cancel):
    started, cleaned = asyncio.Event(), asyncio.Event()
    file = _file()

    async def permissions(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def approvers(*args):
        await started.wait()
        if not cancel:
            raise RuntimeError("审批资料不可用")
        await asyncio.Event().wait()

    service = DepartmentFileViewAccessService(
        resource_loader=AsyncMock(return_value={11: _resource(file)}),
        permission_resolver=permissions,
        approver_resolver=approvers,
        grant_repository=SimpleNamespace(list_active_by_user_and_files=AsyncMock()),
    )
    task = asyncio.create_task(service.evaluate_files(login_user=_login_user(9), files=[file]))
    await asyncio.wait_for(started.wait(), 1)
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await asyncio.wait_for(task, 1)
    assert cleaned.is_set()
    service.grant_repository.list_active_by_user_and_files.assert_not_awaited()


async def test_complete_permissions_computed_once_per_file_with_shared_context(monkeypatch):
    cls = permission_module.FineGrainedPermissionService
    models, bindings, subjects, paths = {}, [], {"user:9"}, {}
    for method, value in [
        ("get_relation_models_map", models),
        ("get_current_user_subject_strings", subjects),
        ("get_binding_department_paths", paths),
    ]:
        monkeypatch.setattr(cls, method, AsyncMock(return_value=value))
    monkeypatch.setattr(permission_module, "_get_bindings", AsyncMock(return_value=bindings))
    current = peak = 0
    calls = []

    async def effective(user, object_type, object_id, **kwargs):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        try:
            assert kwargs["models"] is models and kwargs["bindings"] is bindings
            assert kwargs["user_subject_strings"] is subjects and kwargs["binding_department_paths"] is paths
            assert kwargs["lineage"] == [
                ("knowledge_file", object_id),
                ("folder", "21"),
                ("folder", "20"),
                ("knowledge_space", "10"),
            ]
            calls.append(object_id)
            await asyncio.sleep(0)
            return {"view_file", "download_file", "edit_file"}
        finally:
            current -= 1

    monkeypatch.setattr(cls, "get_effective_permission_ids_async", effective)
    files = [_file(file_id=i) for i in range(1, 42)]
    service = DepartmentFileViewAccessService(grant_repository=SimpleNamespace())
    result = await service._resolve_permission_ids(_login_user(9), files + files[:1])
    assert result == {file.id: {"view_file", "download_file"} for file in files}
    assert sorted(calls, key=int) == [str(file.id) for file in files]
    assert 1 < peak <= 16
    for method in [
        cls.get_relation_models_map,
        cls.get_current_user_subject_strings,
        cls.get_binding_department_paths,
        permission_module._get_bindings,
    ]:
        method.assert_awaited_once()


@pytest.mark.parametrize("failure_stage", ["context", "object"])
async def test_permission_batch_failure_reaps_other_requests(monkeypatch, failure_stage):
    cls = permission_module.FineGrainedPermissionService
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def pending(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async def fail(*args, **kwargs):
        await started.wait()
        raise RuntimeError("权限资料不可用")

    monkeypatch.setattr(
        cls, "get_relation_models_map", pending if failure_stage == "context" else AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        permission_module, "_get_bindings", fail if failure_stage == "context" else AsyncMock(return_value=[])
    )
    monkeypatch.setattr(cls, "get_current_user_subject_strings", AsyncMock(return_value=set()))
    monkeypatch.setattr(cls, "get_binding_department_paths", AsyncMock(return_value={}))

    async def effective(user, kind, object_id, **kwargs):
        return await (pending() if object_id == "1" else fail())

    monkeypatch.setattr(cls, "get_effective_permission_ids_async", effective)
    with pytest.raises(RuntimeError, match="权限资料不可用"):
        await asyncio.wait_for(
            cls.get_effective_permission_ids_batch_async(_login_user(9), "knowledge_file", [1, 2]), 1
        )
    assert cleaned.is_set()
