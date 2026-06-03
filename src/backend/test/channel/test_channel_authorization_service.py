from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeRequest,
    ChannelGrantItem,
    ChannelRevokeItem,
)
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
    ChannelAuthorizationSyncError,
)
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import ChannelRelationEnum


class _User:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return False


class _ChannelRepo:
    async def find_by_id(self, channel_id: str):
        return type('Channel', (), {'id': channel_id, 'tenant_id': 1})()


class _MemberRepo:
    def __init__(self, relation: ChannelRelationEnum):
        self.relation = relation
        self.deleted_binding_keys = []

    async def get_effective_channel_relation(self, channel_id: str, user_id: int):
        return self.relation

    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str):
        self.deleted_binding_keys.append((channel_id, grant_binding_key))
        return 1


class _SyncService:
    def __init__(self):
        self.grants = []
        self.revokes = []

    async def sync_grant(self, **kwargs):
        self.grants.append(kwargs)
        return [kwargs['grant'].subject_id]

    async def sync_revoke(self, **kwargs):
        self.revokes.append(kwargs)
        return 0


def _service(actor_relation: ChannelRelationEnum, sync_service=None) -> ChannelAuthorizationService:
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(actor_relation),
        membership_sync_service=sync_service or _SyncService(),
    )
    service._validate_subjects_belong_to_channel_tenant = AsyncMock(return_value=None)
    service._get_bindings = AsyncMock(return_value=[])
    service._save_bindings = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_owner_grant_writes_permission_tuple_without_membership_sync():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.OWNER),
        ChannelGrantItem(subject_type='user', subject_id=12, relation=ChannelRelationEnum.MANAGER),
        ChannelGrantItem(subject_type='user', subject_id=13, relation=ChannelRelationEnum.EDITOR),
        ChannelGrantItem(subject_type='user', subject_id=14, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch.object(
        service,
        '_save_binding_changes',
        new_callable=AsyncMock,
    ):
        result = await service.authorize_channel('channel-1', request, _User())

    assert mock_authorize.await_count == 1
    assert len(mock_authorize.await_args.kwargs['grants']) == 4
    assert result.synced_user_count == 0
    assert result.affected_member_count == 0
    assert sync_service.grants == []


@pytest.mark.asyncio
async def test_authorize_channel_dispatches_permission_notifications_after_sync():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.MANAGER),
    ])
    notify_context = object()

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ), patch(
        'bisheng.channel.domain.services.channel_authorization_service.'
        'ResourcePermissionNotificationService.build_context',
        new_callable=AsyncMock,
        return_value=notify_context,
    ) as mock_build_context, patch(
        'bisheng.channel.domain.services.channel_authorization_service.'
        'ResourcePermissionNotificationService.dispatch_after_authorize',
        new_callable=AsyncMock,
    ) as mock_dispatch:
        await service.authorize_channel('channel-1', request, _User())

    assert mock_build_context.await_args.kwargs['resource_type'] == 'channel'
    assert mock_build_context.await_args.kwargs['resource_id'] == 'channel-1'
    assert mock_build_context.await_args.kwargs['grants'][0].relation == 'manager'
    assert mock_dispatch.await_args.kwargs == {
        'context': notify_context,
        'operator_user_id': _User.user_id,
        'operator_user_name': getattr(_User, 'user_name', None),
    }


@pytest.mark.asyncio
async def test_owner_cannot_grant_organization_owner():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='department', subject_id=11, relation=ChannelRelationEnum.OWNER),
    ])

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel('channel-1', request, _User())


@pytest.mark.asyncio
async def test_owner_cannot_grant_user_group_owner():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user_group', subject_id=11, relation=ChannelRelationEnum.OWNER),
    ])

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel('channel-1', request, _User())


@pytest.mark.asyncio
async def test_manager_can_only_grant_usage_relations():
    service = _service(ChannelRelationEnum.MANAGER)
    allowed = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.EDITOR),
        ChannelGrantItem(subject_type='user', subject_id=12, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_save_binding_changes',
        new_callable=AsyncMock,
    ):
        await service.authorize_channel('channel-1', allowed, _User())

    denied = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=13, relation=ChannelRelationEnum.MANAGER),
    ])
    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel('channel-1', denied, _User())


@pytest.mark.asyncio
async def test_editor_viewer_cannot_authorize():
    service = _service(ChannelRelationEnum.EDITOR)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel('channel-1', request, _User())


@pytest.mark.asyncio
async def test_fga_failure_does_not_sync_membership():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
        side_effect=RuntimeError('fga down'),
    ):
        with pytest.raises(RuntimeError, match='fga down'):
            await service.authorize_channel('channel-1', request, _User())

    assert sync_service.grants == []


@pytest.mark.asyncio
async def test_membership_sync_service_is_not_called_for_permission_grants():
    class FailingSync(_SyncService):
        async def sync_grant(self, **kwargs):
            self.grants.append(kwargs)
            raise RuntimeError('sync failed')

    sync_service = FailingSync()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch.object(
        service,
        '_get_bindings',
        new_callable=AsyncMock,
        return_value=[{'key': 'existing', 'resource_type': 'channel'}],
        ), patch.object(
            service,
            '_save_bindings',
            new_callable=AsyncMock,
        ):
            result = await service.authorize_channel('channel-1', request, _User())

    assert mock_authorize.await_count == 1
    assert result.synced_user_count == 0
    assert result.affected_member_count == 0
    assert sync_service.grants == []
    assert service.space_channel_member_repository.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_binding_failure_compensates_fga_before_membership_sync():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch.object(
        service,
        '_save_binding_changes_from_snapshot',
        new_callable=AsyncMock,
        side_effect=RuntimeError('binding failed'),
    ):
        with pytest.raises(ChannelAuthorizationSyncError):
            await service.authorize_channel('channel-1', request, _User())

    assert sync_service.grants == []
    assert service.space_channel_member_repository.deleted_binding_keys == []
    assert mock_authorize.await_count == 2
    assert mock_authorize.await_args_list[1].kwargs['revokes'][0].subject_id == 11


