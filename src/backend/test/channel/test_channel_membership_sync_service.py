from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.schemas.channel_authorization_schema import ChannelGrantItem
from bisheng.channel.domain.services.channel_membership_sync_service import (
    ChannelMembershipSyncService,
)
from bisheng.common.models.space_channel_member import ChannelRelationEnum


class _Repo:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.stale_deletes = []

    async def upsert_channel_membership_source(self, **kwargs):
        self.upserts.append(kwargs)
        return kwargs

    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str):
        self.deletes.append((channel_id, grant_binding_key))
        return 1

    async def delete_channel_membership_source_users_not_in(
        self,
        channel_id: str,
        grant_binding_key: str,
        user_ids: list[int],
    ):
        self.stale_deletes.append((channel_id, grant_binding_key, user_ids))
        return 1


@pytest.mark.asyncio
async def test_user_grant_syncs_single_user():
    repo = _Repo()
    service = ChannelMembershipSyncService(repo)
    grant = ChannelGrantItem(subject_type='user', subject_id=11, relation=ChannelRelationEnum.VIEWER)

    affected = await service.sync_grant(channel_id='channel-1', grant=grant, binding_key='user-viewer')

    assert affected == [11]
    assert repo.upserts[0]['user_id'] == 11
    assert repo.upserts[0]['grant_subject_type'] == 'user'


@pytest.mark.asyncio
async def test_department_grant_without_children_syncs_direct_members():
    repo = _Repo()
    service = ChannelMembershipSyncService(repo)
    grant = ChannelGrantItem(
        subject_type='department',
        subject_id=100,
        relation=ChannelRelationEnum.VIEWER,
        include_children=False,
    )

    with patch(
        'bisheng.channel.domain.services.channel_membership_sync_service.UserDepartmentDao.aget_user_ids_by_department',
        new_callable=AsyncMock,
        return_value=[1, 2],
    ):
        affected = await service.sync_grant(channel_id='channel-1', grant=grant, binding_key='dept-viewer')

    assert affected == [1, 2]
    assert [row['user_id'] for row in repo.upserts] == [1, 2]


@pytest.mark.asyncio
async def test_department_grant_with_children_syncs_subtree_members():
    repo = _Repo()
    service = ChannelMembershipSyncService(repo)
    grant = ChannelGrantItem(
        subject_type='department',
        subject_id=100,
        relation=ChannelRelationEnum.VIEWER,
        include_children=True,
    )
    dept = type('Dept', (), {'path': '/100/'})()

    with patch(
        'bisheng.channel.domain.services.channel_membership_sync_service.DepartmentDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=dept,
    ), patch(
        'bisheng.channel.domain.services.channel_membership_sync_service.DepartmentDao.aget_subtree_ids',
        new_callable=AsyncMock,
        return_value=[100, 101],
    ), patch(
        'bisheng.channel.domain.services.channel_membership_sync_service.UserDepartmentDao.aget_user_ids_by_department',
        new_callable=AsyncMock,
        side_effect=[[1, 2], [2, 3]],
    ):
        affected = await service.sync_grant(channel_id='channel-1', grant=grant, binding_key='dept-tree-viewer')

    assert affected == [1, 2, 3]


@pytest.mark.asyncio
async def test_user_group_grant_syncs_group_members():
    repo = _Repo()
    service = ChannelMembershipSyncService(repo)
    grant = ChannelGrantItem(subject_type='user_group', subject_id=200, relation=ChannelRelationEnum.EDITOR)

    with patch(
        'bisheng.channel.domain.services.channel_membership_sync_service.UserGroupDao.aget_plain_member_user_ids',
        new_callable=AsyncMock,
        return_value=[5, 6],
    ):
        affected = await service.sync_grant(channel_id='channel-1', grant=grant, binding_key='group-editor')

    assert affected == [5, 6]
    assert all(row['relation'] == ChannelRelationEnum.EDITOR for row in repo.upserts)
    assert repo.stale_deletes == [('channel-1', 'group-editor', [5, 6])]


@pytest.mark.asyncio
async def test_revoke_deletes_binding_source():
    repo = _Repo()
    service = ChannelMembershipSyncService(repo)

    deleted = await service.sync_revoke(channel_id='channel-1', binding_key='group-editor')

    assert deleted == 1
    assert repo.deletes == [('channel-1', 'group-editor')]
