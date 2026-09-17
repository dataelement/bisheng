"""科室库组织授权：真实事务、默认权限、手工权限与失败恢复。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text
from sqlmodel import select

from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from bisheng.knowledge.domain.repositories.implementations import (
    department_space_binding_repository_impl as repo_module,
)
from bisheng.knowledge.domain.services import knowledge_space_service as space_module
from bisheng.knowledge.domain.services.clinic_space_binding_service import update_clinic_space_binding
from bisheng.permission.domain.services import fine_grained_permission_service as fine_module
from bisheng.permission.domain.services.permission_service import PermissionService
from test.fixtures.mock_openfga import InMemoryOpenFGAClient


@pytest.fixture
async def clinic_env(async_db_engine, async_db_session, monkeypatch):
    async with async_db_engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE knowledge_space_scope ADD COLUMN portal_discovery_enabled BOOLEAN DEFAULT 0")
        )
        await conn.run_sync(DepartmentKnowledgeSpace.__table__.create)
    session = async_db_session
    space = Knowledge(id=11, name="原科室库", user_id=7, tenant_id=1, type=3)
    session.add(space)
    session.add(
        KnowledgeSpaceScope(
            space_id=11,
            tenant_id=1,
            level="team_ks",
            owner_type="user",
            owner_id=7,
            created_by=7,
        )
    )
    session.add(
        DepartmentKnowledgeSpace(
            space_id=11,
            department_id=9,
            tenant_id=1,
            created_by=7,
            sensitive_check_enabled=True,
        )
    )
    await session.commit()
    session.expunge_all()
    repository = repo_module.DepartmentSpaceBindingRepositoryImpl(session)
    monkeypatch.setattr(repo_module, "request_knowledge_intent", AsyncMock())
    fga = InMemoryOpenFGAClient()
    monkeypatch.setattr(PermissionService, "_aget_fga", AsyncMock(return_value=fga))
    monkeypatch.setattr(PermissionService, "_affected_user_ids_for_subject", AsyncMock(return_value=set()))
    failure_queue = AsyncMock()
    monkeypatch.setattr(PermissionService, "_save_failed_tuples", failure_queue)
    departments = {
        did: SimpleNamespace(id=did, path=path, org_level="office", status="active", is_deleted=0)
        for did, path in [(1, "/1/"), (9, "/1/9/"), (10, "/1/9/10/"), (12, "/2/12/"), (13, "/2/12/13/")]
    }
    monkeypatch.setattr(fine_module.DepartmentDao, "aget_by_id", AsyncMock(side_effect=lambda did: departments[did]))
    monkeypatch.setattr(
        fine_module.DepartmentDao, "aget_by_ids", AsyncMock(side_effect=lambda ids: [departments[did] for did in ids])
    )
    monkeypatch.setattr(
        fine_module.DepartmentDao, "aget_active_by_tenant", AsyncMock(return_value=list(departments.values()))
    )
    monkeypatch.setattr(
        fine_module.DepartmentDao,
        "aget_subtree_ids",
        AsyncMock(
            side_effect=lambda path: [did for did, dept in departments.items() if dept.path.startswith(path)],
        ),
    )
    bindings = []
    monkeypatch.setattr(fine_module, "_get_bindings", AsyncMock(side_effect=lambda: bindings))
    return SimpleNamespace(
        space=space,
        repository=repository,
        session=session,
        fga=fga,
        bindings=bindings,
        failure_queue=failure_queue,
    )


async def seed_permissions(env, users):
    await env.fga.write_tuples(
        writes=[
            {"object": "knowledge_space:11", "relation": "viewer", "user": f"department:{did}#member"} for did in users
        ]
        + [{"object": "knowledge_space:11", "relation": "owner", "user": "user:7"}]
    )


async def viewer_ids(env):
    return {
        int(row["user"].split(":")[1].split("#")[0])
        for row in await env.fga.read_tuples(object="knowledge_space:11", relation="viewer")
    }


@pytest.mark.parametrize(
    "target,manual,enabled,expected",
    [
        (12, None, None, {12, 13}),
        (12, 1, True, {9, 10, 12, 13}),
        (12, 10, False, {10, 12, 13}),
        (9, None, None, {9, 10}),
    ],
)
async def test_save_clinic_binding_and_default_viewers(clinic_env, target, manual, enabled, expected):
    env = clinic_env
    await seed_permissions(env, [9, 10] if target != 9 else [])
    if manual:
        env.bindings.append(
            {
                "resource_type": "knowledge_space",
                "resource_id": "11",
                "subject_type": "department",
                "subject_id": manual,
                "relation": "viewer",
                "include_children": True,
            }
        )
    env.space.name = "更新后的科室库"
    await update_clinic_space_binding(
        repository=env.repository,
        space=env.space,
        old_department_id=9,
        department_id=target,
        portal_discovery_enabled=enabled,
    )
    env.session.expunge_all()
    binding = (await env.session.exec(select(DepartmentKnowledgeSpace))).one()
    scope = (await env.session.exec(select(KnowledgeSpaceScope))).one()
    assert binding.department_id == target
    assert binding.created_by == 7 and binding.sensitive_check_enabled
    assert (scope.level, scope.owner_type, scope.owner_id) == ("team_ks", "user", 7)
    assert scope.portal_discovery_enabled == bool(enabled)
    assert (await env.session.get(Knowledge, 11)).name == "更新后的科室库"
    assert await viewer_ids(env) == expected
    env.fga.assert_tuple_exists("user:7", "owner", "knowledge_space:11")
    env.failure_queue.assert_not_awaited()


@pytest.mark.parametrize("failure", ["database", "partial_permission"])
async def test_failure_restores_binding_and_exact_previous_permissions(clinic_env, monkeypatch, failure):
    env = clinic_env
    # 新组织此前已有部分手工权限，失败不能误撤；旧组织也不应被扩权。
    await seed_permissions(env, [9, 12])
    if failure == "database":
        monkeypatch.setattr(env.session, "commit", AsyncMock(side_effect=RuntimeError("database failed")))
    else:
        original = env.fga.write_tuples
        first = True

        async def partial_write(**kwargs):
            nonlocal first
            await original(**kwargs)
            if first:
                first = False
                raise RuntimeError("partial_permission failed")

        monkeypatch.setattr(env.fga, "write_tuples", partial_write)
    env.space.name = "不应保存"
    with pytest.raises(RuntimeError, match="failed"):
        await update_clinic_space_binding(
            repository=env.repository,
            space=env.space,
            old_department_id=9,
            department_id=12,
            portal_discovery_enabled=True,
        )
    env.session.expunge_all()
    assert (await env.session.exec(select(DepartmentKnowledgeSpace))).one().department_id == 9
    assert not (await env.session.exec(select(KnowledgeSpaceScope))).one().portal_discovery_enabled
    assert (await env.session.get(Knowledge, 11)).name == "原科室库"
    assert await viewer_ids(env) == {9, 12}
    env.failure_queue.assert_not_awaited()


async def test_stale_binding_cannot_overwrite_concurrent_rebind(clinic_env):
    env = clinic_env
    with pytest.raises(Exception, match="科室绑定已变化"):
        await update_clinic_space_binding(
            repository=env.repository,
            space=env.space,
            old_department_id=8,
            department_id=12,
        )
    env.session.expunge_all()
    assert (await env.session.exec(select(DepartmentKnowledgeSpace))).one().department_id == 9
    assert await viewer_ids(env) == set()


async def test_compensation_failure_only_queues_original_permissions(clinic_env, monkeypatch):
    env = clinic_env
    await seed_permissions(env, [9, 12])
    monkeypatch.setattr(env.fga, "write_tuples", AsyncMock(side_effect=RuntimeError("FGA unavailable")))
    with pytest.raises(RuntimeError, match="FGA unavailable"):
        await update_clinic_space_binding(
            repository=env.repository,
            space=env.space,
            old_department_id=9,
            department_id=12,
        )
    env.failure_queue.assert_awaited_once()
    operations = env.failure_queue.await_args.args[0]
    assert {(op.action, op.user, op.relation) for op in operations} == {
        ("write", "department:9#member", "viewer"),
        ("delete", "department:13#member", "viewer"),
    }
    env.session.expunge_all()
    assert (await env.session.exec(select(DepartmentKnowledgeSpace))).one().department_id == 9


@pytest.mark.parametrize(
    "target,admin,grants,can_edit,allowed",
    [
        (12, True, [], True, True),
        (12, False, [12], True, True),
        (12, False, [9], True, False),
        (None, False, [], True, True),
        (12, True, [], False, False),
    ],
)
async def test_edit_service_enforces_scope_and_repairs_viewers_on_plain_save(
    clinic_env,
    monkeypatch,
    target,
    admin,
    grants,
    can_edit,
    allowed,
):
    env = clinic_env
    scope = (await env.session.exec(select(KnowledgeSpaceScope))).one()
    binding = (await env.session.exec(select(DepartmentKnowledgeSpace))).one()
    env.session.expunge_all()
    login_user = SimpleNamespace(user_id=7, user_name="管理员", tenant_id=1, is_admin=Mock(return_value=admin))
    service = space_module.KnowledgeSpaceService(request=None, login_user=login_user)
    service.department_space_binding_repo = env.repository
    service._require_permission_id = AsyncMock(
        side_effect=None if can_edit else space_module.SpacePermissionDeniedError(),
    )
    monkeypatch.setattr(space_module, "_require_not_write_frozen", AsyncMock())
    monkeypatch.setattr(space_module.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=env.space))
    monkeypatch.setattr(space_module.KnowledgeSpaceScopeDao, "aget_by_space_id", AsyncMock(return_value=scope))
    monkeypatch.setattr(space_module.DepartmentKnowledgeSpaceDao, "aget_by_space_id", AsyncMock(return_value=binding))
    monkeypatch.setattr(
        space_module.DepartmentAdminGrantDao, "aget_department_ids_by_user_id", AsyncMock(return_value=grants)
    )
    monkeypatch.setattr(space_module.KnowledgeSpaceContentStat, "enqueue_space_rename_stat_async", AsyncMock())
    if allowed:
        await service.update_knowledge_space(space_id=11, department_id=target)
        assert await viewer_ids(env) == ({12, 13} if target else {9, 10})
    else:
        with pytest.raises((space_module.SpaceCreateDepartmentDeniedError, space_module.SpacePermissionDeniedError)):
            await service.update_knowledge_space(space_id=11, department_id=target)
        assert await viewer_ids(env) == set()
    env.session.expunge_all()
    actual = (await env.session.exec(select(DepartmentKnowledgeSpace))).one().department_id
    assert actual == (target if allowed and target else 9)
