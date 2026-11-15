"""Existing dismissal permissions and notifications through real SQL/R2 writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.services import channel_service as module
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


def notifications(context):
    message = SimpleNamespace(send_generic_notify=AsyncMock())
    context.service.message_service = message
    context.service._send_channel_event_notification = ChannelService._send_channel_event_notification.__get__(
        context.service
    )
    return message


async def test_dismiss_channel_notifies_active_members(business):
    business.user = UserPayload(user_id=693, user_name="yangxin", tenant_id=101, user_role=[])
    root = await fixtures.create(business, sync=fixtures.config())
    message = notifications(business)
    await business.service.dismiss_channel(root.id, business.user)
    message.send_generic_notify.assert_awaited_once()
    kwargs = message.send_generic_notify.await_args.kwargs
    assert kwargs["action_code"] == "channel_dismissed" and kwargs["receiver_user_ids"] == [693]
    assert not any(row["business_id"] == root.id for row in (await fixtures.state(business))["space_channel_member"])


async def test_dismiss_allowed_for_non_creator_with_delete_channel_permission(business, monkeypatch):
    root = await fixtures.create(business)
    async with business.sessions() as session, session.begin():
        session.add(SpaceChannelMember(business_id=root.id, business_type="channel", user_id=693, user_role="admin"))
    actor = UserPayload(user_id=693, tenant_id=101, user_role=[])
    check = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", check)
    await business.service.dismiss_channel(root.id, actor)
    assert check.await_count == 2  # candidate and locked current reauthorization
    assert all(call.args[0] is actor and call.kwargs["action"] == "delete" for call in check.await_args_list)
    business.adapter.project_delete.assert_awaited_once()
    assert not any(row["id"] == root.id for row in (await fixtures.state(business))["channel"])
    assert not any(row["business_id"] == root.id for row in (await fixtures.state(business))["space_channel_member"])


async def test_dismiss_allowed_for_super_admin_without_delete_channel_permission(business, monkeypatch):
    root = await fixtures.create(business)
    actor = UserPayload(user_id=693, tenant_id=101, user_role=[], is_global_super=True)
    check = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", check)
    await business.service.dismiss_channel(root.id, actor)
    assert check.await_count == 2 and all(call.args[0] is actor for call in check.await_args_list)
    business.adapter.project_delete.assert_awaited_once()
    state = await fixtures.state(business)
    assert not any(row["id"] == root.id for row in state["channel"])
    assert not any(row["business_id"] == root.id for row in state["space_channel_member"])


async def test_dismiss_denied_for_non_creator_without_delete_channel_permission(business, monkeypatch):
    root = await fixtures.create(business)
    before = await fixtures.state(business)
    monkeypatch.setattr(module, "require_business_action", AsyncMock(side_effect=ChannelPermissionDeniedError()))
    with pytest.raises(ChannelPermissionDeniedError):
        await business.service.dismiss_channel(root.id, business.user)
    assert await fixtures.state(business) == before
    business.adapter.load_permission_record.assert_not_awaited()
    business.adapter.project_delete.assert_not_awaited()
