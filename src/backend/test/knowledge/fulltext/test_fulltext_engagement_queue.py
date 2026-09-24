"""在隔离解释器执行真实 Lua, 避免全局测试桩替换 Redis SDK。"""
import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ISOLATED = os.environ.get("ENGAGEMENT_QUEUE_LUA_TEST") == "1"
if ISOLATED:
    import fakeredis.aioredis
    source = Path(__file__).parents[3] / "bisheng/knowledge/domain/repositories/implementations/knowledge_fulltext_engagement_repository_impl.py"
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.endswith("QueueRepositoryImpl"))
    namespace = dict(KnowledgeFulltextEngagementQueueRepository=object,
                     constants=SimpleNamespace(KNOWLEDGE_FULLTEXT_ENGAGEMENT_DELAY_SECONDS=300,
                                               KNOWLEDGE_FULLTEXT_ENGAGEMENT_LEASE_SECONDS=600))
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    Repository = namespace[node.name]


@pytest.fixture
async def repository():
    if not ISOLATED:
        pytest.skip("由隔离子进程执行 Lua")
    redis = fakeredis.aioredis.FakeRedis()
    yield Repository(redis_client=SimpleNamespace(async_connection=redis))
    await redis.aclose()


async def test_event_during_processing_cannot_steal_lease_and_survives_ack(repository):
    await repository.enqueue_many(file_ids=[11, 11, 12], now_epoch=1000)
    assert await repository.claim(now_epoch=1299, lease_owner="a", limit=10) == []
    assert await repository.claim(now_epoch=1300, lease_owner="a", limit=10) == [11, 12]
    await repository.enqueue(file_id=11, now_epoch=1310)
    assert await repository.claim(now_epoch=1610, lease_owner="b", limit=10) == []
    assert not await repository.ack(file_id=11, lease_owner="b")
    assert await repository.ack_many(file_ids=[11, 12], lease_owner="a") == 2
    assert await repository.claim(now_epoch=1900, lease_owner="b", limit=10) == [11]


@pytest.mark.parametrize("crash", [False, True])
async def test_budget_survives_scans_events_and_new_repository(repository, crash):
    now = 1000
    await repository.enqueue(file_id=11, now_epoch=now - 300)
    for attempt in range(8):
        assert await repository.claim(now_epoch=now, lease_owner="a", limit=10) == [11]
        await repository.enqueue(file_id=11, now_epoch=now)
        if crash:
            assert await repository.reclaim_expired(now_epoch=now + 600) == 1
        else:
            assert await repository.retry(file_id=11, lease_owner="a", now_epoch=now)
        assert await repository.claim(now_epoch=now + 1, lease_owner="b", limit=10) == []
        now += 7200
    fresh = Repository(redis_client=repository.redis_client)
    assert not await fresh.enqueue(file_id=11, now_epoch=now)
    assert await fresh.claim(now_epoch=now + 7200, lease_owner="b", limit=10) == []
    redis = fresh.redis_client.async_connection
    assert await redis.hget(fresh.ATTEMPTS_KEY, "11") == b"8"
    assert await redis.ttl(fresh.DEAD_KEY) == -1
    assert await fresh.restore_dead(file_ids=[11], now_epoch=now) == 1
    assert await fresh.claim(now_epoch=now + 300, lease_owner="c", limit=10) == [11]
    assert not await fresh.ack(file_id=11, lease_owner="a")


async def test_bulk_has_no_total_input_limit(repository):
    assert await repository.enqueue_many(file_ids=list(range(1500)), now_epoch=0) == 1500
    assert len(await repository.claim(now_epoch=300, lease_owner="a", limit=1500)) == 1500
    assert await repository.ack_many(file_ids=list(range(1500)), lease_owner="a") == 1500


def test_isolated_lua_protocol():
    if ISOLATED:
        pytest.skip("不递归启动子进程")
    result = subprocess.run([sys.executable, "-m", "pytest", "--noconftest", str(Path(__file__).resolve()), "-q"],
                            env={**os.environ, "ENGAGEMENT_QUEUE_LUA_TEST": "1"}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
