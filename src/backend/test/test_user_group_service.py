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


class TestCreateGroupCompatibility:

    @pytest.mark.asyncio
    async def test_create_group_writes_legacy_creator_admin_row(self, mock_group_owner):
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        created_group = SimpleNamespace(
            id=25,
            group_name='Alpha',
            visibility='public',
            remark=None,
            create_user=mock_group_owner.user_id,
            update_user=mock_group_owner.user_id,
        )

        with patch(
            'bisheng.user_group.domain.services.user_group_service.GroupDao',
        ) as mock_group_dao, patch(
            'bisheng.user_group.domain.services.user_group_service.UserGroupDao',
        ) as mock_user_group_dao, patch(
            'bisheng.user_group.domain.services.user_group_service.GroupChangeHandler',
        ) as mock_change_handler, patch(
            'bisheng.user_group.domain.services.user_group_service._ensure_create_group',
            new_callable=AsyncMock,
        ), patch.object(
            UserGroupService, '_enrich_group', new_callable=AsyncMock,
            return_value={'id': 25, 'group_name': 'Alpha'},
        ):
            mock_group_dao.acheck_name_duplicate = AsyncMock(return_value=False)
            mock_group_dao.acreate = AsyncMock(return_value=created_group)
            mock_user_group_dao.aset_admins_batch = AsyncMock()
            mock_change_handler.on_created.return_value = ['member-op', 'admin-op']
            mock_change_handler.execute_async = AsyncMock()

            await UserGroupService.acreate_group(
                data=SimpleNamespace(
                    group_name='Alpha',
                    visibility='public',
                    remark=None,
                    admin_user_ids=None,
                ),
                login_user=mock_group_owner,
            )

        mock_user_group_dao.aset_admins_batch.assert_awaited_once_with(
            25, add_ids=[mock_group_owner.user_id], remove_ids=[],
        )
        mock_change_handler.on_created.assert_called_once_with(25, mock_group_owner.user_id)
        mock_change_handler.execute_async.assert_awaited_once_with(['member-op', 'admin-op'])


class TestManageableGroups:

    @pytest.mark.asyncio
    async def test_global_super_is_treated_as_admin_for_manageable_groups(self):
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        login_user = SimpleNamespace(
            user_id=88,
            tenant_id=1,
            user_role=[2],
            is_global_super=True,
        )
        all_groups = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        with patch(
            'bisheng.user_group.domain.services.user_group_service.GroupDao',
        ) as mock_group_dao:
            mock_group_dao.aget_all_groups = AsyncMock(return_value=(all_groups, len(all_groups)))

            groups = await UserGroupService._list_manageable_groups(login_user)

        assert groups == all_groups
        mock_group_dao.aget_all_groups.assert_awaited_once_with(1, 2000, '')

    @pytest.mark.asyncio
    async def test_tenant_admin_is_treated_as_admin_for_manageable_groups(self):
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        login_user = SimpleNamespace(
            user_id=66,
            tenant_id=9,
            user_role=[2],
            is_global_super=False,
        )
        all_groups = [SimpleNamespace(id=3), SimpleNamespace(id=4)]

        with patch(
            'bisheng.department.domain.services.department_service._is_tenant_admin',
            new_callable=AsyncMock, return_value=True,
        ), patch(
            'bisheng.user_group.domain.services.user_group_service.GroupDao',
        ) as mock_group_dao:
            mock_group_dao.aget_all_groups = AsyncMock(return_value=(all_groups, len(all_groups)))

            groups = await UserGroupService._list_manageable_groups(login_user)

        assert groups == all_groups
        mock_group_dao.aget_all_groups.assert_awaited_once_with(1, 2000, '')


class TestListGroups:

    @pytest.mark.asyncio
    async def test_tenant_admin_gets_all_groups_in_management_list(self):
        from bisheng.user_group.domain.services.user_group_service import UserGroupService

        login_user = SimpleNamespace(
            user_id=66,
            tenant_id=9,
            user_role=[2],
            is_global_super=False,
        )
        groups = [SimpleNamespace(id=1, group_name='A'), SimpleNamespace(id=2, group_name='B')]

        with patch(
            'bisheng.department.domain.services.department_service._is_tenant_admin',
            new_callable=AsyncMock, return_value=True,
        ), patch(
            'bisheng.user_group.domain.services.user_group_service.GroupDao',
        ) as mock_group_dao, patch.object(
            UserGroupService, '_enrich_groups',
            new_callable=AsyncMock, return_value=[{'id': 1}, {'id': 2}],
        ):
            mock_group_dao.aget_all_groups = AsyncMock(return_value=(groups, 2))

            result = await UserGroupService.alist_groups(1, 20, '', login_user)

        assert result == {'data': [{'id': 1}, {'id': 2}], 'total': 2}
        mock_group_dao.aget_all_groups.assert_awaited_once_with(1, 20, '')
