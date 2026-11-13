"""Scheduled memory tasks (AC-43, AC-102)."""

import time
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from bisheng.memory.domain.config import MemoryRuntimeConfig
from bisheng.memory.domain.models.memory_item import INDEX_OK, MemoryItem
from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily
from bisheng.memory.domain.models.memory_session_cursor import MemorySessionCursor
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.reconcile import reconcile_tenant
from bisheng.worker.memory import tasks
from test.memory.conftest import TENANT_A, TENANT_B, USER_1, USER_2


@pytest.fixture
def config(monkeypatch):
    holder = {"cfg": MemoryRuntimeConfig()}

    async def _load():
        return holder["cfg"]

    monkeypatch.setattr(tasks, "aget_memory_config", _load)
    return holder


def _due(memory_db, chat_id, tenant_id, user_id, minutes_ago):
    with memory_db.session() as s:
        s.add(
            MemorySessionCursor(
                chat_id=chat_id,
                tenant_id=tenant_id,
                user_id=user_id,
                state="pending",
                last_activity_at=datetime.now() - timedelta(minutes=minutes_ago),
                last_message_id=5,
            )
        )
        s.commit()


async def test_scan_enumerates_across_tenants_and_dispatches_with_header(memory_db, kv, config):
    _due(memory_db, "a", TENANT_A, USER_1, 60)
    _due(memory_db, "b", TENANT_B, USER_2, 60)
    _due(memory_db, "c", TENANT_A, USER_2, 5)  # still in quiet period
    sent = []
    await tasks.scan(kv, publish=lambda t, u: sent.append((t, u)))
    assert sorted(sent) == [(TENANT_A, USER_1), (TENANT_B, USER_2)]


def test_publish_uses_tenant_header(monkeypatch):
    calls = []
    monkeypatch.setattr(tasks.consolidate_memory_user, "apply_async", lambda **kw: calls.append(kw))
    tasks.publish_consolidation(TENANT_B, USER_1)
    assert calls == [{"args": [TENANT_B, USER_1], "headers": {"tenant_id": TENANT_B}}]


async def test_ac43_quiet_period_and_scan_interval_follow_config(memory_db, kv, config):
    _due(memory_db, "a", TENANT_A, USER_1, 10)
    sent = []
    await tasks.scan(kv, publish=lambda t, u: sent.append((t, u)))
    assert sent == []
    config["cfg"] = MemoryRuntimeConfig(quiet_minutes=5, scan_interval_minutes=5)
    await tasks.scan(kv, publish=lambda t, u: sent.append((t, u)))
    assert sent == []  # within the scan interval of the previous run
    await kv.delete(tasks.SCAN_MARK_KEY)
    await tasks.scan(kv, publish=lambda t, u: sent.append((t, u)))
    assert sent == [(TENANT_A, USER_1)]


async def test_ac43_auto_consolidation_switch_off(memory_db, kv, config):
    _due(memory_db, "a", TENANT_A, USER_1, 60)
    config["cfg"] = MemoryRuntimeConfig(auto_consolidation_enabled=False)
    sent = []
    await tasks.scan(kv, publish=lambda t, u: sent.append((t, u)))
    assert sent == []


async def test_reconcile_pending_model_change_and_orphans(memory_db, service, make_ctx, index, details):
    ctx = make_ctx()
    index.write_fail = True
    pending = await service.write(ctx, "remember", content="用户在学法语", type="fact")
    index.write_fail = False
    ok = await service.write(ctx, "remember", content="用户在学德语", type="fact", detail="德语学习计划全文")
    details.objects[f"memory/{ctx.tenant_id}/{ctx.user_id}/orphan.md"] = "孤儿对象"
    orphan = f"memory/{ctx.tenant_id}/{ctx.user_id}/orphan.md"
    index.model_id = "emb-2"  # tenant switched embedding model
    await reconcile_tenant(TENANT_A, service)
    async with _db.async_session() as s:
        rows = {i.id: i for i in (await s.exec(select(MemoryItem))).all()}
    assert rows[pending.item_id].index_state == INDEX_OK
    assert rows[ok.item_id].index_model_id == "emb-2" and rows[ok.item_id].index_state == INDEX_OK
    # First sighting only marks the orphan: it may be a detail whose row has not committed yet.
    assert orphan in details.objects
    await service.kv.set(f"memory:orphan:{orphan}", str(time.time() - 3601))
    await reconcile_tenant(TENANT_A, service)
    assert orphan not in details.objects
    assert rows[ok.item_id].detail_object_key in details.objects


async def test_flush_metrics_task(memory_db, kv, make_ctx):
    metrics = m.MemoryMetrics(kv)
    await metrics.incr(make_ctx(), m.ADDED_AUTO, 3)
    await tasks.flush_metrics(metrics)
    async with _db.async_session() as s:
        rows = (await s.exec(select(MemoryMetricDaily))).all()
    assert [(r.metric, r.value) for r in rows] == [(m.ADDED_AUTO, 3)]


async def test_cleanup_task(memory_db, make_ctx):
    from sqlalchemy import update

    from bisheng.memory.domain.models.memory_turn_record import MemoryTurnRecord
    from bisheng.memory.domain.services.turn_record import TurnRecordService

    await TurnRecordService.add_retrieved(make_ctx(turn_id="t1"), ["x"])
    async with _db.async_session() as s:
        await s.exec(update(MemoryTurnRecord).values(create_time=datetime.now() - timedelta(days=3)))
        await s.commit()
    assert await tasks.cleanup_turn_records() == 1


async def test_per_tenant_tasks_set_tenant_context(memory_db, monkeypatch):
    from bisheng.core.context.tenant import get_current_tenant_id

    seen = []

    async def work(tenant_id):
        seen.append((tenant_id, get_current_tenant_id()))

    monkeypatch.setattr(tasks, "_tenant_ids", lambda: _ids())

    async def _ids():
        return [TENANT_A, TENANT_B]

    await tasks.for_each_tenant(work)
    assert seen == [(TENANT_A, TENANT_A), (TENANT_B, TENANT_B)]


def test_beat_schedule_registered_by_name():
    from bisheng.core.config.settings import CeleryConf

    conf = CeleryConf()
    conf.validate()
    names = {v["task"] for v in conf.beat_schedule.values()}
    assert {
        "bisheng.worker.memory.tasks.scan_memory_sessions",
        "bisheng.worker.memory.tasks.reconcile_memory",
        "bisheng.worker.memory.tasks.flush_memory_metrics",
        "bisheng.worker.memory.tasks.cleanup_memory_turns",
    } <= names
