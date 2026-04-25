from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_rbac_migrator_run_prefers_async_fga_accessor(tmp_path):
    from bisheng.permission.migration.migrate_rbac_to_rebac import RBACToReBACMigrator

    fake_fga = AsyncMock()
    migrator = RBACToReBACMigrator(dry_run=True, checkpoint_dir=str(tmp_path))

    with patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=fake_fga,
    ) as async_get_fga, patch(
        'bisheng.core.openfga.manager.get_fga_client',
        return_value=None,
    ), patch.object(
        RBACToReBACMigrator,
        'step1_super_admin',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step2_user_group_membership',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step3_role_access',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step4_space_channel_members',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step5_resource_owners',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step6_folder_hierarchy',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step7_department_membership',
        new_callable=AsyncMock,
        return_value=0,
    ), patch.object(
        RBACToReBACMigrator,
        'step8_group_resources',
        new_callable=AsyncMock,
        return_value=0,
    ):
        await migrator.run()

    async_get_fga.assert_awaited_once()
    assert migrator._fga is fake_fga


@pytest.mark.asyncio
async def test_init_data_migration_probe_prefers_async_fga_accessor():
    from bisheng.common.init_data import _migrate_rbac_to_rebac_if_needed

    fake_fga = AsyncMock()
    fake_redis = SimpleNamespace(
        aget=AsyncMock(return_value=None),
        asetNx=AsyncMock(return_value=True),
        aset=AsyncMock(),
        adelete=AsyncMock(),
    )
    fake_stats = SimpleNamespace(total=0, to_dict=lambda: {})
    fake_migrator = SimpleNamespace(run=AsyncMock(return_value=fake_stats))

    with patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=fake_fga,
    ) as async_get_fga, patch(
        'bisheng.core.openfga.manager.get_fga_client',
        return_value=None,
    ) as sync_get_fga, patch(
        'bisheng.common.init_data.get_redis_client',
        new_callable=AsyncMock,
        return_value=fake_redis,
    ), patch(
        'bisheng.permission.migration.migrate_rbac_to_rebac.RBACToReBACMigrator',
        return_value=fake_migrator,
    ):
        await _migrate_rbac_to_rebac_if_needed()

    async_get_fga.assert_awaited_once()
    sync_get_fga.assert_not_called()
    fake_migrator.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_mount_cleanup_prefers_async_fga_accessor():
    from bisheng.tenant.domain.services.tenant_mount_service import TenantMountService

    fake_fga = AsyncMock()
    fake_fga.read_tuples = AsyncMock(side_effect=[
        [{'user': 'tenant:9', 'relation': 'admin', 'object': 'tenant:9'}],
        [{'user': 'tenant:9', 'relation': 'shared_to', 'object': 'tenant:1'}],
    ])
    fake_fga.write_tuples = AsyncMock()

    with patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=fake_fga,
    ) as async_get_fga, patch(
        'bisheng.core.openfga.manager.get_fga_client',
        return_value=None,
    ) as sync_get_fga, patch(
        'bisheng.tenant.domain.services.resource_share_service.ResourceShareService.revoke_from_child',
        new_callable=AsyncMock,
    ) as revoke_from_child:
        await TenantMountService._on_child_unmounted(9)

    revoke_from_child.assert_awaited_once_with(9, root_tenant_id=1)
    async_get_fga.assert_awaited_once()
    sync_get_fga.assert_not_called()
    fake_fga.write_tuples.assert_awaited_once_with(deletes=[
        {'user': 'tenant:9', 'relation': 'admin', 'object': 'tenant:9'},
        {'user': 'tenant:9', 'relation': 'shared_to', 'object': 'tenant:1'},
    ])
