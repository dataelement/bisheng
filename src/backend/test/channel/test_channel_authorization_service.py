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
async def test_owner_can_grant_user_owner_manager_editor_viewer():
    service = _service(ChannelRelationEnum.OWNER)
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
    assert result.synced_user_count == 4


@pytest.mark.asyncio
async def test_owner_cannot_grant_organization_owner():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(grants=[
        ChannelGrantItem(subject_type='department', subject_id=11, relation=ChannelRelationEnum.OWNER),
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
async def test_membership_sync_failure_compensates_fga_grant_and_cleans_source():
    class FailingSync(_SyncService):
        async def sync_grant(self, **kwargs):
            self.grants.append(kwargs)
            raise RuntimeError('sync failed')

    service = _service(ChannelRelationEnum.OWNER, FailingSync())
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
    ) as mock_save_bindings:
        with pytest.raises(ChannelAuthorizationSyncError):
            await service.authorize_channel('channel-1', request, _User())

    assert mock_authorize.await_count == 2
    compensation_call = mock_authorize.await_args_list[1].kwargs
    assert compensation_call['grants'] == []
    assert compensation_call['revokes'][0].subject_id == 11
    assert service.space_channel_member_repository.deleted_binding_keys == [
        ('channel-1', 'channel:channel-1:user:11:viewer:-'),
    ]
    assert mock_save_bindings.await_args_list[-1].args[0] == [{'key': 'existing', 'resource_type': 'channel'}]


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
