"""Real Redis acceptance: checkpoint recovery and session tasks never enumerate the DB."""

import os
import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from redis.asyncio import Redis

from bisheng.linsight.domain.models.linsight_execute_task import LinsightExecuteTask
from bisheng.linsight.domain.services import state_message_manager as state
from bisheng.linsight.domain.services.checkpoint_index_backfill import backfill_checkpoint_indexes
from bisheng.linsight.domain.services.checkpointer import PlainRedisCheckpointer


@pytest.fixture
async def redis_indexes():
    url = os.getenv("TEST_TASK_REDIS_URL")
    if not url:
        pytest.skip("TEST_TASK_REDIS_URL enables isolated Redis acceptance")
    redis = Redis.from_url(url)
    token = uuid4().hex
    try:
        yield redis, token
    finally:
        keys = [key async for key in redis.scan_iter(match=f"*{token}*", count=500)]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


def saver_for(redis):
    saver = PlainRedisCheckpointer(ttl_seconds=120)
    saver._get_redis_client = AsyncMock(
        return_value=SimpleNamespace(async_connection=redis, async_pipeline=redis.pipeline)
    )
    return saver


async def test_checkpoint_roundtrip_and_concurrent_pending_writes_without_scan(redis_indexes, monkeypatch):
    redis, token = redis_indexes
    saver = saver_for(redis)
    config = {"configurable": {"thread_id": token, "checkpoint_ns": "agent:child"}}
    next_config = await saver.aput(config, empty_checkpoint(), {"source": "input", "step": 0}, {})
    import asyncio

    await asyncio.gather(
        saver.aput_writes(next_config, [("messages", "one")], "task:汉字"),
        saver.aput_writes(next_config, [("messages", "two")], "task-2"),
    )
    # Re-delivery overwrites one task/index instead of duplicating it.
    await saver.aput_writes(next_config, [("messages", "one-new")], "task:汉字")

    def forbidden(*args, **kwargs):
        raise AssertionError("Checkpoint reads must not scan unrelated keys")

    with monkeypatch.context() as patch:
        patch.setattr(redis, "scan_iter", forbidden)
        patch.setattr(redis, "keys", forbidden)
        result = await saver.aget_tuple(next_config)
        assert {tuple(item) for item in result.pending_writes} == {
            ("task:汉字", "messages", "one-new"),
            ("task-2", "messages", "two"),
        }
        assert len([item async for item in saver.alist(config)]) == 1
    index = saver._writes_key(token, "agent:child", next_config["configurable"]["checkpoint_id"])
    assert 0 < await redis.ttl(index) <= 120


async def test_legacy_backfill_is_readonly_by_default_resumable_and_preserves_payload_ttl(redis_indexes):
    redis, token = redis_indexes
    saver = saver_for(redis)
    config = await saver.aput({"configurable": {"thread_id": token}}, empty_checkpoint(), {"step": 0}, {})
    await saver.aput_writes(config, [("messages", "legacy value")], "old-task")
    cid = config["configurable"]["checkpoint_id"]
    index = saver._writes_key(token, "", cid)
    write = saver._write_key(token, "", cid, "old-task", 0)
    before = await redis.hgetall(write)
    ttl = await redis.pttl(write)
    await redis.delete(index)
    with pytest.raises(RuntimeError, match="backfill"):
        await saver.aget_tuple(config)
    counts = await backfill_checkpoint_indexes(redis)
    assert counts["writes"] >= 1
    assert not await redis.exists(index)
    for _ in range(2):
        await backfill_checkpoint_indexes(redis, apply=True)
        result = await saver.aget_tuple(config)
        assert result.pending_writes == [("old-task", "messages", "legacy value")]
    assert await redis.hgetall(write) == before
    assert 0 < await redis.pttl(write) <= ttl
    assert 0 < await redis.pttl(index) <= 120000


async def test_backfill_handles_empty_legacy_checkpoint(redis_indexes):
    redis, token = redis_indexes
    saver = saver_for(redis)
    config = await saver.aput({"configurable": {"thread_id": token}}, empty_checkpoint(), {}, {})
    await redis.delete(saver._writes_key(token, "", config["configurable"]["checkpoint_id"]))
    await backfill_checkpoint_indexes(redis, apply=True)
    assert (await saver.aget_tuple(config)).pending_writes == []


class TaskCache:
    def __init__(self, redis):
        self.async_connection = redis
        self.async_pipeline = redis.pipeline

    async def aget(self, key):
        value = await self.async_connection.get(key)
        return pickle.loads(value) if value is not None else None

    async def adelete(self, *keys):
        return await self.async_connection.delete(*keys)


def task(token, number, history=None):
    return LinsightExecuteTask(
        id=f"{token}-{number}",
        session_version_id=token,
        task_type="single",
        task_data={"name": str(number)},
        history=history or [],
        tenant_id=1,
    )


