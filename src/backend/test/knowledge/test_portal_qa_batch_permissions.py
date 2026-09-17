from types import SimpleNamespace
from unittest.mock import AsyncMock


async def test_ordinary_candidates_share_context_and_child_deny_overrides_membership(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    service = module.KnowledgeSpaceService(None, SimpleNamespace(user_id=7, tenant_id=1))
    for method, result in [
        ("_get_current_user_subject_strings", {"user:7"}),
        ("_get_relation_bindings", []),
        ("_get_binding_department_paths", {}),
        ("_get_relation_models_map", {}),
    ]:
        monkeypatch.setattr(service, method, AsyncMock(return_value=result))
    members = AsyncMock(
        return_value=[SimpleNamespace(business_id=10, is_active=True, user_role=module.UserRoleEnum.MEMBER)]
    )
    monkeypatch.setattr(module.SpaceChannelMemberDao, "async_get_user_space_members", members)
    calls = []

    async def permission(*args, **kw):
        calls.append(kw)
        return set(), args[2] == 2  # 文件 2 的自定义模型明确未授予查看。

    monkeypatch.setattr(module.FineGrainedPermissionService, "get_effective_permission_ids_async", permission)
    files = [SimpleNamespace(id=i, knowledge_id=10, file_type=1, file_level_path="/20") for i in (1, 2, 3)]
    assert await service.batch_qa_file_view_permissions(files[:2]) == {1: True, 2: False}
    assert await service.batch_qa_file_view_permissions(files[2:]) == {3: True}
    members.assert_awaited_once()
    service._get_relation_models_map.assert_awaited_once()
    assert all(call["tuple_cache"] is calls[0]["tuple_cache"] for call in calls)
    assert all(call["nearest_binding_wins"] and not call["use_permission_level_fallback"] for call in calls)


async def test_qa_space_repository_keeps_rebuilding_and_excludes_retired(async_db_session):
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum, KnowledgeState
    from sqlalchemy import text
    from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl

    for i, state in [(41, KnowledgeState.PUBLISHED), (42, KnowledgeState.REBUILDING), (43, KnowledgeState.DELETING)]:
        async_db_session.add(
            Knowledge(id=i, name=f"space-{i}", tenant_id=1, type=KnowledgeTypeEnum.SPACE.value, state=state.value)
        )
        # 项目共享 SQLite fixture 的空间分类表使用精简列，显式插入其公共字段。
        await async_db_session.execute(
            text(
                "INSERT INTO knowledge_space_scope (space_id, tenant_id, level, owner_type, owner_id, created_by) "
                "VALUES (:id, 1, 'public', 'user', 1, 1)"
            ),
            {"id": i},
        )
    await async_db_session.commit()
    repo = KnowledgeRepositoryImpl(async_db_session)
    rows = await repo.find_qa_spaces_by_ids([41, 42, 43, 99])
    assert {(row.id, level) for row, level in rows} == {(41, "public"), (42, "public")}


async def test_real_permission_evaluator_reads_shared_ancestors_once(monkeypatch):
    from bisheng.knowledge.domain.services import knowledge_space_service as module

    service = module.KnowledgeSpaceService(None, SimpleNamespace(user_id=7, tenant_id=1))
    for method, result in [
        ("_get_current_user_subject_strings", {"user:7"}),
        ("_get_relation_bindings", []),
        ("_get_binding_department_paths", {}),
        ("_get_relation_models_map", {}),
    ]:
        monkeypatch.setattr(service, method, AsyncMock(return_value=result))
    monkeypatch.setattr(module.SpaceChannelMemberDao, "async_get_user_space_members", AsyncMock(return_value=[]))
    fga = SimpleNamespace(read_tuples=AsyncMock(return_value=[]))
    monkeypatch.setattr(module.PermissionService, "_get_fga", lambda: fga)
    implicit = AsyncMock(return_value=None)
    monkeypatch.setattr(module.PermissionService, "get_implicit_permission_level", implicit)
    evaluator = module.FineGrainedPermissionService
    monkeypatch.setattr(evaluator, "_tuple_resource_types", AsyncMock(side_effect=lambda kind, oid: [kind]))
    monkeypatch.setattr(evaluator, "_public_knowledge_space_viewer_permission_ids", AsyncMock(return_value=set()))
    files = [SimpleNamespace(id=i, knowledge_id=10, file_type=1, file_level_path="/99") for i in range(1, 21)]
    assert not any((await service.batch_qa_file_view_permissions(files)).values())
    objects = [call.kwargs["object"] for call in fga.read_tuples.await_args_list]
    assert len(objects) == 22  # 20 个唯一文件 + 1 个共同目录 + 1 个来源库。
    assert objects.count("folder:99") == objects.count("knowledge_space:10") == 1
    assert implicit.await_count == 20  # 业务隐式权限仍逐候选判断，不能声称所有 DB/FGA 调用已变为常数。
