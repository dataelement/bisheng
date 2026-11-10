"""检索运行的 Redis 原子状态与输出保护。"""

import json
import pickle
import time
from uuid import uuid4

from bisheng.common.errcode.flow import PlatformKnowledgeExecutionError
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest

TTL = 7 * 24 * 3600

# 同一会话的状态、引用与事件使用同一 Redis Cluster slot。
_MUTATE = """
local state, pointer, status, events = unpack(KEYS)
local op, id, owner, ttl = ARGV[1], ARGV[2], ARGV[3], tonumber(ARGV[4])
if op == 'create' then
    redis.call('DEL', state)
    redis.call('HSET', state, 'id', id, 'dispatch', ARGV[5], 'state', 'PENDING', 'owner', '')
    redis.call('EXPIRE', state, ttl)
    redis.call('SET', pointer, ARGV[6], 'EX', ttl)
    return 1
end
if redis.call('HGET', state, 'id') ~= id or redis.call('EXISTS', pointer) == 0 then return 0 end
local current = redis.call('HGET', state, 'state')
if op == 'clear' then
    redis.call('DEL', state, pointer)
    return 1
end
if op == 'pop' then
    if current == 'STOPPED' then return false end
    return redis.call('LPOP', events)
end
if current == 'SUCCESS' or current == 'FAILED' or current == 'STOPPED' then return 0 end
if op == 'stop' then
    redis.call('HSET', state, 'state', 'STOPPED')
    redis.call('SET', status, ARGV[5], 'EX', ttl)
    redis.call('DEL', events)
    return 1
end
if op == 'resume' then
    if current ~= 'INPUT' then return 0 end
    redis.call('HSET', state, 'state', 'RESUMING', 'dispatch', ARGV[5], 'owner', '')
    return 1
end
if op == 'claim' then
    if current ~= ARGV[6] or redis.call('HGET', state, 'dispatch') ~= ARGV[5] then return 0 end
    redis.call('HSET', state, 'state', 'RUNNING', 'owner', owner)
    return 1
end
if redis.call('HGET', state, 'owner') ~= owner then return 0 end
if op == 'status' then
    local target = ARGV[5]
    if target == 'WAITING' and current ~= 'PENDING' then return 0 end
    if target == 'INPUT_OVER' and current ~= 'RESUMING' then return 0 end
    if (target == 'RUNNING' or target == 'INPUT' or target == 'SUCCESS') and current ~= 'RUNNING' then
        return 0
    end
    if target == 'INPUT' or target == 'SUCCESS' or target == 'FAILED' then
        redis.call('HSET', state, 'state', target)
    end
    redis.call('SET', status, ARGV[6], 'EX', ttl)
    return 1
end
if current ~= 'RUNNING' or owner == '' then return 0 end
if op == 'check' then return 1 end
if op == 'commit' then
    local step = tonumber(redis.call('HGET', state, ARGV[5]) or '-1')
    if tonumber(ARGV[6]) <= step then return 0 end
    redis.call('HSET', state, ARGV[5], ARGV[6])
    return 1
end
if op == 'event' then
    redis.call('RPUSH', events, ARGV[5])
    redis.call('EXPIRE', events, ttl)
    return 1
end
return 0
"""


class KnowledgeRunRepository:
    def __init__(self, workflow_id, session_id, tenant_id, user_id, *, client=None):
        scope = canonical_digest([workflow_id, session_id, tenant_id, user_id])
        self.key = f"workflow:knowledge:{{{scope}}}"
        self.pointer = f"{self.key}:reference"
        self.client = client if client is not None else get_redis_client_sync()

    def output_keys(self, execution_id):
        prefix = f"{self.key}:{execution_id}"
        return f"{prefix}:status", f"{prefix}:event"

    def execute(self, operation, execution_id, owner="", *args):
        return self.client.connection.eval(
            _MUTATE,
            4,
            self.key,
            self.pointer,
            *self.output_keys(execution_id),
            operation,
            execution_id,
            owner,
            TTL,
            *args,
        )

    def mutate(self, operation, execution_id, owner="", *args):
        return bool(self.execute(operation, execution_id, owner, *args))

    def pop(self, execution_id):
        return self.execute("pop", execution_id)

    def current(self):
        return self.client.get(self.pointer)

    def create(self, record):
        reference = {"execution_id": uuid4().hex, "dispatch_id": uuid4().hex}
        self.mutate(
            "create", reference["execution_id"], "", reference["dispatch_id"], pickle.dumps({**record, **reference})
        )
        return reference

    def claim(self, reference, *, resume):
        owner = uuid4().hex
        if self.mutate(
            "claim", reference["execution_id"], owner, reference["dispatch_id"], "RESUMING" if resume else "PENDING"
        ):
            return owner
        return None

    def resume(self, execution_id):
        dispatch_id = uuid4().hex
        if not self.mutate("resume", execution_id, "", dispatch_id):
            raise PlatformKnowledgeExecutionError()
        return {"execution_id": execution_id, "dispatch_id": dispatch_id}

    def check(self, execution_id, owner):
        if not self.mutate("check", execution_id, owner):
            raise PlatformKnowledgeExecutionError()

    def commit(self, execution_id, owner, node_id, step):
        if not self.mutate("commit", execution_id, owner, f"step:{node_id}", step):
            raise PlatformKnowledgeExecutionError()

    def event(self, execution_id, owner, event):
        return self.mutate("event", execution_id, owner, json.dumps(event, ensure_ascii=False))

    def status(self, execution_id, owner, status, reason=None):
        data = {"status": status, "reason": reason, "time": time.time()}
        return self.mutate("status", execution_id, owner, status, pickle.dumps(data))

    def stop(self, execution_id):
        data = {"status": "FAILED", "reason": "workflow stopped", "time": time.time()}
        return self.mutate("stop", execution_id, "", pickle.dumps(data))

    def clear(self, execution_id):
        return self.mutate("clear", execution_id)
