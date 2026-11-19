"""Unit tests for TenantAdminService (F013 T07).

Covers:
- Root tenant guard (id == 1 fast path AND parent_tenant_id IS NULL defensive)
- grant/revoke success path forwards semantic permission relations
- permission service unavailable raises the stable tenant error
- list_tenant_admins returns [] for Root and parses user IDs
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.tenant import TenantNotFoundError
from bisheng.common.errcode.tenant_fga import (
    PermissionBackendUnavailableError,
    RootTenantAdminNotAllowedError,
)
from bisheng.permission.application import PermissionObject, PermissionRelation, PermissionSubject
from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService


def _permissions(*, user_ids: tuple[str, ...] = ()):
    permissions = MagicMock()
    permissions.grant = AsyncMock()
    permissions.revoke = AsyncMock()
    permissions.list_subject_ids = AsyncMock(return_value=user_ids)
    return permissions


def _patch_permissions(permissions):
    return patch(
        "bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api",
        AsyncMock(return_value=permissions),
    )


# ── _guard_not_root ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_rejects_root_by_id_short_circuit():
    """tenant_id == 1 must short-circuit before DB or permission calls."""
    with (
        patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao,
        patch("bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api") as get_permissions,
    ):
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(tenant_id=1, user_id=10)
        dao.aget_by_id.assert_not_called()
        get_permissions.assert_not_called()


@pytest.mark.asyncio
async def test_grant_rejects_when_parent_tenant_id_null():
    """Defensive: any tenant with parent_tenant_id=None is treated as Root."""
    fake_tenant = SimpleNamespace(id=99, parent_tenant_id=None)
    with patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao:
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.grant_tenant_admin(tenant_id=99, user_id=10)


@pytest.mark.asyncio
async def test_grant_raises_tenant_not_found_when_missing():
    """Missing tenant now raises TenantNotFoundError (20000) — distinct from Root (19204)."""
    with patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao:
        dao.aget_by_id = AsyncMock(return_value=None)
        with pytest.raises(TenantNotFoundError):
            await TenantAdminService.grant_tenant_admin(tenant_id=99, user_id=10)


# ── grant happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_success_for_child_tenant():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    permissions = _permissions()

    with patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao, _patch_permissions(permissions):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)

    permissions.grant.assert_awaited_once_with(
        (
            PermissionRelation(
                subject=PermissionSubject("user", "10"),
                relation="admin",
                resource=PermissionObject("tenant", "5"),
            ),
        )
    )


@pytest.mark.asyncio
async def test_grant_raises_when_fga_unavailable():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    with (
        patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao,
        patch(
            "bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api",
            AsyncMock(side_effect=RuntimeError("permission down")),
        ),
    ):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        with pytest.raises(PermissionBackendUnavailableError):
            await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)


# ── revoke ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_success_for_child_tenant():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    permissions = _permissions()

    with patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao, _patch_permissions(permissions):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.revoke_tenant_admin(tenant_id=5, user_id=10)

    permissions.revoke.assert_awaited_once_with(
        (
            PermissionRelation(
                subject=PermissionSubject("user", "10"),
                relation="admin",
                resource=PermissionObject("tenant", "5"),
            ),
        )
    )


@pytest.mark.asyncio
async def test_revoke_rejects_root_short_circuit():
    with patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao:
        with pytest.raises(RootTenantAdminNotAllowedError):
            await TenantAdminService.revoke_tenant_admin(tenant_id=1, user_id=10)
        dao.aget_by_id.assert_not_called()


# ── list_tenant_admins ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_admins_returns_empty_for_root():
    """Root short-circuits without touching the permission service."""
    with patch("bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api") as get_permissions:
        result = await TenantAdminService.list_tenant_admins(tenant_id=1)
    assert result == []
    get_permissions.assert_not_called()


@pytest.mark.asyncio
async def test_list_admins_returns_empty_when_fga_unavailable():
    with patch(
        "bisheng.tenant.domain.services.tenant_admin_service.get_permission_relation_api",
        AsyncMock(side_effect=RuntimeError("permission down")),
    ):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)
    assert result == []


@pytest.mark.asyncio
async def test_list_admins_parses_user_ids():
    permissions = _permissions(user_ids=("7", "9"))
    with _patch_permissions(permissions):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)

    assert sorted(result) == [7, 9]


@pytest.mark.asyncio
async def test_list_admins_skips_non_numeric_users():
    permissions = _permissions(user_ids=("7", "foo"))
    with _patch_permissions(permissions):
        result = await TenantAdminService.list_tenant_admins(tenant_id=5)

    assert result == [7]


@pytest.mark.asyncio
async def test_grant_uses_permission_application_protocol():
    fake_tenant = SimpleNamespace(id=5, parent_tenant_id=1)
    permissions = _permissions()

    with (
        patch("bisheng.tenant.domain.services.tenant_admin_service.TenantDao") as dao,
        _patch_permissions(permissions) as get_permissions,
    ):
        dao.aget_by_id = AsyncMock(return_value=fake_tenant)
        await TenantAdminService.grant_tenant_admin(tenant_id=5, user_id=10)

    get_permissions.assert_awaited_once()
    permissions.grant.assert_awaited_once()


# ── list_tenant_admin_users ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_admin_users_resolves_names_and_marks_failures():
    """Root → [], lookup failure → None, deleted users dropped, names resolved."""

    async def _list_subject_ids(*, resource, relation, subject_type):
        if resource.resource_id == "6":
            raise RuntimeError("permission down")
        return {"5": ("7", "9", "404")}.get(resource.resource_id, ())

    permissions = MagicMock()
    permissions.list_subject_ids = AsyncMock(side_effect=_list_subject_ids)
    users = [SimpleNamespace(user_id=7, user_name="alice"), SimpleNamespace(user_id=9, user_name="bob")]
    with (
        _patch_permissions(permissions),
        patch("bisheng.user.domain.models.user.UserDao.aget_user_by_ids", AsyncMock(return_value=users)),
    ):
        result = await TenantAdminService.list_tenant_admin_users([1, 5, 6, 8])

    assert result == {
        1: [],
        5: [{"user_id": 7, "user_name": "alice"}, {"user_id": 9, "user_name": "bob"}],
        6: None,
        8: [],
    }


async def test_admin_avatar_query_is_limited_to_listed_users_in_the_managed_tenant():
    permissions = MagicMock()
    permissions.list_subject_ids = AsyncMock(return_value=("7", "8"))
    people = [
        SimpleNamespace(user_id=7, user_name="alice", avatar="avatar/7/current.png"),
        SimpleNamespace(user_id=8, user_name="bob", avatar="avatar/8/current.png"),
    ]
    seen = []

    async def avatars(pairs):
        seen.extend(pairs)
        return {(5, 7): "/object/bisheng/avatar/7/current.png"}

    with (
        _patch_permissions(permissions),
        patch("bisheng.user.domain.models.user.UserDao.aget_user_by_ids", AsyncMock(return_value=people)),
        patch("bisheng.tenant.domain.services.tenant_admin_service.read_visible_user_avatar_urls", avatars),
    ):
        result = await TenantAdminService.list_tenant_admin_users([5], include_avatars=True)

    assert seen == [(5, 7), (5, 8)]
    assert [user.get("avatar") for user in result[5]] == ["/object/bisheng/avatar/7/current.png", None]
