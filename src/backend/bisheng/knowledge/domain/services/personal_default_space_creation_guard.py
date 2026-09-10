"""默认个人库创建的跨进程互斥保护。"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from bisheng.common.errcode.knowledge_space import PersonalDefaultSpaceCreationBusyError
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_lock_repository_impl import (
    KnowledgeMigrationLockRepositoryImpl,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class PersonalDefaultSpaceCreationGuard:
    WAIT_SECONDS = 30
    TTL_SECONDS = 60
    RENEW_SECONDS = 10
    IO_TIMEOUT_SECONDS = 5
    POLL_SECONDS = 0.1

    def __init__(self, tenant_id: int, user_id: int) -> None:
        self.key = f"knowledge:personal-default:create:{int(tenant_id)}:{int(user_id)}"
        # 复用已有令牌比较协议, 使用独立 key, 不占用迁移全局锁。
        self.repository = KnowledgeMigrationLockRepositoryImpl(key=self.key)

    async def _acquire(self, token: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.WAIT_SECONDS
        try:
            while (remaining := deadline - loop.time()) > 0:
                acquired = await asyncio.wait_for(
                    self.repository.acquire(token, ttl_seconds=self.TTL_SECONDS),
                    timeout=min(remaining, self.IO_TIMEOUT_SECONDS),
                )
                if acquired:
                    return
                await asyncio.sleep(min(self.POLL_SECONDS, max(0, deadline - loop.time())))
        except Exception as exc:
            logger.exception("Personal default space lock acquisition failed key=%s", self.key)
            raise PersonalDefaultSpaceCreationBusyError() from exc
        raise PersonalDefaultSpaceCreationBusyError()

    async def _renew(self, token: str) -> None:
        while True:
            await asyncio.sleep(self.RENEW_SECONDS)
            try:
                renewed = await asyncio.wait_for(
                    self.repository.renew(token, ttl_seconds=self.TTL_SECONDS),
                    timeout=self.IO_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                logger.exception("Personal default space lock renewal failed key=%s", self.key)
                raise PersonalDefaultSpaceCreationBusyError() from exc
            if not renewed:
                logger.error("Personal default space lock ownership lost key=%s", self.key)
                raise PersonalDefaultSpaceCreationBusyError()

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        token = uuid.uuid4().hex
        tasks: list[asyncio.Task] = []
        try:
            await self._acquire(token)
            work = asyncio.create_task(operation())
            heartbeat = asyncio.create_task(self._renew(token))
            tasks.extend((work, heartbeat))
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                # 丢锁优先报错, 不返回可能失去互斥保护的创建结果。
                await heartbeat
            return await work
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    # 取消后等待创建结束, 再释放锁, 避免后台任务继续写入。
                    pass
                except Exception:
                    logger.exception("Personal default space guarded task failed key=%s", self.key)
            try:
                # 获取响应丢失也可能已加锁, 始终只尝试释放本次令牌。
                await asyncio.wait_for(self.repository.release(token), timeout=self.IO_TIMEOUT_SECONDS)
            except Exception:
                # 释放失败由 TTL 回收, 不掩盖原创建结果或触发无锁重试。
                logger.exception("Personal default space lock release failed key=%s", self.key)
