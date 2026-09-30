"""跨定时调度与重投保留失败预算, 终止状态只能显式恢复。"""

import importlib
import json
import time
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

from loguru import logger

from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.telemetry.domain.mid_table.queue_retry import QueuedProjectionFailure

MAX_ATTEMPTS = 6
LEASE_SECONDS = 300
ACTIVE_BUDGET: ContextVar = ContextVar("telemetry_retry_budget", default=None)
TASK_MODULES = dict.fromkeys(
    (
        "sync_mid_user_daily_participation_fact",
        "backfill_mid_user_daily_participation_fact",
        "sync_mid_knowledge_space_content_stat",
        "sync_pending_knowledge_space_content_stat",
        "sync_pending_knowledge_space_content_events",
        "recover_knowledge_space_content_stat_leases",
    ),
    "bisheng.worker.telemetry.mid_table",
) | {"sync_mid_realtime_qa_question_fact": "bisheng.worker.telemetry.realtime_dashboard"}

ACQUIRE = """
local status = redis.call('hget', KEYS[1], 'status')
if status == 'dead' then return 'dead' end
local now = tonumber(ARGV[2])
if status == 'running' and tonumber(redis.call('hget', KEYS[1], 'lease_until') or 0) > now then
  return 'busy'
end
if tonumber(redis.call('hget', KEYS[1], 'next_at') or 0) > now then return 'backoff' end
local attempt = tonumber(redis.call('hget', KEYS[1], 'attempt') or 0)
if attempt >= tonumber(ARGV[4]) then
  redis.call('hset', KEYS[1], 'status', 'dead', 'last_error', 'worker lease expired', 'updated_at', now)
  return 'dead'
end
if attempt == 0 and redis.call('hget', KEYS[1], 'preserve_context') ~= '1' then
  redis.call('hdel', KEYS[1], 'context', 'invocation')
end
redis.call('hdel', KEYS[1], 'preserve_context')
redis.call('hset', KEYS[1], 'status', 'running', 'owner', ARGV[1], 'attempt', attempt + 1,
  'lease_until', now + tonumber(ARGV[3]), 'updated_at', now)
return 'acquired'
"""
FINISH = """
if redis.call('hget', KEYS[1], 'owner') ~= ARGV[1] or
   redis.call('hget', KEYS[1], 'status') ~= 'running' or
   tonumber(redis.call('hget', KEYS[1], 'lease_until') or 0) <= tonumber(ARGV[2]) then return 0 end
if ARGV[3] == 'renew' then
  redis.call('hset', KEYS[1], 'lease_until', tonumber(ARGV[2]) + tonumber(ARGV[4]))
elseif ARGV[3] == 'busy' then
  redis.call('hincrby', KEYS[1], 'attempt', -1)
  redis.call('hset', KEYS[1], 'status', 'retry', 'preserve_context', '1', 'next_at', tonumber(ARGV[2]) + 30)
elseif ARGV[3] == 'success' then
  redis.call('hset', KEYS[1], 'status', 'success', 'attempt', 0, 'next_at', 0,
    'last_error', '', 'updated_at', ARGV[2])
else
  local attempt = tonumber(redis.call('hget', KEYS[1], 'attempt'))
  local status = 'retry'
  if attempt >= tonumber(ARGV[4]) then status = 'dead' end
  redis.call('hset', KEYS[1], 'status', status, 'next_at', ARGV[5],
    'last_error', ARGV[6], 'updated_at', ARGV[2])
end
return 1
"""
RESET = """
if redis.call('hget', KEYS[1], 'status') == 'running' and
   tonumber(redis.call('hget', KEYS[1], 'lease_until') or 0) > tonumber(ARGV[1]) then return 0 end
redis.call('hset', KEYS[1], 'status', 'ready', 'attempt', 0, 'next_at', 0,
  'owner', '', 'preserve_context', '1', 'updated_at', ARGV[1])
return 1
"""
STORE = """
if redis.call('hget', KEYS[1], 'owner') ~= ARGV[1] or
   redis.call('hget', KEYS[1], 'status') ~= 'running' or
   tonumber(redis.call('hget', KEYS[1], 'lease_until') or 0) <= tonumber(ARGV[2]) then return 0 end
redis.call('hset', KEYS[1], ARGV[3], ARGV[4])
return 1
"""
RECOVER = """
local now = tonumber(ARGV[1])
local status = redis.call('hget', KEYS[1], 'status')
if status ~= 'retry' and status ~= 'ready' and status ~= 'running' then return 0 end
if status == 'running' and tonumber(redis.call('hget', KEYS[1], 'lease_until') or 0) > now then return 0 end
if tonumber(redis.call('hget', KEYS[1], 'next_at') or 0) > now or
   tonumber(redis.call('hget', KEYS[1], 'dispatch_until') or 0) > now then return 0 end
redis.call('hset', KEYS[1], 'dispatch_until', now + 300)
return 1
"""


