"""F048 identity-only legacy callback contracts."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_role_access_callbacks_never_project_business_tuples() -> None:
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        ACCESS_TYPE_TO_FGA,
        LegacyRBACSyncService,
    )

    assert ACCESS_TYPE_TO_FGA == {}
    with patch.object(
        LegacyRBACSyncService,
        "_write_operations",
        new_callable=AsyncMock,
    ) as write_operations:
        await LegacyRBACSyncService.sync_role_access_change(
            2,
            1,
            ["old"],
            ["new"],
        )
        await LegacyRBACSyncService.sync_role_deleted(2)
        await LegacyRBACSyncService.reconcile_user_role_access(7)

    write_operations.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_user_role_change_writes_super_admin_identity() -> None:
    from bisheng.database.constants import AdminRole
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
    )

    with patch.object(
        LegacyRBACSyncService,
        "_write_operations",
        new_callable=AsyncMock,
    ) as write_operations:
        await LegacyRBACSyncService.sync_user_role_change(
            1,
            [],
            [AdminRole],
        )

    operations, affected = write_operations.await_args.args
    assert [
        (operation.action, operation.user, operation.relation, operation.object)
        for operation in operations
    ] == [
        ("write", "user:1", "super_admin", "system:global"),
    ]
    assert affected == [1]


@pytest.mark.asyncio
async def test_sync_user_auth_created_writes_group_identities() -> None:
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
    )

    with patch.object(
        LegacyRBACSyncService,
        "sync_user_role_change",
        new_callable=AsyncMock,
    ) as role_sync, patch.object(
        LegacyRBACSyncService,
        "_write_operations",
        new_callable=AsyncMock,
    ) as write_operations:
        await LegacyRBACSyncService.sync_user_auth_created(
            5,
            [2],
            member_group_ids=[7],
            admin_group_ids=[8],
        )

    role_sync.assert_awaited_once_with(5, [], [2])
    operations, affected = write_operations.await_args.args
    assert {
        (operation.action, operation.user, operation.relation, operation.object)
        for operation in operations
    } == {
        ("write", "user:5", "member", "user_group:7"),
        ("write", "user:5", "admin", "user_group:8"),
    }
    assert affected == [5]


@pytest.mark.asyncio
async def test_group_change_handler_invalidates_direct_user_cache() -> None:
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.user_group.domain.services.group_change_handler import (
        GroupChangeHandler,
    )

    operations = [
        TupleOperation(
            action="write",
            user="user:9",
            relation="member",
            object="user_group:3",
        ),
        TupleOperation(
            action="write",
            user="user_group:3#member",
            relation="ordinary_assignee",
            object="permission_grant:g1",
        ),
    ]
    with patch(
        "bisheng.permission.domain.services.permission_service."
        "PermissionService.batch_write_tuples",
        new_callable=AsyncMock,
    ) as batch_write, patch(
        "bisheng.permission.domain.services.permission_cache."
        "PermissionCache.invalidate_user",
        new_callable=AsyncMock,
    ) as invalidate:
        await GroupChangeHandler.execute_async(operations)

    batch_write.assert_awaited_once_with(operations, crash_safe=True)
    invalidate.assert_awaited_once_with(9)
