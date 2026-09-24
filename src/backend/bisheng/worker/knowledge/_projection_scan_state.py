"""投影兜底扫描的持久化游标、投递预占和有限恢复预算。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

logger = logging.getLogger(__name__)
QUEUED_SECONDS = 1800
RUNNING_SECONDS = 180
IO_TIMEOUT = 5

# 单键 CAS 兼容 Redis Cluster; 不使用跨 slot 事务。
_CAS = """
local current = redis.call('GET', KEYS[1]) or ''
if current ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2])
if tonumber(ARGV[3]) > 0 then redis.call('EXPIRE', KEYS[1], ARGV[3]) end
return 1
"""


class ProjectionScanState:
    def __init__(self, redis: Any, tenant_id: int, *, now: Callable[[], float] = time.time):
        self.redis = redis
        self.tenant_id = int(tenant_id)
        self.now = now

    @classmethod
    async def create(cls, tenant_id: int) -> ProjectionScanState:
        from bisheng.core.cache.redis_manager import get_redis_client

        client = await asyncio.wait_for(get_redis_client(), IO_TIMEOUT)
        return cls(client.async_connection, tenant_id)

    def key(self, kind: str, object_id: int | str) -> str:
        return f"document_projection:scan:v1:{self.tenant_id}:{kind}:{object_id}"

    async def _change(self, key: str, transform: Callable[[dict], dict | None], *, ttl: int = 0) -> dict | None:
        for _ in range(20):
            raw = await asyncio.wait_for(self.redis.get(key), IO_TIMEOUT)
            before = json.loads(raw) if raw else {}
            after = transform(before)
            if after is None:
                return None
            changed = await asyncio.wait_for(
                self.redis.eval(_CAS, 1, key, raw or "", json.dumps(after), ttl),
                IO_TIMEOUT,
            )
            if changed:
                return after
        raise RuntimeError(f"projection scan state contention: {key}")

    async def reserve(self, kind: str, object_id: int, fingerprint: str, *, max_attempts: int = 0) -> dict | None:
        token = uuid.uuid4().hex

        def change(old: dict) -> dict | None:
            now = self.now()
            if float(old.get("until", 0)) > now:
                return None
            if old.get("fingerprint") != fingerprint:
                old = {"attempts": 0, "fingerprint": fingerprint}
            if max_attempts and int(old["attempts"]) >= max_attempts:
                if old.get("status") == "exhausted":
                    return None
                logger.warning(
                    "projection scan recovery exhausted tenant_id=%s kind=%s id=%s attempts=%s",
                    self.tenant_id,
                    kind,
                    object_id,
                    old["attempts"],
                )
                return {**old, "status": "exhausted", "token": "", "until": 0}
            if float(old.get("next_at", 0)) > now:
                return None
            return {
                **old,
                "token": token,
                "status": "queued",
                "until": now + QUEUED_SECONDS,
                "attempts": int(old["attempts"]) + 1 if max_attempts else 0,
                "max_attempts": max_attempts,
            }

        # 恢复预算不设 TTL, 避免耗尽后自动清零。普通投影沿用数据库失败预算。
        result = await self._change(self.key(kind, object_id), change, ttl=0 if max_attempts else 86400)
        if result is None or result.get("token") != token:
            return None
        return {"tenant_id": self.tenant_id, "kind": kind, "object_id": int(object_id), "token": token}

    def _ticket_key(self, ticket: dict) -> str:
        if int(ticket["tenant_id"]) != self.tenant_id:
            raise ValueError("projection scan ticket tenant mismatch")
        return self.key(ticket["kind"], int(ticket["object_id"]))

    async def _owned_change(self, ticket: dict, change: Callable[[dict], dict | None]) -> dict | None:
        def transform(old: dict) -> dict | None:
            if old.get("token") != ticket["token"] or float(old.get("until", 0)) <= self.now():
                return None
            return change(old)

        return await self._change(
            self._ticket_key(ticket), transform, ttl=86400 if ticket["kind"] == "projection" else 0
        )

    async def start(self, ticket: dict) -> bool:
        return bool(
            await self._owned_change(
                ticket,
                lambda old: (
                    {
                        **old,
                        "status": "running",
                        "until": self.now() + RUNNING_SECONDS,
                    }
                    if old.get("status") == "queued"
                    else None
                ),
            )
        )

    async def renew(self, ticket: dict) -> bool:
        return bool(
            await self._owned_change(
                ticket,
                lambda old: (
                    {
                        **old,
                        "until": self.now() + RUNNING_SECONDS,
                    }
                    if old.get("status") == "running"
                    else None
                ),
            )
        )

    async def finish(self, ticket: dict, *, error: str = "", progress: str | None = None) -> bool:
        def change(old: dict) -> dict:
            attempts = int(old["attempts"])
            if progress is not None and old.get("progress") not in (None, progress):
                attempts = 0
            exhausted = old["max_attempts"] and attempts >= old["max_attempts"]
            if exhausted:
                logger.warning(
                    "projection scan recovery exhausted tenant_id=%s kind=%s id=%s attempts=%s error=%s",
                    self.tenant_id,
                    ticket["kind"],
                    ticket["object_id"],
                    attempts,
                    error[:500],
                )
            return {
                **old,
                "token": "",
                "until": 0,
                "attempts": attempts,
                "status": "exhausted" if exhausted else "waiting",
                "next_at": self.now() + min(300 * 2 ** max(attempts - 1, 0), 3600),
                "error": error[:500],
                "progress": progress,
            }

        return bool(await self._owned_change(ticket, change))

    async def cursor(self, scope: str = "tenant") -> dict:
        raw = await asyncio.wait_for(self.redis.get(self.key("cursor", scope)), IO_TIMEOUT)
        return json.loads(raw) if raw else {}

    async def save_cursor(self, cursor: dict, scope: str = "tenant") -> None:
        await asyncio.wait_for(self.redis.set(self.key("cursor", scope), json.dumps(cursor)), IO_TIMEOUT)


async def run_reserved(
    state: ProjectionScanState,
    tickets: list[dict],
    work: Callable[[list[dict], dict], Awaitable[Any]],
) -> Any:
    """只执行本次成功接管的预占, 运行期间续租; 租约失效则停止异步流程。"""
    active = []
    progress = {}

    async def claim(ticket: dict) -> None:
        if await state.start(ticket):
            active.append(ticket)

    async def execute() -> Any:
        # 大批次不能在全部接管完成后才启动续租, 否则首批票据可能先过期。
        for offset in range(0, len(tickets), 32):
            results = await asyncio.gather(
                *(claim(ticket) for ticket in tickets[offset : offset + 32]), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        if not active:
            return {"status": "skipped", "total": 0}
        return await work(active, progress)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(30)
            snapshot = list(active)
            for offset in range(0, len(snapshot), 32):
                results = await asyncio.gather(
                    *(state.renew(ticket) for ticket in snapshot[offset : offset + 32]),
                    return_exceptions=True,
                )
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
                    if not result:
                        raise RuntimeError("projection scan recovery lease lost")

    action = asyncio.create_task(execute())
    renewal = asyncio.create_task(heartbeat())
    error = ""
    try:
        done, _ = await asyncio.wait((action, renewal), timeout=1800, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise TimeoutError("projection scan recovery exceeded 1800 seconds")
        if renewal in done:
            await renewal
        return await action
    except Exception as exc:
        error = str(exc)
        logger.exception(
            "projection scan recovery failed tenant_id=%s total=%s sample=%s", state.tenant_id, len(active), active[:5]
        )
        return {"status": "failed", "error": error}
    finally:
        for task in (action, renewal):
            task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await task
            except Exception:
                # 同时失败的子任务也必须回收异常, 防止清理覆盖已记录的执行结果。
                if not error:
                    logger.exception("projection scan task cleanup failed")
        for offset in range(0, len(active), 32):
            results = await asyncio.gather(
                *(
                    state.finish(ticket, error=error, progress=progress.get("fingerprint"))
                    for ticket in active[offset : offset + 32]
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    # 工作已结束, 结算失败时保留预占等待过期恢复, 不影响其他票据结算。
                    logger.error(
                        "projection scan reservation settlement failed tenant_id=%s error=%r", state.tenant_id, result
                    )
