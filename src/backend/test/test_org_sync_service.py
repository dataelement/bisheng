from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.database.constants import DefaultRole
from bisheng.database.models.group import DefaultGroup
from bisheng.org_sync.domain.schemas.remote_dto import RemoteMemberDTO
from bisheng.org_sync.domain.services.reconciler import ArchiveDept, CreateMember


@pytest.mark.asyncio
async def test_archive_dept_marks_remote_deleted(monkeypatch):
    import bisheng.org_sync.domain.services.org_sync_service as m
    from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService
    from bisheng.tenant.domain.constants import DeletionSource

    dept = SimpleNamespace(
        id=9,
        parent_id=3,
        status='active',
        is_deleted=0,
        last_sync_ts=0,
        external_id='wx-9',
    )
    monkeypatch.setattr(m.time, 'time', lambda: 1713400000)
    monkeypatch.setattr(m.DepartmentDao, 'aupdate', AsyncMock())
    monkeypatch.setattr(m.DepartmentChangeHandler, 'execute_async', AsyncMock())
    monkeypatch.setattr(m.DepartmentDeletionHandler, 'on_deleted', AsyncMock())

    await OrgSyncService._archive_dept(ArchiveDept(local=dept))

    assert dept.status == 'archived'
    assert dept.is_deleted == 1
    assert dept.last_sync_ts == 1713400000
    m.DepartmentDao.aupdate.assert_awaited_once_with(dept)
    m.DepartmentChangeHandler.execute_async.assert_awaited_once()
    m.DepartmentDeletionHandler.on_deleted.assert_awaited_once_with(
        9, DeletionSource.CELERY_RECONCILE,
    )


@pytest.mark.asyncio
async def test_ensure_default_user_group_membership_adds_missing_member(monkeypatch):
    import bisheng.org_sync.domain.services.org_sync_service as m
    from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService

    monkeypatch.setattr(
        m.GroupDao, 'aget_by_id',
        AsyncMock(return_value=SimpleNamespace(id=DefaultGroup)),
    )
    monkeypatch.setattr(
        m.UserGroupDao, 'acheck_members_exist',
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(m.UserGroupDao, 'aadd_members_batch', AsyncMock())
    monkeypatch.setattr(m.GroupChangeHandler, 'execute_async', AsyncMock())

    result = await OrgSyncService._ensure_default_user_group_membership(7)

    assert result == [DefaultGroup]
    m.UserGroupDao.aadd_members_batch.assert_awaited_once_with(DefaultGroup, [7])
    m.GroupChangeHandler.execute_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_member_syncs_default_group_tuple(monkeypatch):
    import bisheng.org_sync.domain.services.org_sync_service as m
    from bisheng.org_sync.domain.services.org_sync_service import OrgSyncService

    created_user = SimpleNamespace(user_id=7)
    monkeypatch.setattr(
        m.UserDao, 'add_user_and_default_role',
        AsyncMock(return_value=created_user),
    )
    monkeypatch.setattr(
        OrgSyncService,
        '_ensure_default_user_group_membership',
        AsyncMock(return_value=[DefaultGroup]),
    )
    monkeypatch.setattr(
        m.LegacyRBACSyncService, 'sync_user_auth_created',
        AsyncMock(),
    )
    monkeypatch.setattr(m.UserTenantDao, 'acreate', AsyncMock())
    monkeypatch.setattr(m.UserDepartmentDao, 'aadd_member', AsyncMock())
    monkeypatch.setattr(m.DepartmentChangeHandler, 'execute_async', AsyncMock())

    remote = RemoteMemberDTO(
        external_id='u-1',
        name='Alice',
        email='a@example.com',
        phone='13800000000',
        primary_dept_external_id='d-1',
    )
    config = SimpleNamespace(provider='wecom', tenant_id=1)

    await OrgSyncService._create_member(
        CreateMember(remote=remote), config, {'d-1': 11},
    )

    m.LegacyRBACSyncService.sync_user_auth_created.assert_awaited_once_with(
        7, [DefaultRole], member_group_ids=[DefaultGroup],
    )
