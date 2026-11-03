from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.approval.application import request_state
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.common.errcode.approval import ApprovalExecutionFailedError
from test.knowledge.test_square_revoked_membership import Membership, Status
from test.knowledge.test_square_revoked_membership import context as context


@pytest.mark.parametrize("failed", [False, True])
async def test_info_and_square_show_pending_only_for_a_real_waiting_request(context, monkeypatch, failed):
    context.member.status = Membership.PENDING
    context.member.is_active = False
    context.member.is_pending = True
    context.namespace["KnowledgeDao"].async_get_public_spaces_paginated.return_value = [
        (context.space, Membership.PENDING, None, 2)
    ]
    lookup = AsyncMock(return_value=frozenset({"space:74:user:7"}) if failed else frozenset())
    monkeypatch.setattr(request_state, "get_failed_request_keys", lookup)
    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()
    expected = Status.NOT_SUBSCRIBED if failed else Status.PENDING
    assert info.subscription_status == square["data"][0].subscription_status == expected
    assert info.is_pending == square["data"][0].is_pending == (not failed)
    assert info.is_followed is False and info.actions == []


async def test_visible_space_keeps_work120_display_semantics_without_extra_lookup(context, monkeypatch):
    context.member.status = Membership.PENDING
    context.member.is_active = False
    context.member.is_pending = True
    context.service._require_space_info_permission.return_value = (context.space, True)
    context.service._has_joined_visibility.return_value = True
    context.namespace["batch_check_business_visible"].return_value = {"74": True}
    context.namespace["KnowledgeDao"].async_get_public_spaces_paginated.return_value = [
        (context.space, Membership.PENDING, None, 2)
    ]
    lookup = AsyncMock(side_effect=AssertionError("visible space must not query failed requests"))
    monkeypatch.setattr(request_state, "get_failed_request_keys", lookup)
    info = await context.service.get_space_info(74)
    square = await context.service.get_knowledge_square()
    assert info.subscription_status == square["data"][0].subscription_status == Status.PENDING
    lookup.assert_not_awaited()


async def test_retry_of_failed_request_does_not_persist_phantom_membership(context):
    context.member.status = Membership.PENDING
    context.service.approval_gate = ApprovalGate(
        registry=SimpleNamespace(get_handler=AsyncMock()),
        instance_repository=SimpleNamespace(
            find_duplicate_active_instance=AsyncMock(return_value=SimpleNamespace(id=16, status="execute_failed"))
        ),
    )
    with pytest.raises(ApprovalExecutionFailedError):
        await context.service.subscribe_space(74)
    context.service._persist_space_member.assert_not_awaited()
    context.service.sync_direct_space_user_permissions.assert_not_awaited()
