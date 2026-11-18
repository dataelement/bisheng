"""F132 T073: consolidation of deep-research rounds (AC-39, AC-42; decision 7, R8, P-01).

A deep-research round is consolidated from its own question and result, read
through the deep-research module (never from its tables). One summary row per
round carries the ``consolidated`` flag: each ended round is consolidated once
and only once; running or parked rounds wait; rounds unfinished for over 24
hours are abandoned; ``/continue`` rounds (flagged consolidated at start, P-01
option C) are never consolidated. The daily messages of the same conversation
keep their message-watermark consolidation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from bisheng.database.models.session import MessageSession
from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.models.memory_turn_record import KIND_SUMMARY, MemoryTurnRecord
from bisheng.memory.domain.models.memory_user_setting import MemoryUserSetting
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.consolidation_linsight import LinsightRoundConsolidation
from bisheng.memory.domain.services.consolidator import Consolidator
from bisheng.user.domain.models.user import User
from test.memory.conftest import TENANT_A, USER_1, counter, make_message

CHAT = "chat-dr-1"
LONG_AGO = datetime.now() - timedelta(hours=2)


def _seed_chat(memory_db, chat_id=CHAT, daily_messages=()):
    with memory_db.session() as s:
        if s.get(User, USER_1) is None:
            s.add(User(user_id=USER_1, user_name="u", password="x"))
        s.add(MessageSession(chat_id=chat_id, flow_id="", flow_type=15, user_id=USER_1, name="c"))
        ids = []
        for category, text, is_bot in daily_messages:
            msg = make_message(chat_id, USER_1, text, category=category, is_bot=is_bot)
            s.add(msg)
            s.flush()
            ids.append(msg.id)
        s.add(
            MemorySessionCursor(
                chat_id=chat_id,
                tenant_id=TENANT_A,
                user_id=USER_1,
                state="pending",
                last_activity_at=LONG_AGO,
                last_message_id=ids[-1] if ids else 0,
                watermark_message_id=0,
            )
        )
        s.commit()
    return ids


def _add_round(memory_db, message_id, *, ended=True, consolidated=False, created=None, chat_id=CHAT, turn=None):
    with memory_db.session() as s:
        row = MemoryTurnRecord(
            turn_id=turn or f"turn-{message_id}-{consolidated}",
            chat_id=chat_id,
            message_id=message_id,
            tenant_id=TENANT_A,
            user_id=USER_1,
            kind=KIND_SUMMARY,
            scene_class="linsight",
            ended=ended,
            consolidated=consolidated,
            create_time=created or datetime.now(),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def _summary(memory_db, row_id):
    with memory_db.session() as s:
        return s.get(MemoryTurnRecord, row_id)


class FakeReader:
    """Stands in for the deep-research round reader: (chat_id, message_id) -> question/answer/finished."""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls: list = []

    async def __call__(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        return self.rounds.get(message_id)


class FakeContent:
    """``from_messages`` double: one fact per round, records what it was given."""

    def __init__(self):
        self.seen: list = []

    async def from_messages(self, ctx, messages):
        self.seen.append(list(messages))
        question = messages[0][1]
        return [{"op": "add", "content": f"用户研究过：{question}", "type": "fact"}]


def _round(question, answer, finished=True):
    return {"question": question, "answer": answer, "finished": finished}


@pytest.fixture
def step(service):
    def _make(reader):
        content = FakeContent()
        return LinsightRoundConsolidation(service=service, content=content, reader=reader), content

    return _make


async def _items():
    async with _db.async_session() as s:
        return list((await s.exec(select(MemoryItem).order_by(MemoryItem.recorded_at))).all())


async def test_ac39_three_rounds_each_consolidated_once(memory_db, step):
    """AC-39: a task with two follow-ups has three rounds; each is consolidated once and only once."""
    _seed_chat(memory_db)
    rows = [_add_round(memory_db, mid) for mid in (11, 12, 13)]
    reader = FakeReader(
        {11: _round("问题一", "结果一"), 12: _round("问题二", "结果二"), 13: _round("问题三", "结果三")}
    )
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)
    await consolidation(TENANT_A, USER_1)  # a rerun finds nothing new

    assert len(content.seen) == 3
    assert all(_summary(memory_db, r).consolidated for r in rows)
    assert sorted(i.content for i in await _items()) == sorted(
        ["用户研究过：问题一", "用户研究过：问题二", "用户研究过：问题三"]
    )


async def test_ac39_each_round_reads_its_own_question_and_result(memory_db, step):
    """AC-39: the content of a round is that round's question and result, nothing else."""
    _seed_chat(memory_db)
    _add_round(memory_db, 21)
    _add_round(memory_db, 22)
    reader = FakeReader({21: _round("台北房价", "报告A"), 22: _round("东京房价", "报告B")})
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)

    assert sorted(reader.calls) == [(CHAT, 21), (CHAT, 22)]
    assert sorted(content.seen) == sorted(
        [[("用户", "台北房价"), ("系统", "报告A")], [("用户", "东京房价"), ("系统", "报告B")]]
    )


