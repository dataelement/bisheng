from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_role_access_signature_expansion_dedupes_to_highest_relation():
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
        RoleAccessSignature,
    )

    with patch.object(
        LegacyRBACSyncService,
        '_role_access_rows',
        new_callable=AsyncMock,
        return_value=[
            (2, 'kb-1', 1),
            (2, 'kb-1', 3),
            (2, 'asst-1', 5),
        ],
    ):
        result = await LegacyRBACSyncService._role_access_signatures_for_roles(7, {2})

    assert result == {
        RoleAccessSignature('user:7', 'editor', 'knowledge_library', 'kb-1'),
        RoleAccessSignature('user:7', 'editor', 'knowledge_space', 'kb-1'),
        RoleAccessSignature('user:7', 'viewer', 'assistant', 'asst-1'),
    }


@pytest.mark.asyncio
async def test_sync_user_role_change_deletes_stale_except_explicit_bindings():
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
        RoleAccessSignature,
    )

    protected = RoleAccessSignature('user:5', 'viewer', 'workflow', 'wf-protected')
    stale = RoleAccessSignature('user:5', 'editor', 'workflow', 'wf-old')
    desired = RoleAccessSignature('user:5', 'editor', 'workflow', 'wf-new')

    with patch.object(
        LegacyRBACSyncService,
        '_role_access_signatures_for_roles',
        new_callable=AsyncMock,
        side_effect=[{protected, stale}, {desired}],
    ), patch.object(
        LegacyRBACSyncService,
        '_resource_permission_user_binding_set',
        new_callable=AsyncMock,
        return_value={protected},
    ), patch.object(
        LegacyRBACSyncService,
        '_write_operations',
        new_callable=AsyncMock,
    ) as write_ops:
        await LegacyRBACSyncService.sync_user_role_change(5, [2], [3])

    operations, affected = write_ops.await_args.args
    assert {(op.action, op.user, op.relation, op.object) for op in operations} == {
        ('delete', 'user:5', 'editor', 'workflow:wf-old'),
        ('write', 'user:5', 'editor', 'workflow:wf-new'),
    }
    assert affected == {5}


@pytest.mark.asyncio
async def test_sync_role_deleted_preserves_grants_from_remaining_roles():
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
        RoleAccessSignature,
    )

    shared = RoleAccessSignature('user:5', 'viewer', 'workflow', 'wf-shared')
    removed = RoleAccessSignature('user:5', 'editor', 'workflow', 'wf-old')

    with patch.object(
        LegacyRBACSyncService,
        '_user_ids_for_role',
        new_callable=AsyncMock,
        return_value=[5],
    ), patch.object(
        LegacyRBACSyncService,
        '_role_ids_for_user',
        new_callable=AsyncMock,
        return_value={2, 3},
    ), patch.object(
        LegacyRBACSyncService,
        '_role_access_signatures_for_roles',
        new_callable=AsyncMock,
        side_effect=[{shared, removed}, {shared}],
    ), patch.object(
        LegacyRBACSyncService,
        '_resource_permission_user_binding_set',
        new_callable=AsyncMock,
        return_value=set(),
    ), patch.object(
        LegacyRBACSyncService,
        '_write_operations',
        new_callable=AsyncMock,
    ) as write_ops:
        await LegacyRBACSyncService.sync_role_deleted(2)

    operations, affected = write_ops.await_args.args
    assert [(op.action, op.user, op.relation, op.object) for op in operations] == [
        ('delete', 'user:5', 'editor', 'workflow:wf-old'),
    ]
    assert affected == {5}


@pytest.mark.asyncio
async def test_sync_user_role_change_writes_super_admin_tuple_for_admin_role():
    from bisheng.database.constants import AdminRole
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
    )

    with patch.object(
        LegacyRBACSyncService,
        '_role_access_signatures_for_roles',
        new_callable=AsyncMock,
        return_value=set(),
    ), patch.object(
        LegacyRBACSyncService,
        '_write_operations',
        new_callable=AsyncMock,
    ) as write_ops:
        await LegacyRBACSyncService.sync_user_role_change(1, [], [AdminRole])

    operations, affected = write_ops.await_args_list[0].args
    assert [(op.action, op.user, op.relation, op.object) for op in operations] == [
        ('write', 'user:1', 'super_admin', 'system:global'),
    ]
    assert affected == [1]


@pytest.mark.asyncio
async def test_sync_user_auth_created_writes_group_memberships():
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
    )

    with patch.object(
        LegacyRBACSyncService,
        'sync_user_role_change',
        new_callable=AsyncMock,
    ) as role_sync, patch.object(
        LegacyRBACSyncService,
        '_write_operations',
        new_callable=AsyncMock,
    ) as write_ops:
        await LegacyRBACSyncService.sync_user_auth_created(
            5,
            [2],
            member_group_ids=[7],
            admin_group_ids=[8],
        )

    role_sync.assert_awaited_once_with(5, [], [2])
    operations, affected = write_ops.await_args.args
    assert {(op.action, op.user, op.relation, op.object) for op in operations} == {
        ('write', 'user:5', 'member', 'user_group:7'),
        ('write', 'user:5', 'admin', 'user_group:8'),
    }
    assert affected == [5]


@pytest.mark.asyncio
async def test_group_change_handler_invalidates_direct_user_cache():
    from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
    from bisheng.user_group.domain.services.group_change_handler import GroupChangeHandler

    ops = [
        TupleOperation(action='write', user='user:9', relation='member', object='user_group:3'),
        TupleOperation(action='write', user='user_group:3#member', relation='viewer', object='workflow:wf-1'),
    ]

    with patch(
        'bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples',
        new_callable=AsyncMock,
    ) as batch_write, patch(
        'bisheng.permission.domain.services.permission_cache.PermissionCache.invalidate_user',
        new_callable=AsyncMock,
    ) as invalidate:
        await GroupChangeHandler.execute_async(ops)

    batch_write.assert_awaited_once_with(ops, crash_safe=True)
    invalidate.assert_awaited_once_with(9)
