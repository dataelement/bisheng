"""Binding writes use H and permanently retire loss of scope support."""

import pytest
from sqlmodel import select

from bisheng.common.errcode.role import RolePolicyUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.audit_log import AuditLog
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.repositories.role_definition_repository import RoleDefinitionRepository
from bisheng.user.application.policy_bindings import grant_policy_bindings, retire_invalid_policy_bindings
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.role.test_effective_roles import policy_db as policy_db


@pytest.fixture
async def binding_db(policy_db, monkeypatch):
    from bisheng.role.domain.repositories import role_definition_repository

    await policy_db.create(AuditLog)
    monkeypatch.setattr(role_definition_repository, "get_async_db_session", policy_db.sessions)
    return policy_db


async def test_binding_uses_subject_home_not_management_target(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            session.add(Role(id=9, role_name="new global", role_type="global", tenant_id=1))
            await session.commit()
    with management_scope(home=1, target=3):
        await grant_policy_bindings(77, 2, {9})
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            binding = (await session.exec(select(UserRole).where(UserRole.role_id == 9))).one()
            assert binding.tenant_id == 2
            audit = (await session.exec(select(AuditLog))).one()
            assert audit.audit_metadata["added"] == [9]
            assert audit.audit_metadata["reason"] == "EXPLICIT_BINDING_CHANGE"


async def test_foreign_role_cannot_be_granted_even_with_secondary_membership(binding_db):
    with management_scope(home=1, target=3), pytest.raises(RolePolicyUnavailableError):
        await grant_policy_bindings(77, 2, {4})


async def test_scope_loss_deletes_binding_and_expansion_does_not_revive(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            session.add(
                Department(id=31, dept_id="a-other", name="other", tenant_id=1, parent_id=20, path="/10/20/31/")
            )
            await session.commit()
            role = await session.get(Role, 3)
    role = await RoleDefinitionRepository.update(role, {"department_id": 31})
    await RoleDefinitionRepository.update(role, {"department_id": None})
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 3))).all()
            assert (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))).all()


async def test_last_membership_loss_stays_deleted_on_return(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            await session.delete(await session.get(UserDepartment, 1))
            await retire_invalid_policy_bindings([77], session=session, derive_primary_home=True)
            await session.commit()
        async with binding_db.sessions() as session:
            session.add(UserDepartment(id=10, user_id=77, department_id=30, is_primary=1))
            await session.commit()
        async with binding_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 3))).all()
            assert (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))).all()


async def test_secondary_last_support_loss_keeps_unscoped_home_bindings(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            session.add(
                Department(id=31, dept_id="same-home", name="secondary", tenant_id=1, parent_id=20, path="/10/20/31/")
            )
            session.add(UserDepartment(id=11, user_id=77, department_id=31, is_primary=0))
            session.add(Role(id=9, role_name="secondary scoped", role_type="tenant", tenant_id=2, department_id=31))
            session.add(UserRole(id=11, user_id=77, role_id=9, tenant_id=2))
            await session.commit()
        async with binding_db.sessions() as session:
            await session.delete(await session.get(UserDepartment, 11))
            await retire_invalid_policy_bindings([77], session=session, derive_primary_home=True)
            await session.commit()
        async with binding_db.sessions() as session:
            roles = {
                row.role_id
                for row in (
                    await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.tenant_id == 2))
                ).all()
            }
            assert roles == {2, 3}


async def test_global_role_delete_removes_all_home_copies(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            session.add(Role(id=9, role_name="deletable global", role_type="global", tenant_id=1))
            session.add_all(
                [
                    UserRole(id=11, user_id=77, role_id=9, tenant_id=2),
                    UserRole(id=12, user_id=78, role_id=9, tenant_id=1),
                ]
            )
            await session.commit()
            role = await session.get(Role, 9)
    await RoleDefinitionRepository.delete(role)
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            assert not (await session.exec(select(UserRole).where(UserRole.role_id == 9))).all()


async def test_expanding_legacy_invalid_scope_does_not_activate_old_binding(binding_db):
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            role = await session.get(Role, 5)  # B-scoped definition, old grant in H=A.
    await RoleDefinitionRepository.update(role, {"department_id": None})
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            assert not (
                await session.exec(
                    select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 5, UserRole.tenant_id == 2)
                )
            ).all()


async def test_sso_subtree_move_updates_descendants_and_retires_secondary_support(binding_db, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from bisheng.department.domain.services import department_service as module

    monkeypatch.setattr(module, "get_async_db_session", binding_db.sessions)
    monkeypatch.setattr(module, "_prepare_department_projection", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "_bind_department_projection", AsyncMock())
    monkeypatch.setattr(module, "_execute_department_projection", AsyncMock())
    monkeypatch.setattr(module.DepartmentChangeHandler, "on_reparented", Mock(return_value=[]))
    monkeypatch.setattr(module.DepartmentChangeHandler, "execute_async", AsyncMock())
    with bypass_tenant_filter():
        async with binding_db.sessions() as session:
            session.add_all(
                [
                    Department(
                        id=31,
                        dept_id="synced",
                        name="synced",
                        tenant_id=1,
                        parent_id=20,
                        path="/10/20/31/",
                        source="wecom",
                        external_id="f009-move",
                    ),
                    Department(
                        id=32, dept_id="synced-child", name="child", tenant_id=1, parent_id=31, path="/10/20/31/32/"
                    ),
                    UserDepartment(id=11, user_id=77, department_id=32, is_primary=0),
                    Role(id=9, role_name="secondary policy", role_type="tenant", tenant_id=2, department_id=31),
                    UserRole(id=11, user_id=77, role_id=9, tenant_id=2),
                ]
            )
            await session.commit()
        await module.DepartmentTopologyProjectionService.aupsert_synced_department(
            source="wecom",
            external_id="f009-move",
            name="synced",
            parent_id=40,
            parent_path="/10/40/",
            sort_order=0,
            last_sync_ts=1,
        )
        async with binding_db.sessions() as session:
            assert (await session.get(Department, 32)).path == "/10/40/31/32/"
            assert not (await session.exec(select(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 9))).all()


async def test_mounted_tenant_factory_retires_bindings_in_its_coverage_transaction(binding_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from bisheng.database.models.tenant import Tenant
    from bisheng.tenant.application import tenant_creation

    monkeypatch.setattr(tenant_creation, "get_async_db_session", binding_db.sessions)
    monkeypatch.setattr(
        tenant_creation,
        "UnificationCoverageRepository",
        Mock(return_value=SimpleNamespace(aallocate_epoch=AsyncMock(return_value=2))),
    )
    monkeypatch.setattr(
        tenant_creation,
        "production_coverage_factory",
        Mock(
            return_value=SimpleNamespace(
                arequire_global_ready=AsyncMock(
                    return_value=SimpleNamespace(verified_tenant_ids=(1, 2, 3), coverage_epoch=1)
                )
            )
        ),
    )
    certify = AsyncMock()
    monkeypatch.setattr(tenant_creation, "_certify_created_tenant", certify)
    with bypass_tenant_filter():
        tenant = await tenant_creation.create_mounted_tenant_with_coverage(
            tenant=Tenant(tenant_code="new-mount", tenant_name="New", parent_tenant_id=2, root_dept_id=30),
            department_id=30,
            department_tenant_id=1,
        )
        async with binding_db.sessions() as session:
            assert (await session.get(Department, 30)).mounted_tenant_id == tenant.id
            bindings = (await session.exec(select(UserRole).where(UserRole.user_id == 77))).all()
            assert {(row.role_id, row.tenant_id) for row in bindings} == {(1, 1)}
    certify.assert_awaited_once()
