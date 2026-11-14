"""AI revision of one memory item from a plain instruction (AC-107)."""

import json

import pytest

from bisheng.common.errcode.memory import (
    MemoryContentRelativeTimeError,
    MemoryContentTooLongError,
    MemoryItemNotFoundError,
    MemoryNoModelError,
    MemoryReviseFailedError,
)
from bisheng.memory.api.endpoints import memory as api
from bisheng.memory.domain.services.revise import revise_item
from test.memory.conftest import USER_2


def _answer(summary, detail="", type="fact", event_time=None):  # noqa: A002
    return json.dumps(
        {"summary": summary, "detail": detail, "type": type, "event_time": event_time}, ensure_ascii=False
    )


async def _trip(service, make_ctx):
    return await service.write(
        make_ctx(),
        "remember",
        content="用户计划在2026-12-01去海南度假",
        type="fact",
        event_time="2026-12-01",
        detail="- 目的地：海南\n- 需要行李清单",
    )


async def _active(service, ctx):
    return {i.content: i for i in await service.list(ctx)}


async def test_revise_rewrites_summary_and_detail_and_returns_the_previous_version(service, llm, make_ctx, audit_rows):
    ctx = make_ctx()
    old = await _trip(service, make_ctx)
    llm.answers = [
        "```json\n"
        + _answer("用户计划在2027-01-10去海南度假", "- 目的地：海南\n- 出发：2027-01-10", event_time="2027-01-10")
        + "\n```"
    ]
    rev = await revise_item(ctx, old.item_id, "出行改到 2027 年 1 月 10 日", service, llm)

    assert rev.changed and rev.item_id != old.item_id
    assert rev.previous == {
        "summary": "用户计划在2026-12-01去海南度假",
        "detail": "- 目的地：海南\n- 需要行李清单",
        "type": "fact",
        "event_time": "2026-12-01",
    }
    assert "出行改到 2027 年 1 月 10 日" in llm.prompts[0] and "需要行李清单" in llm.prompts[0]
    assert list(await _active(service, ctx)) == ["用户计划在2027-01-10去海南度假"]
    assert await service.get_detail(ctx, rev.item_id) == "- 目的地：海南\n- 出发：2027-01-10"
    assert audit_rows.rows[-1]["action"] == "memory.item.revise"

    # Undo: edit the new item back to the previous version.
    back = await service.edit(
        ctx,
        rev.item_id,
        rev.previous["summary"],
        rev.previous["type"],
        rev.previous["event_time"],
        detail=rev.previous["detail"],
    )
    assert await service.get_detail(ctx, back.item_id) == "- 目的地：海南\n- 需要行李清单"


async def test_revise_that_changes_nothing_writes_nothing(service, llm, make_ctx):
    ctx = make_ctx()
    old = await _trip(service, make_ctx)
    llm.answers = [_answer("用户计划在2026-12-01去海南度假", "- 目的地：海南\n- 需要行李清单", event_time="2026-12-01")]
    rev = await revise_item(ctx, old.item_id, "今天天气不错", service, llm)
    assert not rev.changed and rev.item_id == old.item_id
    assert [i.id for i in await service.list(ctx)] == [old.item_id]


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ("我改不了", MemoryReviseFailedError),
        (_answer("用户计划下个月去海南"), MemoryContentRelativeTimeError),
        (_answer("长" * 201), MemoryContentTooLongError),
        (_answer("用户计划去海南", type="todo"), MemoryReviseFailedError),
        (_answer("用户计划去海南", event_time="下周"), MemoryReviseFailedError),
        (RuntimeError("model down"), MemoryReviseFailedError),
        (MemoryNoModelError(), MemoryNoModelError),
    ],
)
async def test_revise_failures_leave_the_item_alone(service, llm, make_ctx, answer, error):
    ctx = make_ctx()
    old = await _trip(service, make_ctx)
    llm.answers = [answer]
    with pytest.raises(error):
        await revise_item(ctx, old.item_id, "改一下", service, llm)
    assert [i.id for i in await service.list(ctx)] == [old.item_id]


async def test_revise_only_own_items(service, llm, make_ctx):
    old = await _trip(service, make_ctx)
    with pytest.raises(MemoryItemNotFoundError):
        await revise_item(make_ctx(user_id=USER_2), old.item_id, "改一下", service, llm)
    assert llm.prompts == []


async def test_revise_endpoint(service, llm, make_ctx, tenant_ctx):
    from types import SimpleNamespace

    from test.memory.conftest import TENANT_A, USER_1

    tenant_ctx(TENANT_A)
    old = await _trip(service, make_ctx)
    llm.answers = [_answer("用户计划在2027-01-10去海南度假", "", event_time="2027-01-10")]
    resp = await api.revise_memory_item(
        old.item_id,
        api.ReviseIn(instruction="改到 2027-01-10，去掉清单"),
        login_user=SimpleNamespace(user_id=USER_1, tenant_id=TENANT_A),
        service=service,
        llm=llm,
    )
    assert resp.data["changed"] is True and resp.data["previous"]["summary"] == "用户计划在2026-12-01去海南度假"
    assert await service.get_detail(make_ctx(), resp.data["item_id"]) is None
