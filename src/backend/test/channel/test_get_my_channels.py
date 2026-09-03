"""F051 — get_my_channels (created / followed branches) and set_channel_pin.

The list endpoint no longer returns unread counts or F048 actions, reads pin state
from the decoupled channel_user_pin table, sources "created" straight from the
channel table by user_id, and derives "followed" from OpenFGA's visible-ids
enumeration (via ``runtime.list_visible_objects``) minus the user's own created
channels — filtered at the DB layer, not in Python. set_channel_pin gates on the
concrete visible action.
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


def _stub_visible_flow(monkeypatch, *, visible_ids: list[str]):
    """Stub the F048 "visible-ids-first" path used by _get_followed_channels.

    ``resolve_permission_actor`` is replaced with a light wrapper that just
    exposes ``user_id`` / ``current_tenant_id`` from the test login_user;
    ``get_f048_runtime`` returns a fake with a ``list_visible_objects`` coroutine
    that yields the requested id set. Together they let the service run without
    booting the F048 runtime, OpenFGA client, or Redis marker plumbing.
    """

    async def _resolve_actor(login_user):
        return SimpleNamespace(
            user_id=login_user.user_id,
            current_tenant_id=getattr(login_user, "tenant_id", 1),
        )

    async def _list_visible_objects(actor, *, resource_type, max_results):
        assert resource_type == "channel"
        return SimpleNamespace(object_ids=tuple(visible_ids))

    async def _get_runtime():
        return SimpleNamespace(list_visible_objects=_list_visible_objects)

    monkeypatch.setattr(mod, "resolve_permission_actor", _resolve_actor)
    monkeypatch.setattr(mod, "get_f048_runtime", _get_runtime)


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
    """FGA marks c1(own) + c2(visible other) visible; c3 not visible → not in list.

    The old code let batch_check_business_visible say True for all three and then
    filtered ``user_id != login_user.user_id`` in Python. The new flow trusts
    OpenFGA to omit the un-visible id, and pushes the "not my own" predicate
    into the DB read — so ``find_followed_by_visible_ids`` is what drops c1.
    """
    _stub_pin_dao(monkeypatch, pinned=set())
    _stub_visible_flow(monkeypatch, visible_ids=["c1", "c2"])
    # The DB layer honours ``exclude_creator_id=1``, so only c2 comes back even
    # though FGA said c1 is also visible (creators can always see their own).
    followed_rows = _async([_channel("c2", "Visible", user_id=2)])
    service = _service(
        channel_repo={"find_followed_by_visible_ids": followed_rows},
        member_repo={"find_channel_memberships": _async([_membership("c2")])},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1, tenant_id=1),
    )

    assert [item.id for item in result] == ["c2"]
    item = result[0]
    assert item.actions == []
    assert item.user_role == UserRoleEnum.MEMBER.value
    assert item.relation == ChannelRelationEnum.VIEWER.value
    assert item.subscribed_at == datetime(2024, 2, 2)  # from membership row
    assert "unread_count" not in item.model_dump()


async def test_followed_delegates_own_exclusion_to_db_layer(monkeypatch):
    """The service must pass ``exclude_creator_id=login_user.user_id`` through.

    Guards the invariant that the "not my own" predicate lives in the SQL
    ``WHERE`` clause (not in a Python post-filter), which is the whole point of
    moving off the "candidate + batch_check_business_visible" flow.
    """
    _stub_pin_dao(monkeypatch, pinned=set())
    _stub_visible_flow(monkeypatch, visible_ids=["c1", "c2"])
    captured: dict[str, object] = {}

    async def _find_followed(channel_ids, *, tenant_id, exclude_creator_id):
        captured["channel_ids"] = list(channel_ids)
        captured["tenant_id"] = tenant_id
        captured["exclude_creator_id"] = exclude_creator_id
        # DB drops c1 (own), keeps c2.
        return [_channel("c2", "Visible", user_id=2)]

    service = _service(
        channel_repo={"find_followed_by_visible_ids": _find_followed},
        member_repo={"find_channel_memberships": _async([])},
    )

    await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=7, tenant_id=42),
    )

    assert captured == {
        "channel_ids": ["c1", "c2"],
        "tenant_id": 42,
        "exclude_creator_id": 7,
    }


async def test_followed_visible_without_membership_has_null_subscribed_at(monkeypatch):
    _stub_pin_dao(monkeypatch, pinned=set())
    _stub_visible_flow(monkeypatch, visible_ids=["c9"])
    # Visible via org grant, but no membership row.
    service = _service(
        channel_repo={
            "find_followed_by_visible_ids": _async([_channel("c9", "OrgGranted", user_id=2)]),
        },
        member_repo={"find_channel_memberships": _async([])},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1, tenant_id=1),
    )

    assert [item.id for item in result] == ["c9"]
    assert result[0].subscribed_at is None


async def test_followed_no_visible_ids_skips_db_and_membership(monkeypatch):
    """Empty visible id set → no DB read, no membership query, empty response.

    Locks in that both downstream calls are skipped so the endpoint costs one
    OpenFGA hop (and one catalog SQL inside the runtime) when the user can see
    zero channels.
    """
    _stub_pin_dao(monkeypatch, pinned=set())
    _stub_visible_flow(monkeypatch, visible_ids=[])
    db_calls = AsyncMock(return_value=[])
    member_calls = AsyncMock(return_value=[])
    service = _service(
        channel_repo={"find_followed_by_visible_ids": db_calls},
        member_repo={"find_channel_memberships": member_calls},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1, tenant_id=1),
    )

    assert result == []
    db_calls.assert_not_called()
    member_calls.assert_not_called()


async def test_followed_all_own_channels_skip_membership_query(monkeypatch):
    """When every visible channel is the caller's own, no follower rows remain.

    The DB layer's ``exclude_creator_id`` drops them all, so the membership fetch
    can be short-circuited too — asserted here so future refactors don't
    accidentally re-issue a needless query.
    """
    _stub_pin_dao(monkeypatch, pinned=set())
    _stub_visible_flow(monkeypatch, visible_ids=["c1"])
    member_calls = AsyncMock(return_value=[])
    service = _service(
        channel_repo={"find_followed_by_visible_ids": _async([])},  # DB filtered c1 out
        member_repo={"find_channel_memberships": member_calls},
    )

    result = await service.get_my_channels(
        MyChannelQueryRequest(query_type=QueryTypeEnum.FOLLOWED),
        SimpleNamespace(user_id=1, tenant_id=1),
    )

    assert result == []
    member_calls.assert_not_called()


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
