"""Change handlers delegate only to the permission application protocol."""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler


def _patch_permissions():
    permissions = AsyncMock()
    permissions.apply_changes = AsyncMock()
    return permissions, patch(
        "bisheng.permission.application.get_permission_relation_api",
        new=AsyncMock(return_value=permissions),
    )


@pytest.mark.parametrize(
    "changes",
    [
        DepartmentChangeHandler.on_created(dept_id=5, parent_id=1),
        DepartmentChangeHandler.on_members_added(dept_id=5, user_ids=[10, 11, 12]),
        DepartmentChangeHandler.on_moved(dept_id=5, old_parent_id=1, new_parent_id=2),
    ],
)
async def test_department_changes_use_crash_safe_permission_protocol(changes) -> None:
    permissions, permissions_patch = _patch_permissions()

    with permissions_patch:
        await DepartmentChangeHandler.execute_async(changes)

    permissions.apply_changes.assert_awaited_once_with(tuple(changes), crash_safe=True)


@pytest.mark.parametrize(
    "changes",
    [
        GroupChangeHandler.on_created(group_id=3, creator_user_id=1),
        GroupChangeHandler.on_members_added(group_id=3, user_ids=[10, 11]),
        GroupChangeHandler.on_member_removed(group_id=3, user_id=10),
    ],
)
async def test_group_changes_use_crash_safe_permission_protocol(changes) -> None:
    permissions, permissions_patch = _patch_permissions()

    with (
        permissions_patch,
        patch(
            "bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user",
            new=AsyncMock(),
        ),
    ):
        await GroupChangeHandler.execute_async(changes)

    permissions.apply_changes.assert_awaited_once_with(tuple(changes), crash_safe=True)


async def test_empty_changes_do_not_initialize_permission_runtime() -> None:
    with patch("bisheng.permission.application.get_permission_relation_api") as get_permissions:
        await DepartmentChangeHandler.execute_async([])
        await GroupChangeHandler.execute_async([])

    get_permissions.assert_not_called()
