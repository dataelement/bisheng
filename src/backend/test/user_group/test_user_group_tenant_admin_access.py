"""Tests for `_can_open_user_group_management` admitting Child Admin (tenant admin).

PRD §4.5 + F003 routing: a tenant admin (Child Admin) can enter the user
group management section. Tenant-isolated listing of groups is tracked
under v2.5.1 / F023.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.user_group.domain.services import user_group_service as m


def _user(user_id=10, user_role=None):
    return SimpleNamespace(
        user_id=user_id,
        user_role=user_role if user_role is not None else [2],
    )


@pytest.mark.asyncio
async def test_can_open_admits_sys_admin():
    assert await m._can_open_user_group_management(_user(user_role=[1])) is True


@pytest.mark.asyncio
async def test_can_open_admits_dept_admin():
    with patch.object(
        m,
        "_is_department_admin",
        new_callable=AsyncMock,
        return_value=True,
    ):
        assert await m._can_open_user_group_management(_user()) is True


@pytest.mark.asyncio
async def test_can_open_admits_tenant_admin():
    """Child Admin via tenant#admin → access permitted."""
    with (
        patch.object(
            m,
            "_is_department_admin",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.department.domain.services.department_service._is_tenant_admin",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        assert await m._can_open_user_group_management(_user()) is True


@pytest.mark.asyncio
async def test_can_open_rejects_plain_user():
    with (
        patch.object(
            m,
            "_is_department_admin",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.department.domain.services.department_service._is_tenant_admin",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        assert await m._can_open_user_group_management(_user()) is False


@pytest.mark.parametrize("group_tenant,admin,allowed", [(60, True, True), (1, True, False), (60, False, False)])
async def test_membership_mutation_matches_tenant_management_scope(group_tenant, admin, allowed):
    from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError

    user = SimpleNamespace(user_id=10, user_role=[2], tenant_id=60)
    group = SimpleNamespace(id=20, tenant_id=group_tenant, create_user=99, visibility="private")
    with patch("bisheng.department.domain.services.department_service._is_tenant_admin", AsyncMock(return_value=admin)):
        if allowed:
            await m._ensure_mutate_group_members(user, group)
        else:
            with pytest.raises(UserGroupPermissionDeniedError):
                await m._ensure_mutate_group_members(user, group)


@pytest.mark.parametrize("members,allowed", [({871}, True), (set(), False)])
async def test_tenant_admin_cannot_assign_foreign_personnel(monkeypatch, members, allowed):
    from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError
    from bisheng.user_group.domain.repositories.member_identity_repository import MemberIdentityRepository

    monkeypatch.setattr(
        "bisheng.department.domain.services.department_service._is_tenant_admin", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(MemberIdentityRepository, "tenant_member_ids", AsyncMock(return_value=members))
    user = SimpleNamespace(user_id=868, user_role=[2], tenant_id=60)
    group = SimpleNamespace(id=20, tenant_id=60)
    if allowed:
        await m._ensure_tenant_member_scope(user, group, [871], tenant_admin=True)
    else:
        with pytest.raises(UserGroupPermissionDeniedError):
            await m._ensure_tenant_member_scope(user, group, [871], tenant_admin=True)


@pytest.mark.parametrize("desired,allowed", [([182, 99], True), ([182, 99, 100], False)])
async def test_unchanged_unmanageable_membership_is_preserved(monkeypatch, desired, allowed):
    from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError

    monkeypatch.setattr(
        m.UserGroupService, "_list_manageable_groups", AsyncMock(return_value=[SimpleNamespace(id=182)])
    )
    monkeypatch.setattr(
        m.UserGroupDao,
        "aget_user_group",
        AsyncMock(return_value=[SimpleNamespace(group_id=182), SimpleNamespace(group_id=99)]),
    )
    add, remove = AsyncMock(), AsyncMock()
    monkeypatch.setattr(m.UserGroupService, "aadd_members", add)
    monkeypatch.setattr(m.UserGroupService, "aremove_member", remove)
    if allowed:
        await m.UserGroupService.areplace_user_memberships(871, desired, _user())
    else:
        with pytest.raises(UserGroupPermissionDeniedError):
            await m.UserGroupService.areplace_user_memberships(871, desired, _user())
    add.assert_not_awaited()
    remove.assert_not_awaited()
