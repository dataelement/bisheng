"""覆盖 AC: AC-09, AC-12, AC-14, AC-17。真实原子性需要独立测试 Redis。"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from redis import Redis

from bisheng.common.errcode.flow import PlatformKnowledgeExecutionError
from bisheng.workflow.domain.repositories.platform_knowledge_run import KnowledgeRunRepository


def test_stop_and_generation_protect_results_and_events():
    url = os.environ.get("F120_TEST_REDIS_URL")
    if not url:
        pytest.skip("需要独立的 F120 测试 Redis")
    # 全局预加载会替换应用层 Redis 包装。直接使用 redis-py 执行实际 Lua 脚本。
    client = Redis.from_url(url)
    client.ping()
    store = KnowledgeRunRepository("flow", uuid4().hex, 7, 12, client=SimpleNamespace(connection=client))
    keys = [store.key, store.pointer]
    try:
        first = store.create({"graph": {"nodes": []}})
        keys.extend(store.output_keys(first["execution_id"]))
        owner = store.claim(first, resume=False)
        assert owner and store.claim(first, resume=False) is None
        store.commit(first["execution_id"], owner, "node", 0)
        with pytest.raises(PlatformKnowledgeExecutionError):
            store.commit(first["execution_id"], owner, "node", 0)
        assert store.stop(first["execution_id"])
        assert not store.event(first["execution_id"], owner, {"text": "late"})
        with pytest.raises(PlatformKnowledgeExecutionError):
            store.commit(first["execution_id"], owner, "node", 1)
        second = store.create({"graph": {"nodes": []}})
        keys.extend(store.output_keys(second["execution_id"]))
        assert not store.stop(first["execution_id"])
        assert store.claim(second, resume=False)
    finally:
        for key in keys:
            client.delete(key)
        client.close()
