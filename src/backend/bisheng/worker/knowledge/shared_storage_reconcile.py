"""每天凌晨两点启动的共享存储全量对账, 不创建额外状态表。"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.contracts.shared_storage_reconcile import ReconcileLockLost
from bisheng.knowledge.domain.repositories.implementations.shared_storage_reconcile_repository_impl import (
    SharedStorageReconcileRepositoryImpl,
)
from bisheng.knowledge.domain.services.shared_storage_reconcile_service import SharedStorageReconcileService
from bisheng.knowledge.rag.shared_space_storage import load_tenant_routing_snapshot, require_initialized_shared_routing
from bisheng.knowledge.rag.shared_storage_reconcile import SharedStorageReconcileAdapter
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)
LOCK_TTL = 180


class ReconcileLease:
    def __init__(self, lock: Any) -> None:
        self.lock = lock
        self.lost = False

    async def guard(self) -> None:
        if self.lost:
            raise ReconcileLockLost("reconcile lease lost")
        try:
            owned = await asyncio.wait_for(self.lock.owned(), timeout=5)
        except Exception as exc:
            self.lost = True
            raise ReconcileLockLost("cannot verify reconcile lease") from exc
        if not owned:
            self.lost = True
            raise ReconcileLockLost("reconcile lease no longer owned")

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.wait_for(self.lock.extend(LOCK_TTL, replace_ttl=True), timeout=5)
            except Exception as exc:
                self.lost = True
                logger.warning("shared_reconcile lease_renew_failed error_type=%s", type(exc).__name__)
                return


@asynccontextmanager
async def source_factory() -> AsyncIterator[SharedStorageReconcileRepositoryImpl]:
    async with get_async_db_session() as session:
        try:
            yield SharedStorageReconcileRepositoryImpl(session)
            await asyncio.wait_for(session.commit(), timeout=30)
        except BaseException:
            await session.rollback()
            raise


async def _run_tenant(tenant_id: int) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    lock = None
    acquired = False
    heartbeat = None
    store = None
    result = {"run_id": run_id, "status": "incomplete", "tenant_id": tenant_id}
    try:
        redis = await asyncio.wait_for(get_redis_client(), timeout=10)
        lock = redis.async_connection.lock(
            f"shared_storage_reconcile:{tenant_id}",
            timeout=LOCK_TTL,
            blocking=False,
            thread_local=False,
        )
        acquired = await asyncio.wait_for(lock.acquire(), timeout=5)
        if not acquired:
            result["status"] = "already_running"
            return result
        lease = ReconcileLease(lock)
        heartbeat = asyncio.create_task(lease.heartbeat())
        snapshot = await asyncio.wait_for(asyncio.to_thread(load_tenant_routing_snapshot, tenant_id), timeout=30)
        snapshot = require_initialized_shared_routing(tenant_id, snapshot)
        store = SharedStorageReconcileAdapter(snapshot, guard=lease.guard)

        async def dispatch(entry_id: int) -> None:
            from bisheng.worker.knowledge.document_projection import process_document_projection

            await lease.guard()
            await asyncio.to_thread(
                process_document_projection.apply_async,
                kwargs={"tenant_id": tenant_id, "entry_id": entry_id},
                headers={"tenant_id": tenant_id},
                queue="celery",
                retry=False,
            )

        result.update(
            await SharedStorageReconcileService(
                source_factory=source_factory,
                store=store,
                guard=lease.guard,
                dispatch=dispatch,
                run_id=run_id,
            ).run()
        )
    except Exception as exc:
        logger.error(
            "shared_reconcile tenant_failed run_id=%s tenant_id=%s error_type=%s", run_id, tenant_id, type(exc).__name__
        )
        result["status"] = "incomplete"
    finally:
        if heartbeat:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        if store:
            try:
                await store.close()
            except Exception as exc:
                logger.warning("shared_reconcile client_close_failed error_type=%s", type(exc).__name__)
        if acquired:
            try:
                # Redis lock 使用所有权 token, 不能删除另一轮任务的锁。
                await asyncio.wait_for(lock.release(), timeout=5)
            except Exception as exc:
                result["status"] = "incomplete"
                logger.warning(
                    "shared_reconcile lease_release_failed run_id=%s error_type=%s", run_id, type(exc).__name__
                )
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        logger.info("shared_reconcile tenant_summary=%s", result)
    return result


@bisheng_celery.task(name="bisheng.worker.knowledge.shared_storage_reconcile.reconcile_tenant_shared_storage")
def reconcile_tenant_shared_storage(tenant_id: int) -> dict[str, Any]:
    if int(get_current_tenant_id() or DEFAULT_TENANT_ID) != int(tenant_id):
        raise ValueError("shared reconcile tenant header mismatch")
    return run_async_task(lambda: _run_tenant(int(tenant_id)))


async def _fanout() -> dict[str, int]:
    tenant_ids = sorted({DEFAULT_TENANT_ID, *await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID)})
    submitted, failed = 0, 0
    for tenant_id in tenant_ids:
        try:
            await asyncio.to_thread(
                reconcile_tenant_shared_storage.apply_async,
                kwargs={"tenant_id": int(tenant_id)},
                headers={"tenant_id": int(tenant_id)},
                queue="celery",
                retry=False,
            )
            submitted += 1
        except Exception as exc:
            failed += 1
            logger.error(
                "shared_reconcile dispatch_tenant_failed tenant_id=%s error_type=%s", tenant_id, type(exc).__name__
            )
    return {"submitted": submitted, "failed": failed}


@bisheng_celery.task(name="bisheng.worker.knowledge.shared_storage_reconcile.fanout_shared_storage_reconcile")
def fanout_shared_storage_reconcile() -> dict[str, int]:
    return run_async_task(_fanout)
