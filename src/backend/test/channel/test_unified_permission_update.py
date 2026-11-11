"""F050 settings save/permission/member order with the real F118 SQL unit."""

from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.repositories.reference_binding_repository import ChannelReferenceBindingRepository
from bisheng.channel.domain.schemas.channel_manager_schema import UpdateChannelRequest
from bisheng.channel.domain.services import channel_service as service_module
from bisheng.common.models.space_channel_member import SpaceChannelMember
from test.knowledge_unification import test_ch_bindings as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business


async def test_business_save_failure_does_not_touch_grants_or_memberships(business, monkeypatch):
    root = await fixtures.create(business)
    before = await fixtures.state(business)
    lookup = AsyncMock()
    monkeypatch.setattr(service_module, "get_f048_resource_adapter", lookup)
    monkeypatch.setattr(ChannelReferenceBindingRepository, "asave", AsyncMock(side_effect=RuntimeError("save failed")))
    with pytest.raises(RuntimeError, match="save failed"):
        await business.service.update_channel(root.id, UpdateChannelRequest(visibility="private"), business.user)
    lookup.assert_not_awaited()
    assert await fixtures.state(business) == before


async def test_private_projection_commits_before_membership_cleanup(business, monkeypatch):
    root = await fixtures.create(business)
    async with business.sessions() as session, session.begin():
        session.add(SpaceChannelMember(business_id=root.id, business_type="channel", user_id=8, user_role="member"))
    order = []
    original_save = ChannelReferenceBindingRepository.asave
    original_members = ChannelReferenceBindingRepository.amutate_members

    async def save(repo, session, row):
        order.append("business")
        return await original_save(repo, session, row)

    async def members(repo, session, row, **kwargs):
        order.append("membership")
        return await original_members(repo, session, row, **kwargs)

    business.adapter.remove_ordinary_sources.side_effect = lambda **_: order.append("permission")
    monkeypatch.setattr(ChannelReferenceBindingRepository, "asave", save)
    monkeypatch.setattr(ChannelReferenceBindingRepository, "amutate_members", members)
    result = await business.service.update_channel(root.id, UpdateChannelRequest(visibility="private"), business.user)
    assert result.visibility.value == "private"
    assert order == ["business", "permission", "membership"]
    rows = (await fixtures.state(business))["space_channel_member"]
    assert {row["user_id"] for row in rows if row["business_id"] == root.id} == {7}


async def test_private_projection_failure_preserves_membership_rows(business):
    root = await fixtures.create(business)
    async with business.sessions() as session, session.begin():
        session.add(SpaceChannelMember(business_id=root.id, business_type="channel", user_id=8, user_role="member"))
    before = await fixtures.state(business)
    business.adapter.remove_ordinary_sources.side_effect = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await business.service.update_channel(root.id, UpdateChannelRequest(visibility="private"), business.user)
    assert await fixtures.state(business) == before
