"""Unit tests for UserGroupService membership replacement helpers."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_group_owner():
    user = SimpleNamespace()
    user.user_id = 7
    user.tenant_id = 1
    user.is_admin = lambda: False
    return user


class TestReplaceUserMemberships:

    @pytest.mark.asyncio
    async def test_rejects_groups_outside_manageable_scope(self, mock_group_owner):
        from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        manageable = [SimpleNamespace(id=10)]

        with patch.object(
            UserGroupService, "_list_manageable_groups",
            new_callable=AsyncMock, return_value=manageable,
        ):
            with pytest.raises(UserGroupPermissionDeniedError):
                await UserGroupService.areplace_user_memberships(
                    user_id=12,
                    desired_group_ids=[10, 11],
                    login_user=mock_group_owner,
                )

    @pytest.mark.asyncio
    async def test_replaces_only_manageable_memberships(self, mock_group_owner):
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        manageable = [
            SimpleNamespace(id=10),
            SimpleNamespace(id=11),
            SimpleNamespace(id=12),
        ]
        current_links = [
            SimpleNamespace(group_id=10),
            SimpleNamespace(group_id=11),
            SimpleNamespace(group_id=99),  # outside manageable scope; preserved
        ]

        with patch.object(
            UserGroupService, "_list_manageable_groups",
            new_callable=AsyncMock, return_value=manageable,
        ), patch(
            "bisheng.user_group.domain.services.user_group_service.UserGroupDao",
        ) as mock_dao, patch.object(
            UserGroupService, "aremove_member", new_callable=AsyncMock,
        ) as mock_remove, patch.object(
            UserGroupService, "aadd_members", new_callable=AsyncMock,
        ) as mock_add:
            mock_dao.aget_user_group = AsyncMock(return_value=current_links)

            await UserGroupService.areplace_user_memberships(
                user_id=12,
                desired_group_ids=[11, 12],
                login_user=mock_group_owner,
            )

        mock_remove.assert_awaited_once_with(10, 12, mock_group_owner)
        mock_add.assert_awaited_once_with(12, [12], mock_group_owner)