async def test_ac39_running_or_parked_round_waits(memory_db, step):
    """AC-39: a round still running or parked on ask_user (not ended) is not consolidated yet."""
    _seed_chat(memory_db)
    parked = _add_round(memory_db, 31, ended=False)
    unfinished = _add_round(memory_db, 32)  # ended flag set but the version is still not terminal
    reader = FakeReader({31: _round("q", "a"), 32: _round("q2", "a2", finished=False)})
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)

    assert content.seen == []
    assert not _summary(memory_db, parked).consolidated
    assert not _summary(memory_db, unfinished).consolidated


async def test_ac39_round_unfinished_for_24h_is_abandoned(memory_db, step):
    """AC-39: a round not ended after 24 hours is marked abandoned and never tried again."""
    _seed_chat(memory_db)
    stale = _add_round(memory_db, 41, ended=False, created=datetime.now() - timedelta(hours=25))
    reader = FakeReader({41: _round("q", "a")})
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)
    await consolidation(TENANT_A, USER_1)

    row = _summary(memory_db, stale)
    assert row.consolidated and row.op == "abandoned"
    assert content.seen == [] and reader.calls == []


async def test_ac42_items_carry_deep_research_source(memory_db, step):
    """AC-42: items consolidated from a round are marked as coming from deep research."""
    _seed_chat(memory_db)
    _add_round(memory_db, 51)
    consolidation, _ = step(FakeReader({51: _round("问题", "结果")}))

    await consolidation(TENANT_A, USER_1)

    items = await _items()
    assert len(items) == 1
    assert items[0].source_scene == "linsight" and items[0].source_chat_id == CHAT and items[0].origin == "auto"


async def test_ac42_continue_round_is_never_consolidated(memory_db, step):
    """P-01 option C: a /continue round (flagged at start) is skipped."""
    _seed_chat(memory_db)
    _add_round(memory_db, 61, consolidated=True)
    reader = FakeReader({61: _round("q", "a")})
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)

    assert content.seen == [] and reader.calls == []


async def test_ac42_memory_off_skips_round_for_good(memory_db, step):
    """AC-41 via AC-42: with "my memory" off the round is marked done without consolidation."""
    _seed_chat(memory_db)
    row_id = _add_round(memory_db, 71)
    with memory_db.session() as s:
        s.add(MemoryUserSetting(tenant_id=TENANT_A, user_id=USER_1, enabled=False))
        s.commit()
    consolidation, content = step(FakeReader({71: _round("q", "a")}))

    await consolidation(TENANT_A, USER_1)

    assert content.seen == [] and _summary(memory_db, row_id).consolidated


async def test_ac42_other_users_rounds_untouched(memory_db, step):
    """Isolation: consolidating user 1 never touches another user's rounds."""
    _seed_chat(memory_db)
    with memory_db.session() as s:
        other = MemoryTurnRecord(
            turn_id="other",
            chat_id="chat-x",
            message_id=81,
            tenant_id=TENANT_A,
            user_id=USER_1 + 1,
            kind=KIND_SUMMARY,
            scene_class="linsight",
            ended=True,
        )
        s.add(other)
        s.commit()
        s.refresh(other)
        other_id = other.id
    reader = FakeReader({81: _round("q", "a")})
    consolidation, content = step(reader)

    await consolidation(TENANT_A, USER_1)

    assert reader.calls == [] and not _summary(memory_db, other_id).consolidated


