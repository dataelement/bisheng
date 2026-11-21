"""Every member and group delta must validate before the first mutation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError
from bisheng.user_group.domain.repositories.member_identity_repository import MemberIdentityRepository
from bisheng.user_group.domain.services import user_group_service as module


@pytest.fixture
def membership_case(monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id

    token = current_tenant_id.set(3)
    actor = SimpleNamespace(user_id=11, tenant_id=3, user_role=[2])
    groups = {key: SimpleNamespace(id=key, tenant_id=3, create_user=11, visibility="public") for key in (20, 21)}
    monkeypatch.setattr(module.GroupDao, "aget_by_id", AsyncMock(side_effect=lambda key: groups.get(key)))
    monkeypatch.setattr(module, "_ensure_mutate_group_members", AsyncMock(return_value=True))
    members = AsyncMock(return_value={101})
    monkeypatch.setattr(MemberIdentityRepository, "tenant_member_ids", members)
    monkeypatch.setattr(module.UserGroupDao, "aget_plain_member_user_ids", AsyncMock(return_value=[101]))
    monkeypatch.setattr(module.UserGroupDao, "aget_user_group", AsyncMock(return_value=[SimpleNamespace(group_id=20)]))
    monkeypatch.setattr(
        module.UserGroupService, "_list_manageable_groups", AsyncMock(return_value=list(groups.values()))
    )
    effects = [AsyncMock() for _ in range(3)]
    monkeypatch.setattr(module.UserGroupDao, "adelete_plain_members_batch", effects[0])
    monkeypatch.setattr(module.UserGroupDao, "aadd_members_batch", effects[1])
    monkeypatch.setattr(module.GroupChangeHandler, "execute_async", effects[2])
    monkeypatch.setattr(module.UserGroupService, "_audit_group", MagicMock())
    yield SimpleNamespace(actor=actor, groups=groups, members=members, effects=effects)
    current_tenant_id.reset(token)


async def test_sync_rejects_foreign_desired_member_before_removing_existing(membership_case):
    case = membership_case
    with pytest.raises(UserGroupPermissionDeniedError):
        await module.UserGroupService.async_plain_members(20, [202], case.actor)
    for effect in case.effects:
        effect.assert_not_awaited()


async def test_replacement_validates_later_group_before_first_remove(membership_case, monkeypatch):
    case = membership_case

    async def policy(user, group):
        if group.id == 21:
            raise UserGroupPermissionDeniedError()
        return True

    monkeypatch.setattr(module, "_ensure_mutate_group_members", policy)
    remove = AsyncMock()
    monkeypatch.setattr(module.UserGroupService, "aremove_member", remove)
    with pytest.raises(UserGroupPermissionDeniedError):
        await module.UserGroupService.areplace_user_memberships(101, [21], case.actor)
    remove.assert_not_awaited()


async def test_delegated_legacy_group_admin_cannot_assign_foreign_user(membership_case, monkeypatch):
    from bisheng.permission import application

    monkeypatch.setattr(
        application,
        "get_permission_relation_api",
        AsyncMock(return_value=SimpleNamespace(check=AsyncMock(return_value=True))),
    )
    with pytest.raises(UserGroupPermissionDeniedError):
        await module.UserGroupService.avalidate_legacy_membership_changes(
            membership_case.actor, 202, [20], delegated_group_ids=[20]
        )


async def test_sync_all_valid_members_keeps_legitimate_batch(membership_case):
    case = membership_case
    case.members.return_value = {101, 102}
    await module.UserGroupService.async_plain_members(20, [101, 102], case.actor)
    case.effects[0].assert_not_awaited()
    case.effects[1].assert_awaited_once_with(20, [102])


async def test_later_foreign_group_cannot_delete_earlier_group_membership(membership_case, monkeypatch):
    case = membership_case
    case.groups[21].tenant_id = 4
    remove = AsyncMock()
    monkeypatch.setattr(module.UserGroupService, "aremove_member", remove)
    with pytest.raises(UserGroupPermissionDeniedError):
        await module.UserGroupService.areplace_user_memberships(101, [21], case.actor)
    remove.assert_not_awaited()


async def test_replacement_validates_user_before_first_remove(membership_case, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(module.UserGroupService, "aremove_member", remove)
    with pytest.raises(UserGroupPermissionDeniedError):
        await module.UserGroupService.areplace_user_memberships(202, [21], membership_case.actor)
    remove.assert_not_awaited()
