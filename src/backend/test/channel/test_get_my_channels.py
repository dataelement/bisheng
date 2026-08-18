"""F051 — get_my_channels (created / followed branches) and set_channel_pin.

The list endpoint no longer returns unread counts or F048 actions, reads pin state
from the decoupled channel_user_pin table, sources "created" straight from the
channel table by user_id, and derives "followed" from the F048-visible subset minus
the user's own created channels. set_channel_pin gates on the concrete visible action.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bisheng.channel.domain.services.channel_service as mod
from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import (
    MyChannelQueryRequest,
    QueryTypeEnum,
    SetPinRequest,
    SortByEnum,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.models.space_channel_member import ChannelRelationEnum, UserRoleEnum


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _channel(cid: str, name: str, user_id: int, *, create_time=None):
    return SimpleNamespace(
        id=cid,
        name=name,
        user_id=user_id,
        source_list=[],
        visibility=ChannelVisibilityEnum.PUBLIC,
        is_released=True,
        latest_article_update_time=None,
        create_time=create_time or datetime(2024, 1, 1),
    )


def _membership(business_id: str, *, create_time=None):
    return SimpleNamespace(
        business_id=business_id,
        create_time=create_time or datetime(2024, 2, 2),
        relation=ChannelRelationEnum.VIEWER,
        user_role=UserRoleEnum.MEMBER,
        grant_subject_type=None,
    )


def _service(*, channel_repo=None, member_repo=None):
    return ChannelService(
        channel_repository=SimpleNamespace(**(channel_repo or {})),
        space_channel_member_repository=SimpleNamespace(**(member_repo or {})),
        channel_info_source_repository=SimpleNamespace(),
    )


def _stub_pin_dao(monkeypatch, pinned: set[str]):
    monkeypatch.setattr(
        mod,
        "ChannelUserPinDao",
        SimpleNamespace(
            list_pinned_channel_ids=AsyncMock(return_value=pinned),
            pin=AsyncMock(),
            unpin=AsyncMock(),
        ),
    )
    return mod.ChannelUserPinDao


# ─────────────────────────── created branch ───────────────────────────

async def test_created_reads_channel_table_no_actions_no_unread(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned={"c2"})
    channels = [_channel("c1", "A", user_id=1), _channel("c2", "B", user_id=1)]
    service = _service(channel_repo={"find_channels_by_user_id": _async(channels)})

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.CREATED, sort_by=SortByEnum.CHANNEL_NAME),
        SimpleNamespace(user_id=1),
    )

    assert {item.id for item in result} == {"c1", "c2"}
    for item in result:
        assert item.actions == []  # no F048 actions on the list — lazy via detail
        assert item.user_role == UserRoleEnum.CREATOR.value
        assert item.relation == ChannelRelationEnum.OWNER.value
        assert item.subscribed_at == item.create_time  # created "added" time == creation
        assert "unread_count" not in item.model_dump()  # unread removed from the list
    by_id = {item.id: item for item in result}
    assert by_id["c2"].is_pinned is True
    assert by_id["c1"].is_pinned is False


async def test_created_empty_returns_empty(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned=set())
    service = _service(channel_repo={"find_channels_by_user_id": _async([])})
    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.CREATED),
        SimpleNamespace(user_id=1),
    )
    assert result == []


# ─────────────────────────── followed branch ───────────────────────────

async def test_followed_keeps_visible_excludes_own_and_invisible(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned=set())
    # c1 = own (login user 1), c2 = visible other, c3 = not visible
    candidates = [
        _channel("c1", "Own", user_id=1),
        _channel("c2", "Visible", user_id=2),
        _channel("c3", "Hidden", user_id=3),
    ]
    monkeypatch.setattr(
        mod,
        "batch_check_business_visible",
        AsyncMock(return_value={"c1": True, "c2": True, "c3": False}),
    )
    service = _service(
        channel_repo={"find_permission_candidates": _async(candidates)},
        member_repo={"find_channel_memberships": _async([_membership("c2")])},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1),
    )

    assert [item.id for item in result] == ["c2"]  # own (c1) + invisible (c3) dropped
    item = result[0]
    assert item.actions == []
    assert item.user_role == UserRoleEnum.MEMBER.value
    assert item.relation == ChannelRelationEnum.VIEWER.value
    assert item.subscribed_at == datetime(2024, 2, 2)  # from membership row
    assert "unread_count" not in item.model_dump()


async def test_followed_visible_without_membership_has_null_subscribed_at(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned=set())
    candidates = [_channel("c9", "OrgGranted", user_id=2)]
    monkeypatch.setattr(
        mod, "batch_check_business_visible", AsyncMock(return_value={"c9": True})
    )
    # Visible via org grant, but no membership row.
    service = _service(
        channel_repo={"find_permission_candidates": _async(candidates)},
        member_repo={"find_channel_memberships": _async([])},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1),
    )

    assert [item.id for item in result] == ["c9"]
    assert result[0].subscribed_at is None


async def test_followed_no_visible_returns_empty(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned=set())
    candidates = [_channel("c2", "V", user_id=2)]
    monkeypatch.setattr(
        mod, "batch_check_business_visible", AsyncMock(return_value={"c2": False})
    )
    service = _service(
        channel_repo={"find_permission_candidates": _async(candidates)},
        member_repo={"find_channel_memberships": _async([])},
    )
    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1),
    )
    assert result == []


# ─────────────────────────── set_channel_pin ───────────────────────────

async def test_set_pin_pins_after_visible_check(monkeypatch):
    dao = _stub_pin_dao(monkeypatch, pinned=set())
    monkeypatch.setattr(
        mod, "batch_check_business_visible", AsyncMock(return_value={"c1": True})
    )
    service = _service(channel_repo={"find_channels_by_ids": _async([_channel("c1", "A", 1)])})

    ok = await service.set_channel_pin(
        SetPinRequest(channel_id="c1", is_pinned=True), SimpleNamespace(user_id=7)
    )

    assert ok is True
    dao.pin.assert_awaited_once_with(user_id=7, channel_id="c1")
    dao.unpin.assert_not_called()


async def test_set_pin_unpins(monkeypatch):
    dao = _stub_pin_dao(monkeypatch, pinned=set())
    monkeypatch.setattr(
        mod, "batch_check_business_visible", AsyncMock(return_value={"c1": True})
    )
    service = _service(channel_repo={"find_channels_by_ids": _async([_channel("c1", "A", 1)])})

    ok = await service.set_channel_pin(
        SetPinRequest(channel_id="c1", is_pinned=False), SimpleNamespace(user_id=7)
    )

    assert ok is True
    dao.unpin.assert_awaited_once_with(user_id=7, channel_id="c1")
    dao.pin.assert_not_called()


async def test_set_pin_rejects_when_not_visible(monkeypatch):
    dao = _stub_pin_dao(monkeypatch, pinned=set())
    monkeypatch.setattr(
        mod, "batch_check_business_visible", AsyncMock(return_value={"c1": False})
    )
    service = _service(channel_repo={"find_channels_by_ids": _async([_channel("c1", "A", 1)])})

    with pytest.raises(ChannelNotFoundError):
        await service.set_channel_pin(
            SetPinRequest(channel_id="c1", is_pinned=True), SimpleNamespace(user_id=7)
        )
    dao.pin.assert_not_called()
    dao.unpin.assert_not_called()


async def test_set_pin_rejects_when_channel_missing(monkeypatch):
    dao = _stub_pin_dao(monkeypatch, pinned=set())
    visible = AsyncMock(return_value={})
    monkeypatch.setattr(mod, "batch_check_business_visible", visible)
    service = _service(channel_repo={"find_channels_by_ids": _async([])})

    with pytest.raises(ChannelNotFoundError):
        await service.set_channel_pin(
            SetPinRequest(channel_id="c1", is_pinned=True), SimpleNamespace(user_id=7)
        )
    visible.assert_not_called()  # short-circuits before the visibility check
    dao.pin.assert_not_called()
