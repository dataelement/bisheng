"""Management API /api/v1/memory (AC-08, AC-09, AC-68, AC-87–AC-90, AC-103)."""

import inspect
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.memory import (
    MemoryContentSensitiveError,
    MemoryContentTooLongError,
    MemoryDetailUnavailableError,
    MemoryItemNotFoundError,
)
from bisheng.memory.api.endpoints import memory as api
from bisheng.memory.api.router import router
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.resident import ResidentService
from test.memory.conftest import TENANT_A, TENANT_B, USER_1, USER_2


def _user(user_id=USER_1):
    return SimpleNamespace(user_id=user_id, tenant_id=TENANT_A)


def _data(resp):
    return resp.data


@pytest.fixture
def tenant_a(tenant_ctx):
    tenant_ctx(TENANT_A)


@pytest.fixture
def resident_svc(kv):
    return ResidentService(kv=kv, metrics=m.MemoryMetrics(kv))


async def test_ac88_list_fields_and_manual_source(service, make_ctx, tenant_a):
    await service.write(
        make_ctx(scene="assistant", app_id="a1", app_name="差旅助手"), "remember", content="用户常飞上海", type="fact"
    )
    await api.add_item(
        api.ItemIn(content="用户的座位偏好是靠窗", type="preference"), login_user=_user(), service=service
    )
    items = _data(await api.list_items(login_user=_user(), service=service))
    assert {i["content"] for i in items} == {"用户常飞上海", "用户的座位偏好是靠窗"}
    manual = next(i for i in items if i["content"].startswith("用户的座位"))
    assert manual["source"]["origin"] == "manual" and manual["pinned"] is True
    other = next(i for i in items if i["content"] == "用户常飞上海")
    assert other["source"]["app_name"] == "差旅助手"
    assert {"id", "type", "recorded_at", "event_time", "pinned", "has_detail"} <= set(other)


async def test_ac89_add_and_edit_rejections_save_nothing(service, tenant_a):
    with pytest.raises(MemoryContentTooLongError):
        await api.add_item(api.ItemIn(content="长" * 201, type="fact"), login_user=_user(), service=service)
    with pytest.raises(MemoryContentSensitiveError):
        await api.add_item(api.ItemIn(content="我的密码是 abc12345", type="fact"), login_user=_user(), service=service)
    assert _data(await api.list_items(login_user=_user(), service=service)) == []


async def test_ac89_edit_delete_clear_undo(service, make_ctx, tenant_a):
    added = _data(
        await api.add_item(api.ItemIn(content="用户爱吃面", type="preference"), login_user=_user(), service=service)
    )
    edited = _data(
        await api.edit_item(
            added["item_id"], api.ItemIn(content="用户爱吃米饭", type="preference"), login_user=_user(), service=service
        )
    )
    assert [i["content"] for i in _data(await api.list_items(login_user=_user(), service=service))] == ["用户爱吃米饭"]
    await api.delete_item(edited["item_id"], login_user=_user(), service=service)
    assert _data(await api.list_items(login_user=_user(), service=service)) == []
    ctx = make_ctx(turn_id="t1")
    await service.write(ctx, "remember", content="用户的猫叫咪咪", type="fact")
    view = _data(await api.get_turn(turn_id="t1", message_id=None, login_user=_user(), service=service, resident=None))
    await api.undo(api.UndoIn(record_id=view["writes"][0]["record_id"]), login_user=_user(), service=service)
    assert _data(await api.list_items(login_user=_user(), service=service)) == []
    await service.write(ctx, "remember", content="用户的狗叫旺财", type="fact")
    await api.clear_items(login_user=_user(), service=service)
    assert _data(await api.list_items(login_user=_user(), service=service)) == []


async def test_ac08_other_users_item_ids_are_not_found(service, make_ctx, tenant_a):
    theirs = await service.write(make_ctx(user_id=USER_2), "remember", content="乙的秘密爱好是唱歌", type="preference")
    with pytest.raises(MemoryItemNotFoundError):
        await api.delete_item(theirs.item_id, login_user=_user(USER_1), service=service)
    with pytest.raises(MemoryItemNotFoundError):
        await api.edit_item(
            theirs.item_id, api.ItemIn(content="改掉", type="fact"), login_user=_user(USER_1), service=service
        )
    assert len(await service.list(make_ctx(user_id=USER_2))) == 1


def test_ac08_no_user_id_parameter_and_no_metrics_endpoint():
    for route in router.routes:
        params = inspect.signature(route.endpoint).parameters
        assert "user_id" not in params, route.path
        assert not any(word in route.path for word in ("metric", "stat", "config")), route.path


async def test_ac90_my_memory_off_does_not_block_management(service, make_ctx, tenant_a):
    await api.update_setting(api.SettingIn(enabled=False), login_user=_user(), service=service)
    assert _data(await api.get_setting(login_user=_user()))["enabled"] is False
    added = _data(
        await api.add_item(
            api.ItemIn(content="用户偏好深色主题", type="preference"), login_user=_user(), service=service
        )
    )
    await api.edit_item(
        added["item_id"], api.ItemIn(content="用户偏好浅色主题", type="preference"), login_user=_user(), service=service
    )
    assert len(_data(await api.list_items(login_user=_user(), service=service))) == 1
    await api.clear_items(login_user=_user(), service=service)


