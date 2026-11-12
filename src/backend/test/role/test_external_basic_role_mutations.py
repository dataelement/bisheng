"""覆盖 AC: AC-04, AC-09, AC-13。真实仓储核对普通和旧入口。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from sqlmodel import select

from bisheng.common.errcode.sso_sync import KunlianBindingConflictError, KunlianIdentityUnavailableError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.role import Role, RoleDao, RoleUpdate
from bisheng.role.domain.models.external_basic_role import RoleExternalBasicRole
from bisheng.role.domain.schemas.role_schema import RoleUpdateRequest
from bisheng.role.domain.services.role_service import RoleService
from test.fixtures import kunlian_onboarding
from test.role.test_external_basic_role import setup_role

onboarding_store = kunlian_onboarding.onboarding_store


@pytest.mark.parametrize("entry", ["menu", "combined", "legacy_update", "delete", "legacy_delete"])
async def test_managed_mutation_all_entrypoints_share_template_transaction(onboarding_store, monkeypatch, entry):
    from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService
    from bisheng.role.application import external_basic_role as port
    from bisheng.user.api import user as api

    _, app = await setup_role(onboarding_store)
    monkeypatch.setattr(port, "get_repository", lambda: app.repository)
    monkeypatch.setattr(RoleService, "_check_role_permission", AsyncMock())
    monkeypatch.setattr(RoleService, "_ensure_role_mutation_access", AsyncMock())
    monkeypatch.setattr(LegacyRBACSyncService, "sync_role_deleted", AsyncMock())
    monkeypatch.setattr(api, "update_role_hook", lambda *a: None)
    monkeypatch.setattr(api.AuditLogService, "delete_role", lambda *a: None)
    actor = SimpleNamespace(
        user_id=101,
        tenant_id=7,
        is_admin=lambda: True,
        async_check_group_admin=AsyncMock(return_value=True),
        check_group_admin=lambda _: True,
    )
    with tenant_execution_scope(7):
        op = await app.reserve_external_basic_role("fixture", 7)
        receipt = await app.ensure_external_basic_role(op)

        async def get_role(rid):
            async with onboarding_store.sessions() as session:
                return (await session.exec(select(Role).where(Role.id == rid))).first()

        monkeypatch.setattr(RoleDao, "aget_role_by_id", get_role)
        if entry == "menu":
            await RoleService.update_menu(receipt.role_id, ["admin", "build"], actor)
        elif entry == "combined":
            await RoleService.update_role_with_menu(
                receipt.role_id, RoleUpdateRequest(menu_ids=["admin", "build"]), actor
            )
        elif entry == "legacy_update":
            await api.update_role(
                request=Request({"type": "http"}),
                role_id=receipt.role_id,
                role=RoleUpdate(remark="兼容说明"),
                login_user=actor,
            )
            assert (await get_role(receipt.role_id)).remark == "兼容说明"
        elif entry == "delete":
            await RoleService.delete_role(receipt.role_id, actor)
        else:
            original = await get_role(receipt.role_id)
            original.group_id = 5
            monkeypatch.setattr(RoleDao, "get_role_by_id", lambda _: original)
            await api.delete_role(
                request=Request({"type": "http", "client": ("127.0.0.1", 1), "headers": []}),
                role_id=receipt.role_id,
                login_user=actor,
            )
        async with onboarding_store.sessions() as session:
            state = (await session.exec(select(RoleExternalBasicRole))).one()
            assert state.state == ("APPLIED" if entry == "legacy_update" else "SUSPENDED")
        if entry != "legacy_update":
            with pytest.raises(KunlianIdentityUnavailableError):
                await app.reserve_external_basic_role("fixture", 7)


async def test_template_menu_expansion_is_refused_even_with_global_admin(onboarding_store, monkeypatch):
    from bisheng.role.application import external_basic_role as port

    _, app = await setup_role(onboarding_store)
    monkeypatch.setattr(port, "get_repository", lambda: app.repository)
    monkeypatch.setattr(RoleService, "_check_role_permission", AsyncMock())
    monkeypatch.setattr(RoleService, "_ensure_role_mutation_access", AsyncMock())
    with tenant_execution_scope(7):
        receipt = await app.ensure_external_basic_role(await app.reserve_external_basic_role("fixture", 7))
        async with onboarding_store.sessions() as session:
            row = (await session.exec(select(Role).where(Role.id == receipt.role_id))).one()
        monkeypatch.setattr(RoleDao, "aget_role_by_id", AsyncMock(return_value=row))
        with pytest.raises(KunlianBindingConflictError):
            await RoleService.update_menu(
                row.id, ["admin", "build", "create_app"], SimpleNamespace(is_admin=lambda: True, tenant_id=7)
            )
