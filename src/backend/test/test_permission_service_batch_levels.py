import pytest
from unittest.mock import AsyncMock, patch

from bisheng.permission.domain.services.permission_service import PermissionService, PermissionLevel


def _fake_login_user(user_id=7, is_admin=False):
    class _U:
        def __init__(self):
            self.user_id = user_id
        def is_admin(self):
            return is_admin
    return _U()


@pytest.mark.asyncio
async def test_get_permission_levels_matches_single_calls():
    login_user = _fake_login_user()
    object_ids = ['1', '2', '3']

    # object 1 -> owner True; object 2 -> can_read True; object 3 -> all False
    def _single_batch_check(checks):
        # checks: 4 rows for one object (owner, can_manage, can_edit, can_read)
        obj = checks[0]['object']
        table = {
            'knowledge_space:1': [True, False, False, False],
            'knowledge_space:2': [False, False, False, True],
            'knowledge_space:3': [False, False, False, False],
        }
        return table[obj]

    fga = AsyncMock()
    fga.batch_check.side_effect = lambda checks: _single_batch_check(checks)

    with patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga), \
         patch.object(PermissionService, '_evaluate_tenant_gate', new_callable=AsyncMock, return_value=(False, None)), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        singles = {}
        for oid in object_ids:
            singles[oid] = await PermissionService.get_permission_level(
                user_id=login_user.user_id, object_type='knowledge_space', object_id=oid, login_user=login_user)

    # For the batch call, batch_check receives 4*N rows in one shot.
    def _merged_batch_check(checks):
        out = []
        # group by object, preserve level order per object
        by_obj = {}
        for c in checks:
            by_obj.setdefault(c['object'], []).append(c)
        for c in checks:
            table = {
                'knowledge_space:1': {'owner': True},
                'knowledge_space:2': {'can_read': True},
                'knowledge_space:3': {},
            }
            out.append(table[c['object']].get(c['relation'], False))
        return out

    fga2 = AsyncMock()
    fga2.batch_check.side_effect = lambda checks: _merged_batch_check(checks)
    with patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga2), \
         patch.object(PermissionService, '_evaluate_tenant_gate', new_callable=AsyncMock, return_value=(False, None)), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        batched = await PermissionService.get_permission_levels(
            user_id=login_user.user_id, object_type='knowledge_space', object_ids=object_ids, login_user=login_user)

    assert batched == singles
    assert batched == {'1': 'owner', '2': 'can_read', '3': None}
    # a single merged batch_check call, not one-per-object
    assert fga2.batch_check.await_count == 1


@pytest.mark.asyncio
async def test_get_permission_levels_admin_shortcut():
    login_user = _fake_login_user(is_admin=True)
    result = await PermissionService.get_permission_levels(
        user_id=login_user.user_id, object_type='knowledge_space', object_ids=['1', '2'], login_user=login_user)
    assert result == {'1': PermissionLevel.owner.value, '2': PermissionLevel.owner.value}


@pytest.mark.asyncio
async def test_get_permission_levels_tenant_gate_denied_and_shortcut():
    login_user = _fake_login_user()

    async def _gate(user_id, object_type, object_id, login_user=None):
        if object_id == '1':
            return True, None           # denied -> None
        if object_id == '2':
            return False, 'owner'       # shortcut -> owner
        return False, None

    fga = AsyncMock()
    fga.batch_check.side_effect = lambda checks: [False, False, False, False]
    with patch.object(PermissionService, '_evaluate_tenant_gate', side_effect=_gate), \
         patch.object(PermissionService, '_aget_fga', new_callable=AsyncMock, return_value=fga), \
         patch.object(PermissionService, '_legacy_alias_object_types', new_callable=AsyncMock, return_value=[]), \
         patch.object(PermissionService, '_get_implicit_permission_level_after_gate', new_callable=AsyncMock, return_value=None):
        result = await PermissionService.get_permission_levels(
            user_id=login_user.user_id, object_type='knowledge_space', object_ids=['1', '2', '3'], login_user=login_user)
    assert result == {'1': None, '2': 'owner', '3': None}
