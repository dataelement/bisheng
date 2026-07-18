"""Unit tests for the per-area menu approval scope computation.

Covers ``LoginUser.compute_menu_approval_modes`` (workbench/admin split with
legacy fallback) and ``compute_menu_approval_mode_for_menu`` (scope resolution
by menu key).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import bisheng.user.domain.services.auth as auth_module

LoginUser = auth_module.LoginUser

# Non-super-admin role id (super-admin AdminRole is excluded by the compute).
_ROLE_ID = 2


def _patch_roles(quota_configs):
    """Patch the DAO chain so the user maps to roles with the given quota_configs."""
    user_roles = [SimpleNamespace(role_id=_ROLE_ID + i) for i in range(len(quota_configs))]
    roles = [SimpleNamespace(quota_config=qc) for qc in quota_configs]
    return patch.multiple(
        "bisheng.user.domain.services.auth",
        UserRoleDao=SimpleNamespace(aget_user_roles=AsyncMock(return_value=user_roles)),
        RoleDao=SimpleNamespace(aget_role_by_ids=AsyncMock(return_value=roles)),
    )


@pytest.mark.asyncio
async def test_legacy_flag_falls_back_to_both_scopes():
    user = SimpleNamespace(user_id=7)
    with _patch_roles([{"menu_approval_mode": True}]):
        workbench, admin = await LoginUser.compute_menu_approval_modes(user)
    assert workbench is True
    assert admin is True


@pytest.mark.asyncio
async def test_scoped_flags_are_independent():
    user = SimpleNamespace(user_id=7)
    with _patch_roles(
        [
            {"menu_approval_mode_workbench": True, "menu_approval_mode_admin": False},
        ]
    ):
        workbench, admin = await LoginUser.compute_menu_approval_modes(user)
    assert workbench is True
    assert admin is False


@pytest.mark.asyncio
async def test_scoped_key_overrides_legacy():
    """A scoped key wins over the legacy global flag for its own area."""
    user = SimpleNamespace(user_id=7)
    with _patch_roles(
        [
            # admin explicitly off; workbench unset → falls back to legacy True.
            {"menu_approval_mode": True, "menu_approval_mode_admin": False},
        ]
    ):
        workbench, admin = await LoginUser.compute_menu_approval_modes(user)
    assert workbench is True
    assert admin is False


@pytest.mark.asyncio
async def test_union_across_multiple_roles():
    user = SimpleNamespace(user_id=7)
    with _patch_roles(
        [
            {"menu_approval_mode_workbench": True},
            {"menu_approval_mode_admin": True},
        ]
    ):
        workbench, admin = await LoginUser.compute_menu_approval_modes(user)
    assert workbench is True
    assert admin is True


@pytest.mark.asyncio
async def test_no_roles_returns_false():
    user = SimpleNamespace(user_id=7)
    with patch.multiple(
        "bisheng.user.domain.services.auth",
        UserRoleDao=SimpleNamespace(aget_user_roles=AsyncMock(return_value=[])),
        RoleDao=SimpleNamespace(aget_role_by_ids=AsyncMock(return_value=[])),
    ):
        workbench, admin = await LoginUser.compute_menu_approval_modes(user)
    assert workbench is False
    assert admin is False


@pytest.mark.asyncio
async def test_for_menu_resolves_admin_scope_for_admin_menu():
    user = SimpleNamespace(user_id=7)
    with _patch_roles(
        [
            {"menu_approval_mode_workbench": True, "menu_approval_mode_admin": False},
        ]
    ):
        # 'knowledge' is an admin-area menu → admin scope (False).
        assert await LoginUser.compute_menu_approval_mode_for_menu(user, "knowledge") is False
        # 'apps' is a workbench menu → workbench scope (True).
        assert await LoginUser.compute_menu_approval_mode_for_menu(user, "apps") is True


def test_default_web_entry_regular_user_prefers_workspace():
    """Regular users land on 工作台; admins keep 管理后台 priority."""
    # Regular user with BOTH areas → 工作台 (not dropped into the console on login).
    assert LoginUser.default_web_entry(True, True, prefer_workbench=True) == "workspace"
    # Admin (prefer_workbench=False) with both areas keeps 管理后台.
    assert LoginUser.default_web_entry(True, True, prefer_workbench=False) == "platform"
    # Regular user with admin menus but no workbench still falls back to 管理后台.
    assert LoginUser.default_web_entry(False, True, prefer_workbench=True) == "platform"
    # Only workbench → 工作台 regardless of the flag.
    assert LoginUser.default_web_entry(True, False) == "workspace"
    # Neither area → 管理后台 default.
    assert LoginUser.default_web_entry(False, False, prefer_workbench=True) == "platform"
