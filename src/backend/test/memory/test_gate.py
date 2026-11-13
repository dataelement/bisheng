"""Eligibility registration and enablement (AC-10, AC-40, AC-66, AC-72, AC-73, AC-74, AC-76, AC-99)."""

from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.database.models.message import ChatMessage
from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.ports import SCENE_ASSISTANT, SCENE_DAILY, SCENE_WORKFLOW
from bisheng.memory.domain.repositories.setting_repository import SettingRepository
from bisheng.memory.domain.services.gate import MemoryGate
from bisheng.user.domain.models.user import User
from test.memory.conftest import TENANT_A, TENANT_B, USER_1, USER_2, make_message


def _login(user_id=USER_1):
    return SimpleNamespace(user_id=user_id)


def _seed_chat(memory_db, chat_id="chat-1", owner=USER_1, messages=3, user_delete=0):
    with memory_db.session() as s:
        if s.get(User, owner) is None:
            s.add(User(user_id=owner, user_name=f"u{owner}", password="x", delete=user_delete))
        s.add(MessageSession(chat_id=chat_id, flow_id="", flow_type=15, user_id=owner, name="c"))
        for i in range(messages):
            s.add(make_message(chat_id, owner, f"m{i}"))
        s.commit()


def _cursor(memory_db, chat_id="chat-1"):
    with memory_db.session() as s:
        return s.get(MemorySessionCursor, chat_id)


async def test_resolve_without_registration_returns_none(memory_db):
    """AC-10: no registration row (open API, guest link, evaluation) means memory never works."""
    assert await MemoryGate.resolve("chat-x", SCENE_DAILY) is None


async def test_ac40_open_creates_row_with_watermark_at_current_max(memory_db, tenant_ctx):
    """AC-40: history before registration is never consolidated: watermark = current max message id."""
    _seed_chat(memory_db, messages=3)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    row = _cursor(memory_db)
    with memory_db.session() as s:
        max_id = max(m.id for m in s.exec(select(ChatMessage)).all())
    assert (row.tenant_id, row.user_id, row.eligible) == (TENANT_A, USER_1, True)
    assert row.watermark_message_id == max_id == row.last_message_id


async def test_open_new_chat_without_session_row(memory_db, tenant_ctx):
    tenant_ctx(TENANT_A)
    await MemoryGate.open("brand-new", _login())
    row = _cursor(memory_db, "brand-new")
    assert row.watermark_message_id == 0 and row.eligible


