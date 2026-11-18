"""F009 AC-21/22/24/28: tool child increments and mutations use their parent T."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import delete

from bisheng.common.errcode.tenant_quota import QuotaResponsibilityChangedError, TenantRoleQuotaExceededError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant
from bisheng.database.models.user_role import UserRole
from bisheng.role.domain.services.quota_service import QuotaResourceType, require_quota
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao, GptsToolsType, GptsToolsTypeRead
from bisheng.tool.domain.services.tool import ToolServices
from test.fixtures.managed_tenant import managed_db as managed_db
from test.fixtures.managed_tenant import management_scope
from test.quota.test_managed_tenant_quota import quota_db as quota_db
from test.role.test_effective_roles import policy_db as policy_db
from test.tool.test_managed_tenant_creation import tool_db as tool_db


async def test_update_children_inherits_parent_t_under_other_management_view(tool_db, monkeypatch):
    with bypass_tenant_filter():
        async with tool_db.sessions() as session:
            parent = GptsToolsType(id=9, name="parent", tenant_id=2, user_id=7)
            session.add(parent)
            await session.commit()
    monkeypatch.setattr(ToolServices, "_assert_tool_delta_quota", AsyncMock())
    req = GptsToolsTypeRead(id=9, name="parent", children=[GptsTools(name="new", tool_key="new", desc="", tenant_id=3)])
    with management_scope(1, 3):
        result = await ToolServices._update_gpts_tools(parent, req)
    assert len(result.children) == 1
    assert result.children[0].tenant_id == 2 and result.children[0].user_id == 7


async def test_bulk_tool_delete_stays_with_verified_parent_t(tool_db):
    with bypass_tenant_filter():
        async with tool_db.sessions() as session:
            parent = GptsToolsType(id=9, name="parent", tenant_id=2, user_id=7)
            session.add_all(
                [
                    parent,
                    GptsTools(id=11, type=9, name="a", tool_key="a", desc="", tenant_id=2),
                    GptsTools(id=12, type=9, name="legacy wrong scope", tool_key="b", desc="", tenant_id=3),
                ]
            )
            await session.commit()
    with management_scope(1, 3):
        await GptsToolsDao.update_tool_type(parent, [11, 12], [], [])
    with bypass_tenant_filter():
        async with tool_db.sessions() as session:
            assert (await session.get(GptsTools, 11)).is_delete == 1
            assert (await session.get(GptsTools, 12)).is_delete == 0


async def test_tool_create_precheck_uses_all_new_functions(quota_db):
    await quota_db.create(GptsToolsType, GptsTools)
    with bypass_tenant_filter():
        async with quota_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            for rid in (2, 3):
                (await session.get(Role, rid)).quota_config = {"tool": 2}
            await session.commit()
    write = AsyncMock()

    @require_quota(QuotaResourceType.TOOL)
    async def endpoint(*, login_user, req):
        await write()

    login = SimpleNamespace(user_id=77, tenant_id=2, is_admin=lambda: False)
    with management_scope(2, 2), pytest.raises(TenantRoleQuotaExceededError):
        await endpoint(login_user=login, req={"children": [{"name": "a"}, {"name": "b"}, {"name": "c"}]})
    write.assert_not_awaited()
    with management_scope(2, 2):
        await endpoint(login_user=login, req={"children": [{"name": "a"}, {"name": "b"}]})
    write.assert_awaited_once()


async def test_role_increment_with_zero_tenant_increment_works_at_tenant_cap(quota_db):
    await quota_db.create(GptsToolsType, GptsTools)
    with bypass_tenant_filter():
        async with quota_db.sessions() as session:
            await session.exec(delete(UserRole).where(UserRole.user_id == 77, UserRole.role_id == 1))
            for rid in (2, 3):
                (await session.get(Role, rid)).quota_config = {"tool": 2}
            tenant = await session.get(Tenant, 2)
            tenant.quota_config = {"tool": 2}
            session.add_all(
                [
                    GptsTools(id=11, type=9, name="owned", tool_key="a", desc="", tenant_id=2, user_id=77),
                    GptsTools(id=12, type=9, name="other", tool_key="b", desc="", tenant_id=2, user_id=78),
                ]
            )
            await session.commit()
    parent = SimpleNamespace(user_id=77, tenant_id=2, is_preset=ToolPresetType.API.value)
    with management_scope(2, 2):
        await ToolServices._assert_tool_delta_quota(parent, 1, 0)


async def test_moved_owner_tool_increment_cannot_use_editors_budget(policy_db):
    parent = SimpleNamespace(user_id=78, tenant_id=2, is_preset=ToolPresetType.API.value)
    editor = SimpleNamespace(is_admin=lambda: True)
    with pytest.raises(QuotaResponsibilityChangedError):
        await ToolServices._assert_tool_delta_quota(parent, 1, 1, editor)
    await ToolServices._assert_tool_delta_quota(parent, 0, 0, editor)
