"""Tests for ``DepartmentKnowledgeSpaceService.cleanup_removed_department_admins``.

When a user loses department-admin status via a path that carries no
``login_user`` (调岗 / SSO 同步 / 账号删除), the derived knowledge-space bindings
must still be cleared:

- the ``space_channel_member`` row (``membership_source=department_admin``), and
- the ``knowledge_space#manager`` OpenFGA tuple.

Otherwise the user keeps manage access to the space after losing the admin role
(越权 residue). These were previously only cleaned on the manual ``aset_admins``
/ ``aremove_member`` paths.

DAO / FGA interactions are mocked — this suite validates the binding cleanup
orchestration, not DB behaviour.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.models.space_channel_member import (
    MembershipStatusEnum,
    UserRoleEnum,
)
from bisheng.knowledge.domain.services import (
    department_knowledge_space_service as mod,
)
from bisheng.knowledge.domain.services.department_knowledge_space_service import (
    DepartmentKnowledgeSpaceService,
)


def _member(
    *,
    role=UserRoleEnum.ADMIN,
    source="department_admin",
    promoted_from=None,
    status=MembershipStatusEnum.ACTIVE,
    user_id=139439,
):
    return SimpleNamespace(
        id=1,
        user_id=user_id,
        user_role=role,
        membership_source=source,
        department_admin_promoted_from_role=promoted_from,
        status=status,
    )


@pytest.fixture()
def patches(monkeypatch):
    space_lookup = AsyncMock(return_value=139)
    monkeypatch.setattr(
        mod.DepartmentKnowledgeSpaceDao,
        "aget_space_id_by_department_id",
        space_lookup,
    )
    find = AsyncMock()
    delete = AsyncMock(return_value=True)
    update = AsyncMock()
    monkeypatch.setattr(mod.SpaceChannelMemberDao, "async_find_member", find)
    monkeypatch.setattr(mod.SpaceChannelMemberDao, "delete_space_member", delete)
    monkeypatch.setattr(mod.SpaceChannelMemberDao, "update", update)
    authorize = AsyncMock()
    monkeypatch.setattr(mod.PermissionService, "authorize", authorize)
    return SimpleNamespace(
        space_lookup=space_lookup,
        find=find,
        delete=delete,
        update=update,
        authorize=authorize,
    )


def test_cleanup_deletes_binding_and_revokes_manager(patches):
    """department_admin member with no prior manual role → delete row + revoke manager tuple."""
    patches.find.return_value = _member()

    asyncio.run(
        DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=36460,
            user_ids=[139439],
        )
    )

    patches.delete.assert_awaited_once_with(139, 139439)
    # knowledge_space#manager tuple revoked (authorize called with revokes only).
    patches.authorize.assert_awaited_once()
    _, kwargs = patches.authorize.call_args
    assert kwargs.get("revokes")
    assert not kwargs.get("grants")


def test_cleanup_demotes_back_to_promoted_role(patches):
    """A manual member temporarily promoted to admin → restore prior role, don't delete."""
    patches.find.return_value = _member(promoted_from="member")

    asyncio.run(
        DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=36460,
            user_ids=[139439],
        )
    )

    patches.delete.assert_not_awaited()
    patches.update.assert_awaited_once()
    updated = patches.update.call_args.args[0]
    assert updated.user_role == UserRoleEnum.MEMBER
    assert updated.membership_source == "manual"
    assert updated.department_admin_promoted_from_role is None
    patches.authorize.assert_awaited_once()  # manager tuple still revoked


def test_cleanup_noop_when_department_has_no_space(patches):
    patches.space_lookup.return_value = None

    asyncio.run(
        DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=999,
            user_ids=[139439],
        )
    )

    patches.find.assert_not_awaited()
    patches.delete.assert_not_awaited()


def test_cleanup_skips_missing_member(patches):
    patches.find.return_value = None

    asyncio.run(
        DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=36460,
            user_ids=[139439],
        )
    )

    patches.delete.assert_not_awaited()
    patches.update.assert_not_awaited()


def test_cleanup_leaves_manual_admin_untouched(patches):
    """A genuine manual ADMIN (not department_admin source) must keep their role."""
    patches.find.return_value = _member(source="manual", role=UserRoleEnum.ADMIN)

    asyncio.run(
        DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=36460,
            user_ids=[139439],
        )
    )

    patches.delete.assert_not_awaited()
    patches.update.assert_not_awaited()
