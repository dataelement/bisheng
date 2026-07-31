from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.permission.domain.services.owner_service import OwnerService


_PERM_SVC = 'bisheng.permission.domain.services.permission_service.PermissionService'


@pytest.mark.asyncio
async def test_delete_user_group_resource_tuples_deletes_all_identity_rows():
    fga = MagicMock()
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:1', 'relation': 'member', 'object': 'user_group:3'},
        {'user': 'user:2', 'relation': 'admin', 'object': 'user_group:3'},
    ])
    with patch(f'{_PERM_SVC}._get_fga', return_value=fga), patch(
        f'{_PERM_SVC}.batch_write_tuples', new_callable=AsyncMock,
    ) as mock_batch:
        await OwnerService.delete_resource_tuples('user_group', '3')

    mock_batch.assert_awaited_once()
    ops = mock_batch.await_args.args[0]
    assert {op.user for op in ops} == {'user:1', 'user:2'}
    assert all(op.action == 'delete' for op in ops)


@pytest.mark.asyncio
async def test_legacy_owner_cleanup_rejects_business_resources():
    with pytest.raises(RuntimeError, match='identity-only'):
        await OwnerService.delete_resource_tuples('channel', 'c1')