_FINE_GRAINED_PERMISSIONS = (
    'bisheng.channel.domain.services.channel_authorization_service'
    '.FineGrainedPermissionService.get_effective_permission_ids_async'
)


@pytest.mark.asyncio
async def test_grantable_models_excludes_owner_without_manage_channel_owner():
    # Role carries delete + manage_manager + manage_user but NOT manage_channel_owner.
    service = _service(ChannelRelationEnum.OWNER)
    service._get_relation_models = AsyncMock(
        return_value=ChannelAuthorizationService._default_relation_models()
    )
    effective = {
        'view_channel',
        'edit_channel',
        'delete_channel',
        'manage_channel_manager',
        'manage_channel_user',
    }

    with patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective):
        models = await service.grantable_relation_models('channel-1', _User())

    relations = {m.relation.value for m in models}
    assert 'owner' not in relations
    assert {'manager', 'editor', 'viewer'} <= relations


@pytest.mark.asyncio
async def test_authorize_denied_owner_grant_without_manage_channel_owner():
    service = _service(ChannelRelationEnum.OWNER)
    effective = {'delete_channel', 'manage_channel_manager', 'manage_channel_user'}
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.OWNER),
    ])

    with patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective), patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.authorize_channel('channel-1', request, _User())

    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_allows_manager_grant_with_manage_channel_manager():
    service = _service(ChannelRelationEnum.OWNER)
    effective = {'manage_channel_manager', 'manage_channel_user'}
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.MANAGER),
    ])

    with patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective), patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch.object(
        service,
        '_save_binding_changes_from_snapshot',
        new_callable=AsyncMock,
    ):
        await service.authorize_channel('channel-1', request, _User())

    mock_authorize.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_non_owner_bindings_keeps_owner_and_other_resources():
    bindings = [
        {'key': 'k1', 'resource_type': 'channel', 'resource_id': 'channel-1', 'relation': 'owner'},
        {'key': 'k2', 'resource_type': 'channel', 'resource_id': 'channel-1', 'relation': 'manager'},
        {'key': 'k3', 'resource_type': 'channel', 'resource_id': 'channel-1', 'relation': 'viewer'},
        {'key': 'k4', 'resource_type': 'channel', 'resource_id': 'channel-2', 'relation': 'viewer'},
        {'key': 'k5', 'resource_type': 'knowledge_space', 'resource_id': 'channel-1', 'relation': 'viewer'},
    ]
    saved: dict = {}

    async def _fake_save(new_bindings):
        saved['value'] = new_bindings

    with patch.object(
        ChannelAuthorizationService, '_get_bindings', new_callable=AsyncMock, return_value=bindings,
    ), patch.object(
        ChannelAuthorizationService, '_save_bindings', new=_fake_save,
    ):
        removed = await ChannelAuthorizationService.clear_non_owner_bindings('channel-1')

    assert removed == 2
    remaining_keys = {b['key'] for b in saved['value']}
    assert remaining_keys == {'k1', 'k4', 'k5'}


@pytest.mark.asyncio
async def test_clear_non_owner_bindings_noop_when_nothing_to_remove():
    bindings = [
        {'key': 'k1', 'resource_type': 'channel', 'resource_id': 'channel-1', 'relation': 'owner'},
    ]
    with patch.object(
        ChannelAuthorizationService, '_get_bindings', new_callable=AsyncMock, return_value=bindings,
    ), patch.object(
        ChannelAuthorizationService, '_save_bindings', new_callable=AsyncMock,
    ) as mock_save:
        removed = await ChannelAuthorizationService.clear_non_owner_bindings('channel-1')

    assert removed == 0
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_subject_validation_rejects_before_fga_write():
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(ChannelRelationEnum.OWNER),
        membership_sync_service=_SyncService(),
    )
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch.object(
        service,
        '_users_belong_to_tenant',
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.authorize_channel('channel-1', request, _User())

    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_revoke_is_allowed_for_cleanup():
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(ChannelRelationEnum.OWNER),
        membership_sync_service=_SyncService(),
    )
    request = ChannelAuthorizeRequest(revokes=[
        ChannelRevokeItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER),
    ])

    with patch.object(
        service,
        '_users_belong_to_tenant',
        new_callable=AsyncMock,
        return_value=False,
    ) as mock_users_belong_to_tenant, patch(
        'bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize',
        new_callable=AsyncMock,
    ) as mock_authorize, patch.object(
        service,
        '_save_binding_changes_from_snapshot',
        new_callable=AsyncMock,
    ), patch.object(
        service,
        '_get_bindings',
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        service,
        '_save_bindings',
        new_callable=AsyncMock,
    ):
        await service.authorize_channel('channel-1', request, _User())

    mock_users_belong_to_tenant.assert_not_awaited()
    mock_authorize.assert_awaited_once()
