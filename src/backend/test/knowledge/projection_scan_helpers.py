"""编排测试的内存状态连接; Lua 协议另用 fakeredis 验证。"""

import pytest


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.locks = set()

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value
        return True

    async def eval(self, script, count, key, before, after, ttl):
        if self.values.get(key, "") != before:
            return 0
        self.values[key] = after
        return 1

    def lock(self, key, **kwargs):
        parent = self

        class Lock:
            async def acquire(self):
                if key in parent.locks:
                    return False
                parent.locks.add(key)
                return True

            async def owned(self):
                return key in parent.locks

            async def release(self):
                parent.locks.remove(key)

        return Lock()


@pytest.fixture
def scan_state(monkeypatch):
    from bisheng.worker.knowledge._projection_scan_state import ProjectionScanState

    clock = [1000.0]
    state = ProjectionScanState(MemoryRedis(), 7, now=lambda: clock[0])
    state.clock = clock

    async def create(tenant_id):
        assert tenant_id == 7
        return state

    monkeypatch.setattr(ProjectionScanState, "create", create)
    return state
