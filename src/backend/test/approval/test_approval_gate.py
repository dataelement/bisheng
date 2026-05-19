from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
)
from bisheng.approval.domain.models.approval_scenario import ApprovalScenario
from bisheng.approval.domain.models.user_menu_access import UserMenuAccess, UserMenuAccessStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_query_repository import ApprovalQueryRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.repositories.user_menu_access_repository import UserMenuAccessRepository


@pytest_asyncio.fixture
async def approval_db_engine():
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalScenario.__table__,
        ApprovalInstance.__table__,
        ApprovalTask.__table__,
        ApprovalException.__table__,
        UserMenuAccess.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def patched_approval_repositories(approval_db_engine, monkeypatch):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=approval_db_engine) as session:
            yield session

    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session',
        _factory,
    )
    monkeypatch.setattr(
        'bisheng.approval.domain.repositories.user_menu_access_repository.get_async_db_session',
        _factory,
    )
    yield


@pytest.mark.asyncio
async def test_repository_flow_creates_scenario_disabled_exception(patched_approval_repositories):
    scenario = await ApprovalScenarioRepository.create_scenario(
        ApprovalScenario(
            tenant_id=1,
            scenario_code='menu_access_request',
            scenario_name='菜单权限申请',
            enabled=False,
        )
    )
    instance = await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code=scenario.scenario_code,
            scenario_name=scenario.scenario_name,
            handler_key='menu_access',
            business_key='menu:knowledge',
            business_resource_type='web_menu',
            business_resource_id='knowledge',
            business_name='知识管理',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.EXCEPTION,
            payload_snapshot={'menu_key': 'knowledge'},
            detail_snapshot={'menu_name': '知识管理'},
        )
    )
    await ApprovalInstanceRepository.create_exception(
        ApprovalException(
            tenant_id=1,
            instance_id=instance.id,
            exception_type=ApprovalExceptionType.SCENARIO_DISABLED,
            detail={'scenario_code': scenario.scenario_code},
        )
    )

    saved = await ApprovalInstanceRepository.get_instance(instance.id)
    exceptions = await ApprovalInstanceRepository.list_exceptions(instance.id)
    tasks = await ApprovalQueryRepository.list_tasks_by_approver(1, 7)

    assert saved is not None
    assert saved.status == ApprovalInstanceStatus.EXCEPTION
    assert [one.exception_type for one in exceptions] == [ApprovalExceptionType.SCENARIO_DISABLED]
    assert tasks == []


@pytest.mark.asyncio
async def test_repository_returns_existing_duplicate_pending_instance(patched_approval_repositories):
    await ApprovalInstanceRepository.create_instance(
        ApprovalInstance(
            tenant_id=1,
            scenario_code='channel_subscribe_request',
            scenario_name='频道订阅审批',
            handler_key='channel_subscribe',
            business_key='channel:88:user:7',
            business_resource_type='channel',
            business_resource_id='88',
            business_name='资讯频道',
            applicant_user_id=7,
            applicant_user_name='alice',
            status=ApprovalInstanceStatus.PENDING,
            payload_snapshot={'channel_id': 88},
            detail_snapshot={'channel_name': '资讯频道'},
        )
    )

    duplicate = await ApprovalInstanceRepository.find_duplicate_active_instance(
        tenant_id=1,
        scenario_code='channel_subscribe_request',
        business_key='channel:88:user:7',
        applicant_user_id=7,
    )

    assert duplicate is not None
    assert duplicate.status == ApprovalInstanceStatus.PENDING


@pytest.mark.asyncio
async def test_user_menu_access_repository_lists_active_grants(patched_approval_repositories):
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=9,
        menu_key='workstation',
        menu_name='工作台',
        grant_source='approval_instance',
        grant_instance_id=11,
    )
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=9,
        menu_key='home',
        menu_name='首页',
        grant_source='approval_instance',
        grant_instance_id=11,
    )
    await UserMenuAccessRepository.upsert_active_grant(
        tenant_id=1,
        user_id=10,
        menu_key='apps',
        menu_name='应用中心',
        grant_source='approval_instance',
        grant_instance_id=12,
    )
    await UserMenuAccessRepository.revoke_grant(
        tenant_id=1,
        user_id=9,
        menu_key='workstation',
        grant_source='approval_instance',
        revoked_by_user_id=1,
        revoked_reason='manual revoke',
    )

    user9_keys = await UserMenuAccessRepository.list_active_menu_keys(1, 9)
    user10_keys = await UserMenuAccessRepository.list_active_menu_keys(1, 10)
    revoked = await UserMenuAccessRepository.get_active_grant(1, 9, 'workstation')

    assert user9_keys == ['home']
    assert user10_keys == ['apps']
    assert revoked is None
