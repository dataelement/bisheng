"""昆联账号必须在所属租户成员查询中可见, 成功回执也能补齐。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianIdentityUnavailableError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.department import Department, UserDepartment, UserDepartmentDao
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.sso_sync.domain.models.kunlian import KunlianIdentityBinding
from bisheng.user.domain.models.user import User
from test.sso import test_kunlian_directory as directory
from test.sso import test_kunlian_tenant_onboarding as fixtures

onboarding = fixtures.onboarding
onboarding_store = fixtures.onboarding_store


@pytest.mark.parametrize("recovery", ["regular_scan", "projected_receipt"])
async def test_existing_successful_user_recovers_visible_membership_once(onboarding, recovery):
    s = onboarding
    await directory.publish(
        s.repo,
        tenants=[directory.tenant(), directory.tenant("external-b")],
        members=[directory.member(), directory.member("m2", "s2", "external-b")],
    )
    await fixtures.run_round(s.service)
    async with s.sessions() as session:
        bindings = (await session.exec(select(KunlianIdentityBinding))).all()
        tenants = (await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).all()
        # 模拟线上旧版本: 用户与投影已成功, 但没有部门关联。
        await session.exec(delete(UserDepartment))
        await session.commit()
    for _ in range(2):
        if recovery == "regular_scan":
            await fixtures.run_round(s.service)
        else:
            for binding in bindings:
                await s.projection.project_identity(binding.identity_key)
    with tenant_execution_scope(1):
        for tenant in tenants:
            rows, total = await UserDepartmentDao.aget_members(tenant.root_dept_id)
            assert total == 1, "已有账号必须通过原部门成员查询可见"
            binding = next(b for b in bindings if b.local_user_id == rows[0].user_id)
            mapping = await s.repo.get_tenant_binding("fixture", binding.external_tenant_id)
            assert mapping.local_tenant_id == tenant.id
            assert rows[0].is_primary == 1 and rows[0].source == "kunlian"
    async with s.sessions() as session:
        assert len((await session.exec(select(UserDepartment))).all()) == 2
        assert len((await session.exec(select(KunlianIdentityBinding))).all()) == 2


async def test_new_user_is_visible_after_first_round(onboarding):
    s = onboarding
    await directory.publish(s.repo)
    await fixtures.run_round(s.service)
    async with s.sessions() as session:
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        row = (await session.exec(select(UserDepartment))).one_or_none()
        assert row is not None, "首次同步必须创建部门成员关系"
        dept = await session.get(Department, row.department_id)
        assert row.user_id == binding.local_user_id
        mapping = await s.repo.get_tenant_binding("fixture", binding.external_tenant_id)
        assert dept.mounted_tenant_id == mapping.local_tenant_id


@pytest.mark.parametrize(
    "case", ["wrong_mount", "wrong_membership", "foreign_primary", "inactive_tenant", "local_identity"]
)
async def test_invalid_target_is_rejected_without_department_mutation(onboarding, case):
    from bisheng.department.application.external_membership import ensure_external_department_membership

    s = onboarding
    await directory.publish(s.repo)
    await fixtures.run_round(s.service)
    async with s.sessions() as session:
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        tenant = (await session.exec(select(Tenant).where(Tenant.parent_tenant_id == 1))).one()
        uid, tid, root_id = binding.local_user_id, tenant.id, tenant.root_dept_id
        await session.exec(delete(UserDepartment))
        if case == "wrong_mount":
            dept = await session.get(Department, root_id)
            dept.mounted_tenant_id = 999
            session.add(dept)
        elif case == "wrong_membership":
            member = (await session.exec(select(UserTenant).where(UserTenant.user_id == uid))).one()
            member.tenant_id = 1
            session.add(member)
        elif case == "foreign_primary":
            session.add(UserDepartment(user_id=uid, department_id=1, is_primary=1, source="local"))
        elif case == "inactive_tenant":
            tenant.status = "disabled"
            session.add(tenant)
        else:
            user = await session.get(User, uid)
            user.source = "local"
            session.add(user)
        await session.commit()
    with pytest.raises((KunlianBindingConflictError, KunlianIdentityUnavailableError)):
        await ensure_external_department_membership(uid, tid, root_id)
    async with s.sessions() as session:
        rows = (await session.exec(select(UserDepartment))).all()
        assert [(r.user_id, r.department_id, r.source) for r in rows] == (
            [(uid, 1, "local")] if case == "foreign_primary" else []
        )


async def test_existing_manual_primary_department_is_preserved(onboarding):
    s = onboarding
    await directory.publish(s.repo)
    await fixtures.run_round(s.service)
    async with s.sessions() as session:
        binding = (await session.exec(select(KunlianIdentityBinding))).one()
        root = (await session.exec(select(Department).where(Department.is_tenant_root == 1))).one()
        child = Department(dept_id="manual-child", name="人工部门", tenant_id=1, parent_id=root.id)
        session.add(child)
        await session.flush()
        child.path = root.path + str(child.id) + "/"
        session.add(child)
        await session.exec(delete(UserDepartment))
        session.add(UserDepartment(user_id=binding.local_user_id, department_id=child.id, source="local"))
        await session.commit()
        child_id = child.id
    await fixtures.run_round(s.service)
    await s.projection.project_identity(binding.identity_key)
    async with s.sessions() as session:
        row = (await session.exec(select(UserDepartment))).one()
        assert (row.department_id, row.is_primary, row.source) == (child_id, 1, "local")


async def test_permission_prepare_failure_does_not_commit_department_member(onboarding, monkeypatch):
    from bisheng.department.domain.services import department_service as module

    s = onboarding
    await directory.publish(s.repo)
    await s.service.recover("fixture", stage="tenants")
    original = module._prepare_department_projection
    monkeypatch.setattr(
        module, "_prepare_department_projection", AsyncMock(side_effect=KunlianDependencyUnavailableError())
    )
    assert (await s.service.recover("fixture", stage="projection"))["failed"] == 1
    async with s.sessions() as session:
        assert not (await session.exec(select(UserDepartment))).all()
    monkeypatch.setattr(module, "_prepare_department_projection", original)
    assert (await s.service.recover("fixture", stage="projection"))["succeeded"] == 1
    async with s.sessions() as session:
        assert len((await session.exec(select(UserDepartment))).all()) == 1


async def test_department_projection_failure_is_resumed_without_duplicate_members(onboarding, monkeypatch):
    from bisheng.department.domain.services import department_projection_scope as scope_module
    from bisheng.department.domain.services import department_service as module

    s = onboarding
    scope = scope_module.SqlDepartmentProjectionScope()
    monkeypatch.setattr(scope_module, "get_async_db_session", s.sessions)
    monkeypatch.setattr(module, "_uses_f048_department_projection", lambda: True)
    plan = None

    class Runtime:
        execute = AsyncMock(side_effect=KunlianDependencyUnavailableError())
        abandon = AsyncMock()

        async def bind(self, session, prepared):
            await scope.bind(session, prepared.plan, prepared.operation_id)

        async def reconcile_operation(self, operation_id):
            await scope.finalize(plan, operation_id)
            return SimpleNamespace(target_version=plan.target_version)

    runtime = Runtime()

    async def prepare(**kwargs):
        nonlocal plan
        dept = kwargs["department"]
        plan = SimpleNamespace(
            tenant_id=dept.tenant_id,
            scope_type="department",
            scope_key=str(dept.id),
            expected_version=dept.permission_projection_version,
            target_version=dept.permission_projection_version + 1,
        )
        return SimpleNamespace(runtime=runtime, prepared=SimpleNamespace(plan=plan, operation_id=123))

    monkeypatch.setattr(module, "_prepare_department_projection", prepare)
    monkeypatch.setattr(scope_module, "get_department_projection_runtime", AsyncMock(return_value=runtime))
    await directory.publish(s.repo)
    await s.service.recover("fixture", stage="tenants")
    assert (await s.service.recover("fixture", stage="projection"))["failed"] == 1
    async with s.sessions() as session:
        assert len((await session.exec(select(UserDepartment))).all()) == 1
        root = await session.get(Department, int(plan.scope_key))
        assert root.permission_projection_state == "PROJECTING"
        assert (await session.exec(select(KunlianIdentityBinding))).one().projection_status == "FAILED"
    assert (await s.service.recover("fixture", stage="projection"))["succeeded"] == 1
    async with s.sessions() as session:
        root = await session.get(Department, int(plan.scope_key))
        assert root.permission_projection_state == "CURRENT" and root.permission_projection_version == 1
        assert len((await session.exec(select(UserDepartment))).all()) == 1
    assert runtime.execute.await_count == 1
    runtime.abandon.assert_not_awaited()