async def test_ac68_switch_default_on_and_only_affects_self(service, tenant_a):
    assert _data(await api.get_setting(login_user=_user(USER_1)))["enabled"] is True
    await api.update_setting(api.SettingIn(enabled=False), login_user=_user(USER_1), service=service)
    assert _data(await api.get_setting(login_user=_user(USER_2)))["enabled"] is True


async def test_timezone_written_only_when_changed(memory_db, make_ctx, tenant_a, monkeypatch):
    calls = []
    original = SettingRepository.set_timezone.__func__

    async def spy(cls, ctx, tz):
        changed = await original(cls, ctx, tz)
        calls.append(changed)
        return changed

    monkeypatch.setattr(SettingRepository, "set_timezone", classmethod(spy))
    await api.report_timezone(api.TimezoneIn(timezone="Asia/Taipei"), login_user=_user())
    await api.report_timezone(api.TimezoneIn(timezone="Asia/Taipei"), login_user=_user())
    assert calls == [True, False]
    with pytest.raises(ValueError):
        api.TimezoneIn(timezone="Not/AZone")


async def test_ac87_turn_view_has_retrieved_and_resident_parts(service, make_ctx, tenant_a, resident_svc):
    from bisheng.memory.domain.services.turn_record import TurnRecordService

    ctx = make_ctx(turn_id="t9")
    a = await service.write(make_ctx(turn_id="t0"), "remember", content="用户住在厦门", type="fact")
    b = await service.write(make_ctx(turn_id="t0"), "remember", content="做调研时先看一手数据", type="experience")
    block = await resident_svc.resident(ctx, "chat")
    await TurnRecordService.add_retrieved(ctx, [b.item_id])
    await TurnRecordService.add_summary(ctx, block.rev, block.day, "chat")
    await TurnRecordService.bind_turn(ctx, 77)
    view = _data(
        await api.get_turn(turn_id=None, message_id=77, login_user=_user(), service=service, resident=resident_svc)
    )
    assert [i["id"] for i in view["retrieved"]] == [b.item_id]
    assert [i["id"] for i in view["resident"]] == [a.item_id]
    other = _data(
        await api.get_turn(
            turn_id=None, message_id=77, login_user=_user(USER_2), service=service, resident=resident_svc
        )
    )
    assert other["retrieved"] == [] and other["resident"] == [] and other["writes"] == []


async def test_turn_view_from_other_tenant_is_empty(service, make_ctx, tenant_ctx):
    ctx = make_ctx(turn_id="t1")
    await service.write(ctx, "remember", content="用户的组是平台组", type="fact")
    tenant_ctx(TENANT_B)
    view = _data(await api.get_turn(turn_id="t1", message_id=None, login_user=_user(), service=service, resident=None))
    assert view["writes"] == []


async def test_flags_by_chat(service, make_ctx, tenant_a):
    from bisheng.memory.domain.services.turn_record import TurnRecordService

    ctx = make_ctx(turn_id="t1", chat_id="c-flags")
    await service.write(ctx, "remember", content="用户周末在家办公", type="fact")
    await TurnRecordService.bind_turn(ctx, 5)
    flags = _data(await api.get_flags(chat_id="c-flags", login_user=_user()))
    assert flags == {"5": {"turn_id": "t1", "has_write": True, "has_attribution": False}}
    assert _data(await api.get_flags(chat_id="c-flags", login_user=_user(USER_2))) == {}


async def test_ac88_full_text_readable_and_kept_through_an_edit(service, make_ctx, details, tenant_a):
    res = await service.write(
        make_ctx(), "remember", content="用户的周报格式", type="experience", detail="周报全文：先结论后过程"
    )
    plain = await service.write(make_ctx(), "remember", content="用户喜欢冰美式", type="preference")
    get = lambda item_id, user=None: api.get_item_detail(item_id, login_user=user or _user(), service=service)  # noqa: E731
    assert _data(await get(res.item_id)) == {"detail": "周报全文：先结论后过程"}
    assert _data(await get(plain.item_id)) == {"detail": None}
    with pytest.raises(MemoryItemNotFoundError):
        await get(res.item_id, _user(USER_2))

    # A hand edit changes the one-line content; the full text moves to the new item.
    edited = _data(
        await api.edit_item(
            res.item_id,
            api.ItemIn(content="用户的周报格式是先结论", type="experience"),
            login_user=_user(),
            service=service,
        )
    )
    assert _data(await get(edited["item_id"])) == {"detail": "周报全文：先结论后过程"}
    with pytest.raises(MemoryItemNotFoundError):
        await get(res.item_id)  # the edited-away item is no longer active

    # Unreadable full text: the read says so, and an edit saves nothing rather than drop it.
    details.read_fail = True
    with pytest.raises(MemoryDetailUnavailableError):
        await get(edited["item_id"])
    with pytest.raises(MemoryDetailUnavailableError):
        await api.edit_item(
            edited["item_id"], api.ItemIn(content="改不成", type="experience"), login_user=_user(), service=service
        )
    contents = {i["content"] for i in _data(await api.list_items(login_user=_user(), service=service))}
    assert contents == {"用户的周报格式是先结论", "用户喜欢冰美式"}
