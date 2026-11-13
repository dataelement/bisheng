"""Audit and metrics (AC-101, AC-102, AC-103)."""

import uuid
from datetime import datetime

from sqlmodel import select

from bisheng.memory.domain.models.memory_item import MemoryItem
from bisheng.memory.domain.models.memory_metric_daily import MemoryMetricDaily
from bisheng.memory.domain.repositories import _db
from bisheng.memory.domain.services import metrics as m
from bisheng.memory.domain.services.audit import ACTIONS, MemoryAudit
from bisheng.memory.domain.services.metrics import MemoryMetrics
from test.memory.conftest import TENANT_A, TENANT_B, USER_1


class FakeAuditWriter:
    def __init__(self):
        self.rows = []

    async def __call__(self, **kwargs):
        self.rows.append(kwargs)


async def test_ac101_audit_records_operator_time_action_without_content(make_ctx):
    writer = FakeAuditWriter()
    audit = MemoryAudit(writer=writer)
    ctx = make_ctx()
    await audit.record(ctx, "delete", item_ids=["i1"], operator_id=USER_1)
    row = writer.rows[0]
    assert row["action"] == "memory.item.delete"
    assert row["operator_id"] == USER_1 and row["tenant_id"] == TENANT_A
    assert row["metadata"] == {"item_ids": ["i1"], "scene": ctx.scene}
    assert "content" not in str(row["metadata"])


def test_ac101_actions_not_visible_to_admin_audit_page():
    from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS

    assert all(a.startswith("memory.item.") for a in ACTIONS.values())
    assert not set(ACTIONS.values()) & set(_UI_VISIBLE_V2_ACTIONS)


async def test_audit_failure_does_not_raise(make_ctx):
    async def broken(**_):
        raise RuntimeError("db down")

    await MemoryAudit(writer=broken).record(make_ctx(), "add", item_ids=["x"], operator_id=USER_1)


def _item(ctx, **kw):
    return MemoryItem(
        id=str(uuid.uuid4()),
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        type="fact",
        content="c",
        recorded_at=datetime(2026, 11, 1),
        origin="explicit",
        source_scene="daily",
        **kw,
    )


async def test_ac102_counters_increment_and_flush_split_by_tenant_scene_app(memory_db, kv, make_ctx):
    metrics = MemoryMetrics(kv)
    a = make_ctx(scene="assistant", app_id="asst-1")
    b = make_ctx(tenant_id=TENANT_B, scene="daily")
    for name in m.ALL_COUNTERS:
        await metrics.incr(a, name)
    await metrics.incr(a, m.ADDED_EXPLICIT, 2)
    await metrics.incr(b, m.ADDED_AUTO)
    await metrics.flush(day="2026-11-13")
    async with _db.async_session() as s:
        rows = (await s.exec(select(MemoryMetricDaily))).all()
    by_key = {(r.tenant_id, r.scene, r.app_id, r.metric): r.value for r in rows}
    assert by_key[(TENANT_A, "assistant", "asst-1", m.ADDED_EXPLICIT)] == 3
    assert by_key[(TENANT_B, "daily", "", m.ADDED_AUTO)] == 1
    assert {r.metric for r in rows if r.tenant_id == TENANT_A} == set(m.ALL_COUNTERS)
    # flushing twice in a day accumulates, Redis was drained
    await metrics.incr(a, m.ADDED_EXPLICIT)
    await metrics.flush(day="2026-11-13")
    async with _db.async_session() as s:
        row = (
            await s.exec(
                select(MemoryMetricDaily).where(
                    MemoryMetricDaily.tenant_id == TENANT_A, MemoryMetricDaily.metric == m.ADDED_EXPLICIT
                )
            )
        ).first()
    assert row.value == 4


async def test_ac102_read_sets_update_item_columns(memory_db, kv, make_ctx):
    metrics = MemoryMetrics(kv)
    ctx = make_ctx()
    items = [_item(ctx, detail_object_key=f"k{i}") for i in range(4)]
    async with _db.async_session() as s:
        for it in items:
            s.add(it)
        await s.commit()
    await metrics.mark_read(ctx, [items[0].id, items[1].id])
    await metrics.mark_detail_read(ctx, [items[0].id])
    await metrics.flush(day="2026-11-13")
    assert await metrics.count_never_read(TENANT_A) == 2
    assert await metrics.detail_read_ratio(TENANT_A) == 0.25


async def test_ac103_metric_table_has_no_content_columns():
    columns = set(MemoryMetricDaily.__table__.c.keys())
    assert columns == {"id", "day", "tenant_id", "scene", "app_id", "metric", "value"}