def manager_for(redis, token, monkeypatch):
    monkeypatch.setattr(state, "get_redis_client_sync", lambda: TaskCache(redis))
    return state.LinsightStateMessageManager(token)


async def test_legacy_task_index_uses_sql_ids_but_preserves_newer_redis_history(redis_indexes, monkeypatch):
    redis, token = redis_indexes
    manager = manager_for(redis, token, monkeypatch)
    a, b = task(token, 1), task(token, 2)
    cached = a.model_copy(update={"history": [{"text": "unflushed thinking"}]})
    await redis.set(manager._keys["execution_tasks"] + a.id, pickle.dumps(cached.model_dump()), ex=120)
    query = AsyncMock(return_value=[a, b])
    monkeypatch.setattr(state.LinsightExecuteTaskDao, "get_by_session_version_id", query)
    monkeypatch.setattr(state.LinsightExecuteTaskDao, "get_by_id", AsyncMock(return_value=b))
    no_scan = AsyncMock(side_effect=AssertionError("Task listing must not enumerate Redis keys"))
    monkeypatch.setattr(redis, "keys", no_scan)
    monkeypatch.setattr(redis, "scan", no_scan)
    result = await manager.get_execution_tasks()
    assert {row.id for row in result} == {a.id, b.id}
    assert next(row for row in result if row.id == a.id).history == cached.history
    again = await manager.get_execution_tasks()
    assert len(again) == 2
    query.assert_awaited_once()
    no_scan.assert_not_awaited()
    monkeypatch.undo()


async def test_task_index_includes_new_tasks_and_cleanup_is_scoped(redis_indexes, monkeypatch):
    redis, token = redis_indexes
    manager = manager_for(redis, token, monkeypatch)
    monkeypatch.setattr(state.LinsightExecuteTaskDao, "get_by_session_version_id", AsyncMock(return_value=[]))
    a, b = task(token, 1), task(token, 2)
    await manager.set_execution_tasks([a])
    assert [row.id for row in await manager.get_execution_tasks()] == [a.id]
    await manager.set_execution_tasks([b])
    assert {row.id for row in await manager.get_execution_tasks()} == {a.id, b.id}
    unrelated = f"other:{token}"
    await redis.set(unrelated, "keep")
    await manager.cleanup_session_data()
    assert not await redis.exists(manager._keys["task_ids"])
    assert not await redis.exists(manager._keys["execution_tasks"] + a.id)
    assert await redis.get(unrelated) == b"keep"


async def test_real_langgraph_interrupt_resumes_in_another_worker_without_scan(redis_indexes, monkeypatch):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt
    from typing_extensions import TypedDict

    redis, token = redis_indexes

    class AnswerState(TypedDict):
        answer: str

    def collect_answer(_):
        return {"answer": interrupt("Confirm the task")}

    builder = StateGraph(AnswerState)
    builder.add_node("collect", collect_answer)
    builder.add_edge(START, "collect")
    builder.add_edge("collect", END)
    config = {"configurable": {"thread_id": token}}
    first_worker = builder.compile(checkpointer=saver_for(redis))
    parked = await first_worker.ainvoke({"answer": ""}, config)
    assert parked["__interrupt__"]

    def forbidden(*args, **kwargs):
        raise AssertionError("Resuming a task must only read its own indexes")

    # New saver represents another process restoring the parked conversation.
    other_worker = builder.compile(checkpointer=saver_for(redis))
    with monkeypatch.context() as patch:
        patch.setattr(redis, "scan_iter", forbidden)
        patch.setattr(redis, "keys", forbidden)
        completed = await other_worker.ainvoke(Command(resume="confirmed"), config)
    assert completed["answer"] == "confirmed"


async def test_interrupted_backfill_never_marks_partial_inventory_complete(redis_indexes, monkeypatch):
    redis, token = redis_indexes
    saver = saver_for(redis)
    config = await saver.aput({"configurable": {"thread_id": token}}, empty_checkpoint(), {}, {})
    await saver.aput_writes(config, [("messages", "preserve")], "task")
    index = saver._writes_key(token, "", config["configurable"]["checkpoint_id"])
    await redis.delete(index)
    original = redis.scan_iter

    async def interrupted(*args, **kwargs):
        async for key in original(*args, **kwargs):
            yield key
            if token.encode() in key:
                raise RuntimeError("injected interruption")

    with monkeypatch.context() as patch:
        patch.setattr(redis, "scan_iter", interrupted)
        with pytest.raises(RuntimeError, match="injected interruption"):
            await backfill_checkpoint_indexes(redis, apply=True)
    with pytest.raises(RuntimeError, match="backfill"):
        await saver.aget_tuple(config)
    await backfill_checkpoint_indexes(redis, apply=True)
    assert (await saver.aget_tuple(config)).pending_writes == [("task", "messages", "preserve")]