class DailyContent:
    def __init__(self):
        self.calls = []

    async def __call__(self, ctx, cursor, end_id):
        self.calls.append((cursor.chat_id, cursor.watermark_message_id, end_id))
        return [{"op": "add", "content": "日常对话里的结论", "type": "fact"}]


async def test_ac39_daily_watermark_and_rounds_do_not_interfere(memory_db, service, kv, step):
    """AC-39 / AC-42: in one conversation the daily messages follow the watermark and the
    deep-research rounds follow their own flags; one consolidator run handles both once."""
    ids = _seed_chat(memory_db, daily_messages=[("question", "你好", False), ("answer", "你好呀", True)])
    round_id = _add_round(memory_db, 99)
    consolidation, content = step(FakeReader({99: _round("研究问题", "研究结果")}))
    daily = DailyContent()
    consolidator = Consolidator(
        service=service, kv=kv, metrics=m.MemoryMetrics(kv), content_fn=daily, extra_steps=[consolidation]
    )

    await consolidator.consolidate_user(TENANT_A, USER_1)

    assert daily.calls == [(CHAT, 0, ids[-1])]
    assert len(content.seen) == 1 and _summary(memory_db, round_id).consolidated
    with memory_db.session() as s:
        cursor = s.get(MemorySessionCursor, CHAT)
    assert cursor.watermark_message_id == ids[-1] and cursor.state == "idle"
    assert sorted(i.content for i in await _items()) == sorted(["日常对话里的结论", "用户研究过：研究问题"])
    assert await counter(kv, TENANT_A, m.ADDED_AUTO) == 2


async def test_ac42_factory_wires_round_step_into_consolidator(monkeypatch):
    """AC-42: the production consolidator runs the deep-research round step."""
    from bisheng.memory.domain.services import factory

    monkeypatch.setattr(factory, "_instances", {"kv": SimpleNamespace(), "llm": SimpleNamespace()})
    monkeypatch.setattr(factory, "get_memory_service", lambda: SimpleNamespace())
    monkeypatch.setattr(factory, "get_metrics", lambda: SimpleNamespace())

    consolidator = factory.get_consolidator()

    assert any(isinstance(s, LinsightRoundConsolidation) for s in consolidator.extra_steps)


async def test_ac42_linsight_reader_reads_question_and_result_by_task_message(monkeypatch):
    """AC-42: the deep-research reader maps a task message row to its version's question and result."""
    import json

    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
    from bisheng.linsight.domain.services import memory_turns

    message = SimpleNamespace(
        id=5, chat_id=CHAT, user_id=USER_1, category="task", is_bot=True,
        extra=json.dumps({"linsight_session_version_id": "sv-9"}),
    )  # fmt: skip
    version = SimpleNamespace(
        id="sv-9",
        session_id=CHAT,
        user_id=USER_1,
        question="研究问题",
        output_result={"answer": "研究结果"},
        status=SessionVersionStatusEnum.COMPLETED,
    )

    async def _msg(message_id):
        return message if message_id == 5 else None

    async def _ver(linsight_session_version_id):
        return version

    monkeypatch.setattr(memory_turns.ChatMessageDao, "aget_message_by_id", _msg)
    monkeypatch.setattr(memory_turns.LinsightSessionVersionDao, "get_by_id", _ver)

    got = await memory_turns.read_round_for_memory(CHAT, 5)
    assert got == {"question": "研究问题", "answer": "研究结果", "finished": True}
    assert await memory_turns.read_round_for_memory("other-chat", 5) is None
    version.status = SessionVersionStatusEnum.IN_PROGRESS
    assert (await memory_turns.read_round_for_memory(CHAT, 5))["finished"] is False