async def test_open_again_same_owner_keeps_row_updates_timezone_only_on_change(memory_db, tenant_ctx, make_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    first = _cursor(memory_db)
    await MemoryGate.open("chat-1", _login())
    assert _cursor(memory_db).model_dump() == first.model_dump()
    await SettingRepository.set_timezone(make_ctx(), "Asia/Taipei")
    await MemoryGate.open("chat-1", _login())
    row = _cursor(memory_db)
    assert row.timezone == "Asia/Taipei"
    assert row.watermark_message_id == first.watermark_message_id


async def test_open_with_other_tenant_marks_ineligible(memory_db, tenant_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    tenant_ctx(TENANT_B)
    await MemoryGate.open("chat-1", _login())
    row = _cursor(memory_db)
    assert row.eligible is False and row.tenant_id == TENANT_A
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is None


async def test_open_rejects_chat_owned_by_someone_else(memory_db, tenant_ctx):
    """A user who knows another user's chat_id cannot register it."""
    _seed_chat(memory_db, owner=USER_2)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login(USER_1))
    assert _cursor(memory_db) is None


async def test_ac14_timezone_fallback_chain(memory_db, tenant_ctx, make_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    ctx = await MemoryGate.resolve("chat-1", SCENE_DAILY)
    assert ctx.timezone == "Asia/Shanghai"  # deployment default
    await SettingRepository.set_timezone(make_ctx(), "Europe/Berlin")
    assert (await MemoryGate.resolve("chat-1", SCENE_DAILY)).timezone == "Europe/Berlin"  # user setting
    with memory_db.session() as s:
        row = s.get(MemorySessionCursor, "chat-1")
        row.timezone = "Asia/Tokyo"
        s.add(row)
        s.commit()
    assert (await MemoryGate.resolve("chat-1", SCENE_DAILY)).timezone == "Asia/Tokyo"  # registration row


@pytest.mark.parametrize(
    "scene,user_on,app_on,expected",
    [
        (SCENE_DAILY, True, True, True),
        (SCENE_DAILY, False, True, False),
        (SCENE_ASSISTANT, True, True, True),
        (SCENE_ASSISTANT, True, False, False),
        (SCENE_ASSISTANT, False, True, False),
        (SCENE_WORKFLOW, True, True, True),
        (SCENE_WORKFLOW, True, False, False),
        (SCENE_WORKFLOW, False, False, False),
    ],
)
async def test_ac66_enablement_matrix(memory_db, tenant_ctx, make_ctx, scene, user_on, app_on, expected):
    """AC-66: user switch AND (for assistant/workflow) the app switch."""
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    await SettingRepository.set_enabled(make_ctx(), user_on)
    ctx = await MemoryGate.resolve("chat-1", scene, app_enabled=app_on)
    assert (ctx is not None) is expected


async def test_ac76_no_setting_row_means_enabled(memory_db, tenant_ctx):
    """AC-76: after upgrade every user's "my memory" is on (no row = on)."""
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    with memory_db.session() as s:
        assert s.exec(select(MemoryUserSetting)).all() == []
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is not None


async def test_ac99_disabled_user_gets_nothing_until_reenabled(memory_db, tenant_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    with memory_db.session() as s:
        user = s.get(User, USER_1)
        user.delete = 1
        s.add(user)
        s.commit()
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is None
    with memory_db.session() as s:
        user = s.get(User, USER_1)
        user.delete = 0
        s.add(user)
        s.commit()
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is not None


async def test_ac72_ac73_switch_off_then_on_keeps_identity(memory_db, tenant_ctx, make_ctx):
    """AC-72/73: turning off stops memory; turning on again resumes with the same space."""
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    await SettingRepository.set_enabled(make_ctx(), False)
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is None
    await SettingRepository.set_enabled(make_ctx(), True)
    ctx = await MemoryGate.resolve("chat-1", SCENE_DAILY)
    assert (ctx.tenant_id, ctx.user_id) == (TENANT_A, USER_1)


async def test_ac74_result_is_a_snapshot_for_the_turn(memory_db, tenant_ctx, make_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    ctx = await MemoryGate.resolve("chat-1", SCENE_DAILY)
    await SettingRepository.set_enabled(make_ctx(), False)
    assert ctx.turn_id and ctx.user_id == USER_1  # unchanged object for this turn
    assert await MemoryGate.resolve("chat-1", SCENE_DAILY) is None  # next turn


async def test_downstream_uses_row_identity_not_tenant_contextvar(memory_db, tenant_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    tenant_ctx(TENANT_B)
    ctx = await MemoryGate.resolve("chat-1", SCENE_DAILY)
    assert (ctx.tenant_id, ctx.user_id) == (TENANT_A, USER_1)


async def test_each_resolve_has_new_turn_id_and_sync_version_matches(memory_db, tenant_ctx):
    _seed_chat(memory_db)
    tenant_ctx(TENANT_A)
    await MemoryGate.open("chat-1", _login())
    a = await MemoryGate.resolve("chat-1", SCENE_DAILY)
    b = MemoryGate.resolve_sync("chat-1", SCENE_WORKFLOW, app_enabled=True)
    assert a.turn_id != b.turn_id
    assert (b.tenant_id, b.user_id, b.scene) == (TENANT_A, USER_1, SCENE_WORKFLOW)
    assert MemoryGate.resolve_sync("chat-1", SCENE_WORKFLOW, app_enabled=False) is None