class RunBudget:
    def __init__(self, name: str):
        self.key = f"telemetry:{{bounded_jobs}}:{name}"
        self.owner = uuid4().hex
        redis = get_redis_client_sync()
        redis.cluster_nodes(self.key)
        self.connection = redis.connection

    @staticmethod
    def _now(now):
        return int(time.time() if now is None else now)

    def acquire(self, now=None) -> str:
        value = self.connection.eval(ACQUIRE, 1, self.key, self.owner, self._now(now), LEASE_SECONDS, MAX_ATTEMPTS)
        return value.decode() if isinstance(value, bytes) else value

    def status(self) -> dict:
        return {
            (key.decode() if isinstance(key, bytes) else key): (value.decode() if isinstance(value, bytes) else value)
            for key, value in self.connection.hgetall(self.key).items()
        }

    def renew(self, now=None):
        if not self.connection.eval(FINISH, 1, self.key, self.owner, self._now(now), "renew", LEASE_SECONDS):
            raise RuntimeError("Telemetry task lease lost")

    def succeed(self, now=None):
        if not self.connection.eval(FINISH, 1, self.key, self.owner, self._now(now), "success", 0):
            raise RuntimeError("Telemetry task lease lost")

    def fail(self, error: str, now=None) -> int:
        attempt = int(self.status().get("attempt", 1))
        delay = min(900, 30 * 2 ** min(attempt - 1, 5))
        if not self.connection.eval(
            FINISH,
            1,
            self.key,
            self.owner,
            self._now(now),
            "failure",
            MAX_ATTEMPTS,
            self._now(now) + delay,
            error[:2000],
        ):
            raise RuntimeError("Telemetry task lease lost while recording failure")
        return delay

    def reset(self, now=None) -> bool:
        return bool(self.connection.eval(RESET, 1, self.key, self._now(now)))

    def defer(self):
        if not self.connection.eval(FINISH, 1, self.key, self.owner, self._now(None), "busy", 0):
            raise RuntimeError("Telemetry task lease lost")

    def store(self, field, value):
        if not self.connection.eval(STORE, 1, self.key, self.owner, self._now(None), field, value):
            raise RuntimeError("Telemetry task lease lost")


def checkpoint() -> None:
    budget = ACTIVE_BUDGET.get()
    if budget:
        budget.renew()


def frozen_value(name, factory):
    """同一失败链固定日期窗口, 跨天重试或人工重放不能悄悄跳过原数据。"""
    budget = ACTIVE_BUDGET.get()
    if not budget:
        return factory()
    budget.renew()
    context = json.loads(budget.status().get("context", "{}"))
    if name not in context:
        context[name] = factory()
        budget.store("context", json.dumps(context))
    return context[name]


def recover_due_jobs(dispatch=None):
    """补偿重试消息投递失败或执行进程退出; 终止记录始终排除。"""
    recovered = []
    for name, module in TASK_MODULES.items():
        if name == "recover_knowledge_space_content_stat_leases":
            continue
        budget = RunBudget(name)
        if not budget.connection.eval(RECOVER, 1, budget.key, budget._now(None)):
            continue
        invocation = json.loads(budget.status().get("invocation", "{}"))
        if dispatch:
            dispatch(name, invocation)
        else:
            getattr(importlib.import_module(module), name).apply_async(
                args=invocation.get("args", []), kwargs=invocation.get("kwargs", {})
            )
        recovered.append(name)
    return recovered


def bounded_telemetry_task(function):
    @wraps(function)
    def run(*args, **kwargs):
        budget = RunBudget(function.__name__)
        state = budget.acquire()
        if state != "acquired":
            logger.warning("telemetry.task.skipped task={} reason={}", function.__name__, state)
            return {"degraded": True, "retry_state": state}
        token = ACTIVE_BUDGET.set(budget)
        try:
            invocation = budget.status().get("invocation")
            if invocation:
                saved = json.loads(invocation)
                args, kwargs = saved["args"], saved["kwargs"]
            else:
                budget.store("invocation", json.dumps({"args": args, "kwargs": kwargs}))
            result = function(*args, **kwargs)
            if isinstance(result, dict) and result.get("failure_stage") == "owner_lock":
                budget.defer()
                try:
                    function.__globals__[function.__name__].apply_async(args=args, kwargs=kwargs, countdown=30)
                except Exception:
                    logger.exception("telemetry.task.defer_publish_failed task={}", function.__name__)
                return result
            budget.succeed()
            logger.info("telemetry.task.completed task={} result={}", function.__name__, result)
            return result
        except QueuedProjectionFailure:
            # 工作项已有独立预算, 不能让一条坏记录熔断整个队列。
            budget.succeed()
            raise
        except Exception as exc:
            delay = budget.fail(f"{type(exc).__name__}: {exc}")
            state = budget.status()
            logger.exception("telemetry.task.failed task={} state={}", function.__name__, state)
            if state["status"] != "dead":
                task = function.__globals__[function.__name__]
                try:
                    task.apply_async(args=args, kwargs=kwargs, countdown=delay)
                except Exception:
                    logger.exception("telemetry.task.retry_publish_failed task={}", function.__name__)
            raise
        finally:
            ACTIVE_BUDGET.reset(token)

    return run
