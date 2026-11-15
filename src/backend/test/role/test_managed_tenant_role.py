"""F009 AC-01, AC-02, AC-03: definition and menu writes retain owner scope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from bisheng.common.errcode.role import RoleNameDuplicateError, RolePermissionDeniedError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.role import Role
from bisheng.database.models.role_access import AccessType, RoleAccess
from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
from bisheng.role.domain.services.role_service import RoleService
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope


@pytest.fixture
async def role_db(managed_db, monkeypatch):
    import bisheng.database.models.role as role_module
    import bisheng.role.domain.services.role_service as service_module

    await managed_db.create(Role, RoleAccess)
    for module in (role_module, service_module):
        monkeypatch.setattr(module, "get_async_db_session", managed_db.sessions)
    # A repository added by the implementation must also use the same real DB.
    try:
        import bisheng.role.domain.repositories.role_definition_repository as repository
    except ModuleNotFoundError as exc:
        if exc.name != "bisheng.role.domain.repositories" and not exc.name.endswith("role_definition_repository"):
            raise
    else:
        monkeypatch.setattr(repository, "get_async_db_session", managed_db.sessions)
    with bypass_tenant_filter():
        async with managed_db.sessions() as session:
            session.add_all(
                [
                    Role(id=20, role_name="global", role_type="global", tenant_id=1),
                    Role(id=21, role_name="taken", role_type="global", tenant_id=1),
                    Role(id=22, role_name="child", role_type="tenant", tenant_id=2),
                    RoleAccess(id=1, role_id=20, type=AccessType.WEB_MENU.value, third_id="build", tenant_id=1),
                ]
            )
            await session.commit()
    monkeypatch.setattr(RoleService, "_check_role_permission", AsyncMock())
    monkeypatch.setattr(RoleService, "_ensure_role_mutation_access", AsyncMock())
    return managed_db


@pytest.mark.parametrize("operation", ["update_role", "update_role_with_menu", "update_menu"])
async def test_global_update_keeps_definition_and_menu_owner(role_db, operation):
    """AC-02: all save paths work when H=Root, M=Child and O=Root."""
    actor = SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True)
    with management_scope():
        if operation == "update_menu":
            await RoleService.update_menu(20, ["tool", "tool"], actor)
        else:
            await getattr(RoleService, operation)(20, RoleUpdateRequest(remark="saved", menu_ids=["tool"]), actor)
    with bypass_tenant_filter():
        async with role_db.sessions() as session:
            role = (await session.exec(select(Role).where(Role.id == 20))).one()
            menus = (await session.exec(select(RoleAccess).where(RoleAccess.role_id == 20))).all()
            assert role.tenant_id == 1
            if operation != "update_menu":
                assert role.remark == "saved"
            assert all(row.tenant_id == 1 for row in menus)
            assert {row.third_id for row in menus} == ({"build"} if operation == "update_role" else {"tool"})


async def test_duplicate_name_is_checked_in_definition_owner(role_db):
    """AC-03: owner-scope duplicate cannot disappear behind M."""
    actor = SimpleNamespace(user_id=7, tenant_id=2, is_admin=lambda: True)
    with management_scope(home=2, target=2), pytest.raises(RoleNameDuplicateError):
        await RoleService.update_role_with_menu(20, RoleUpdateRequest(role_name="taken", menu_ids=[]), actor)
    with bypass_tenant_filter():
        async with role_db.sessions() as session:
            role = (await session.exec(select(Role).where(Role.id == 20))).one()
            assert role.role_name == "global"
            assert (await session.exec(select(RoleAccess).where(RoleAccess.role_id == 20))).one().third_id == "build"


async def test_tenant_admin_cannot_update_global_definition(role_db):
    """AC-02: visibility of a global definition does not grant mutation."""
    actor = SimpleNamespace(user_id=8, tenant_id=2, is_admin=lambda: False)
    with management_scope(home=2), pytest.raises(RolePermissionDeniedError):
        await RoleService.update_menu(20, [], actor)


async def test_global_menu_read_uses_definition_owner(role_db, monkeypatch):
    """AC-02: the menu read after a save cannot hide Root associations."""
    monkeypatch.setattr(RoleService, "_ensure_role_scope_access", AsyncMock())
    actor = SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True)
    with management_scope():
        assert await RoleService.get_menu(20, actor) == ["build"]


async def test_absent_menu_is_preserved_and_explicit_empty_clears(role_db):
    """AC-02: absence and an explicit empty set have different meanings."""
    actor = SimpleNamespace(user_id=7, tenant_id=1, is_admin=lambda: True)
    with management_scope():
        await RoleService.update_role_with_menu(20, RoleUpdateRequest(remark="keep"), actor)
    with bypass_tenant_filter():
        async with role_db.sessions() as session:
            assert (await session.exec(select(RoleAccess).where(RoleAccess.role_id == 20))).one().third_id == "build"
    with management_scope():
        await RoleService.update_role_with_menu(20, RoleUpdateRequest(menu_ids=[]), actor)
    with bypass_tenant_filter():
        async with role_db.sessions() as session:
            assert (await session.exec(select(RoleAccess).where(RoleAccess.role_id == 20))).all() == []
