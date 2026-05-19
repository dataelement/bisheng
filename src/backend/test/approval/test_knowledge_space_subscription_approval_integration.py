from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from test.test_knowledge_space_service import _load_service_class


@pytest.mark.asyncio
async def test_approval_space_subscription_uses_approval_gate_pending():
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        UserRoleEnum,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeTypeEnum

    service = _load_service_class()(None, SimpleNamespace(user_id=42, user_name='alice', tenant_id=7))
    service.message_service = SimpleNamespace(send_generic_approval=AsyncMock())
    service.approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(return_value=SimpleNamespace(decision='pending', instance_id=21))
    )

    space = SimpleNamespace(id=12, name='研发知识空间', type=KnowledgeTypeEnum.SPACE.value, auth_type=AuthTypeEnum.APPROVAL)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_user_space_subscriptions',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_insert_member',
        new_callable=AsyncMock,
    ) as mock_insert:
        result = await service.subscribe_space(12)

    assert result == {'status': 'pending', 'space_id': 12}
    mock_insert.assert_awaited_once()
    inserted = mock_insert.await_args.args[0]
    assert inserted.business_id == '12'
    assert inserted.user_role == UserRoleEnum.MEMBER
    assert inserted.status == MembershipStatusEnum.PENDING
    service.approval_gate.request_or_pass.assert_awaited_once()
    service.message_service.send_generic_approval.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_space_subscription_direct_pass_activates_member():
    from bisheng.common.models.space_channel_member import MembershipStatusEnum
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeTypeEnum

    login_user = SimpleNamespace(user_id=42, user_name='alice', tenant_id=7)
    service = _load_service_class()(None, login_user)
    service.approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(return_value=SimpleNamespace(decision='pass', instance_id=22))
    )
    space = SimpleNamespace(id=12, name='研发知识空间', type=KnowledgeTypeEnum.SPACE.value, auth_type=AuthTypeEnum.APPROVAL)
    membership = SimpleNamespace(id=9, business_id='12', user_id=42, user_role='member', status=MembershipStatusEnum.REJECTED)

    with patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=space,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_find_member',
        new_callable=AsyncMock,
        return_value=membership,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.async_count_user_space_subscriptions',
        new_callable=AsyncMock,
        return_value=0,
    ), patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.SpaceChannelMemberDao.update',
        new_callable=AsyncMock,
        side_effect=lambda row: row,
    ) as mock_update, patch(
        'bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.sync_direct_space_user_permissions',
        new_callable=AsyncMock,
    ) as mock_sync:
        result = await service.subscribe_space(12)

    assert result == {'status': 'subscribed', 'space_id': 12}
    assert membership.status == MembershipStatusEnum.ACTIVE
    mock_update.assert_awaited()
    mock_sync.assert_awaited()


@pytest.mark.asyncio
async def test_knowledge_space_subscribe_scenario_handler_updates_membership_states():
    from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
        KnowledgeSpaceSubscribeScenarioHandler,
    )
    from bisheng.common.models.space_channel_member import MembershipStatusEnum

    membership = SimpleNamespace(id=1, status=MembershipStatusEnum.PENDING, user_id=42, user_role='member')
    handler = KnowledgeSpaceSubscribeScenarioHandler(
        find_member=AsyncMock(return_value=membership),
        update_member=AsyncMock(side_effect=lambda row: row),
        sync_permissions=AsyncMock(),
    )

    payload = {'space_id': 12, 'space_name': '研发知识空间', 'applicant_user_id': 42}
    await handler.on_approved(instance_id=1, payload_snapshot=payload)
    assert membership.status == MembershipStatusEnum.ACTIVE
    handler.sync_permissions.assert_awaited_once()

    membership.status = MembershipStatusEnum.PENDING
    await handler.on_rejected(instance_id=1, payload_snapshot=payload, reason='reject')
    assert membership.status == MembershipStatusEnum.REJECTED
