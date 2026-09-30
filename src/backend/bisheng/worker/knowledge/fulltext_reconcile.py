"""每日 01:00 全量全文对账及持久化续跑, 解析在独立队列任务执行。"""

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session
from bisheng.core.search.elasticsearch.manager import get_es_connection
from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileLeaseLost
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_es_repository_impl import (
    KnowledgeFulltextReconcileESRepository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_repository_impl import (
    KnowledgeFulltextReconcileRepository,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_reconcile_service import KnowledgeFulltextReconcileService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

START_TASK = "bisheng.worker.knowledge.fulltext_reconcile.start"
RESUME_TASK = "bisheng.worker.knowledge.fulltext_reconcile.resume"
PARSE_TASK = "bisheng.worker.knowledge.fulltext_reconcile.reparse_file"
PROJECTION_TASK = "bisheng.worker.knowledge.fulltext_reconcile.rebuild_projection"
LOCK_TTL = 180


def local_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def register_schedule() -> None:
    schedule = dict(bisheng_celery.conf.beat_schedule or {})
    schedule["daily_knowledge_fulltext_reconcile"] = {"task": START_TASK, "schedule": crontab(hour=1, minute=0)}
    # 恢复任务只处理已存在轮次和持久化修复意图, 不启动新的全量扫描。
    schedule["resume_knowledge_fulltext_reconcile"] = {"task": RESUME_TASK, "schedule": 300.0}
    bisheng_celery.conf.beat_schedule = schedule


register_schedule()


@asynccontextmanager
async def repository_factory():
    async with get_async_db_session() as session:
        try:
            yield KnowledgeFulltextReconcileRepository(session)
            await asyncio.wait_for(session.commit(), timeout=30)
        except BaseException:
            await session.rollback()
            raise


class Lease:
    def __init__(self, lock):
        self.lock = lock
        self.lost = False

    async def guard(self):
        try:
            if self.lost or not await asyncio.wait_for(self.lock.owned(), timeout=5):
                raise ReconcileLeaseLost("fulltext reconcile lease lost")
        except Exception as exc:
            self.lost = True
            raise ReconcileLeaseLost("cannot verify fulltext reconcile lease") from exc

    async def heartbeat(self):
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.wait_for(self.lock.extend(LOCK_TTL, replace_ttl=True), timeout=5)
            except Exception:
                self.lost = True
                logger.exception("fulltext reconcile lease renewal failed")
                return


async def publish_repairs(guard) -> dict:
    async with repository_factory() as repo:
        tickets = await repo.state.pending_repairs(local_now())
    submitted, failed = 0, 0
    deadline = time.monotonic() + 15
    for ticket in tickets:
        if time.monotonic() >= deadline:
            break
        await guard()
        task = reparse_fulltext_file if ticket.reason == "parse" else rebuild_fulltext_projection
        try:
            # 超时后投递结果可能未知, 后续仍使用相同任务 ID 和数据库领取条件。
            await asyncio.wait_for(
                asyncio.to_thread(
                    task.apply_async,
                    kwargs={
                        "file_id": ticket.file_id,
                        "fingerprint": ticket.fingerprint,
                        "repair_task_id": ticket.task_id,
                    },
                    task_id=ticket.task_id,
                    queue="knowledge_celery" if ticket.reason == "parse" else "celery",
                    retry=False,
                ),
                timeout=5,
            )
            async with repository_factory() as repo:
                await repo.state.repair_published(ticket, local_now())
            submitted += 1
        except Exception:
            failed += 1
            logger.exception("fulltext reconcile repair publish failed file_id={}", ticket.file_id)
    return {"repair_submitted": submitted, "repair_publish_failed": failed}


async def _run(*, create: bool):
    constants.ensure_runtime_compatible(multi_tenant_enabled=settings.multi_tenant.enabled)
    redis = await asyncio.wait_for(get_redis_client(), timeout=10)
    lock = redis.async_connection.lock(
        "knowledge_fulltext:daily_reconcile", timeout=LOCK_TTL, blocking=False, thread_local=False
    )
    if not await asyncio.wait_for(lock.acquire(), timeout=5):
        return {"status": "already_running"}
    lease = Lease(lock)
    heartbeat = asyncio.create_task(lease.heartbeat())
    try:
        client = (await get_es_connection()).options(request_timeout=30)
        # 对账不能自动修改 mapping/切换别名, 部署契约错误时保留进度。
        await KnowledgeFulltextIndexRepositoryImpl(client).validate_read_index()
        repairs = await publish_repairs(lease.guard)
        service = KnowledgeFulltextReconcileService(
            repository_factory=repository_factory,
            es=KnowledgeFulltextReconcileESRepository(client, index=constants.physical_index_name()),
            guard=lease.guard,
            now=local_now,
        )
        result = await asyncio.wait_for(service.run(create=create), timeout=420)
        after_repairs = await publish_repairs(lease.guard)
        result.update({key: value + after_repairs[key] for key, value in repairs.items()})
        logger.info("fulltext reconcile summary={}", result)
        return result
    except Exception:
        logger.exception("fulltext reconcile paused; persisted cursor will resume")
        raise
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        try:
            await lock.release()
        except Exception:
            logger.exception("fulltext reconcile lease release failed")


@bisheng_celery.task(name=START_TASK, acks_late=True, soft_time_limit=550, time_limit=600)
def start_fulltext_reconcile():
    return run_async_task(lambda: _run(create=True))


@bisheng_celery.task(name=RESUME_TASK, acks_late=True, soft_time_limit=550, time_limit=600)
def resume_fulltext_reconcile():
    return run_async_task(lambda: _run(create=False))


async def _begin(file_id, fingerprint, task_id):
    constants.ensure_runtime_compatible(multi_tenant_enabled=settings.multi_tenant.enabled)
    async with repository_factory() as repo:
        return await repo.begin_repair(file_id, fingerprint, task_id, local_now())


async def _finish(file_id, fingerprint, task_id, kind, ok):
    async with repository_factory() as repo:
        await repo.finish_repair(file_id, fingerprint, task_id, kind, ok, local_now())


@bisheng_celery.task(name=PARSE_TASK, acks_late=True, soft_time_limit=880, time_limit=900)
def reparse_fulltext_file(file_id: int, fingerprint: str, repair_task_id: str):
    kind = run_async_task(lambda: _begin(file_id, fingerprint, repair_task_id))
    if kind != "parse":
        return {"status": "not_claimed"}
    ok = False
    try:
        from bisheng.worker.knowledge.file_worker import retry_knowledge_file_celery

        # 当前已经是独立文件解析队列任务; 复用带解析交付跟踪的正式入口。
        retry_knowledge_file_celery.run(file_id=file_id)
        ok = True
    finally:
        run_async_task(lambda: _finish(file_id, fingerprint, repair_task_id, kind, ok))
    return {"status": "finished"}


@bisheng_celery.task(name=PROJECTION_TASK, acks_late=True, soft_time_limit=880, time_limit=900)
def rebuild_fulltext_projection(file_id: int, fingerprint: str, repair_task_id: str):
    kind = run_async_task(lambda: _begin(file_id, fingerprint, repair_task_id))
    if kind != "projection":
        return {"status": "not_claimed"}
    ok = False
    try:
        from bisheng.worker.knowledge.fulltext_index import _run_logical_entry_projection_repair

        ok = run_async_task(
            lambda: _run_logical_entry_projection_repair(file_id=file_id, tenant_id=1, lease_owner=repair_task_id)
        )
    finally:
        run_async_task(lambda: _finish(file_id, fingerprint, repair_task_id, kind, ok))
    return {"status": "waiting_projection" if ok is None else "finished"}
