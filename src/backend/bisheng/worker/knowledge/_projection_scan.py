"""按租户、轮次预算和持久化游标执行投影兜底扫描。"""

import asyncio
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    current_tenant_id,
    get_admin_scope_tenant_id,
    set_admin_scope_tenant_id,
    strict_tenant_filter,
    visible_tenant_ids,
)
from bisheng.database.models.tenant import TenantDao
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf
from bisheng.worker.knowledge._projection_scan_state import IO_TIMEOUT, ProjectionScanState

logger = logging.getLogger(__name__)
PAGE_SIZE = 100
KINDS = ("projection", "permission", "retirement")


@contextmanager
def tenant_scan_context(tenant_id: int):
    """每个异步租户扫描独立设置上下文, 包括数据库过滤及后续消息头。"""
    tenant_token = current_tenant_id.set(tenant_id)
    visible_token = visible_tenant_ids.set(frozenset({tenant_id}))
    previous_scope = get_admin_scope_tenant_id()
    set_admin_scope_tenant_id(None)
    try:
        with strict_tenant_filter():
            yield
    finally:
        set_admin_scope_tenant_id(previous_scope)
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


async def scan_documents(tenant_id: int | None = None) -> dict:
    if tenant_id is not None:
        with tenant_scan_context(tenant_id):
            dispatched = await scan_tenant(tenant_id)
        return {"status": "completed", "tenants_visited": 1, "projection_dispatched": dispatched, "failed_tenants": []}

    conf = get_shared_storage_conf()
    budget = int(getattr(conf, "projection_scan_total_time_budget_seconds", 120))
    concurrency = int(getattr(conf, "projection_scan_tenant_concurrency", 3))
    state = await ProjectionScanState.create(DEFAULT_TENANT_ID)
    lock = state.redis.lock(state.key("lock", "all_tenants"), timeout=budget + 60, blocking=False, thread_local=False)
    if not await asyncio.wait_for(lock.acquire(), IO_TIMEOUT):
        return {"status": "already_running", "tenants_visited": 0, "projection_dispatched": 0, "failed_tenants": []}

    result = {"status": "completed", "tenants_visited": 0, "projection_dispatched": 0, "failed_tenants": []}
    workers = []

    async def guard() -> None:
        if not await asyncio.wait_for(lock.owned(), IO_TIMEOUT):
            raise RuntimeError("projection global scan lease lost")

    async def scan_all() -> None:
        # 租户轮转游标与默认租户自己的文档游标分别存储。
        cursor = await state.cursor("all_tenants")
        tenant_ids = sorted({DEFAULT_TENANT_ID, *await TenantDao.aget_children_ids_active(DEFAULT_TENANT_ID)})
        last_id = int(cursor.get("last_tenant_id", 0))
        ordered = [value for value in tenant_ids if value > last_id] + [
            value for value in tenant_ids if value <= last_id
        ]
        admission_lock = asyncio.Lock()
        position = 0

        async def consume() -> None:
            nonlocal position
            while True:
                async with admission_lock:
                    if position >= len(ordered):
                        return
                    await guard()
                    selected = ordered[position]
                    # 记录已安排租户, 即使其中一个租户一直失败也不会堵住后续租户。
                    await state.save_cursor({"last_tenant_id": selected}, "all_tenants")
                    position += 1
                try:
                    with tenant_scan_context(selected):
                        dispatched = await scan_tenant(selected)
                    result["projection_dispatched"] += dispatched
                except Exception:
                    logger.exception("projection tenant scan failed tenant_id=%s", selected)
                    result["failed_tenants"].append(selected)
                finally:
                    result["tenants_visited"] += 1

        workers.extend(asyncio.create_task(consume()) for _ in range(min(concurrency, len(ordered))))
        await asyncio.gather(*workers)

    started = time.monotonic()
    try:
        await asyncio.wait_for(scan_all(), timeout=budget)
        if result["failed_tenants"]:
            result["status"] = "completed_with_failures"
    except asyncio.TimeoutError:
        result["status"] = "budget_reached"
        logger.warning("projection global scan budget reached budget_seconds=%s", budget)
    finally:
        for task in workers:
            task.cancel()
        outcomes = await asyncio.gather(*workers, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.error("projection scan worker stopped: %r", outcome)
        try:
            await asyncio.wait_for(lock.release(), IO_TIMEOUT)
        except Exception:
            logger.exception("projection global scan lock release failed")
        logger.info("projection global scan result=%s elapsed_seconds=%.2f", result, time.monotonic() - started)
    return result


async def scan_tenant(tenant_id: int) -> int:
    from bisheng.worker.knowledge import document_projection as worker

    conf = get_shared_storage_conf()
    budget = int(getattr(conf, "projection_scan_time_budget_seconds", 45))
    max_pages = int(getattr(conf, "projection_scan_max_pages", 15))
    max_attempts = int(conf.projection_max_retries)
    state = await ProjectionScanState.create(tenant_id)
    lock = state.redis.lock(state.key("lock", "tenant"), timeout=budget + 60, blocking=False, thread_local=False)
    if not await asyncio.wait_for(lock.acquire(), IO_TIMEOUT):
        logger.info("projection scan skipped: tenant already scanning tenant_id=%s", tenant_id)
        return 0

    async def guard() -> None:
        if not await asyncio.wait_for(lock.owned(), IO_TIMEOUT):
            raise RuntimeError("projection scan lease lost")

    dispatched = pages = rows_seen = 0
    exhausted_sample = []
    cursor = {}
    projection_tickets = []
    committed_projection_cursor = 0
    cutoff = datetime.now() - timedelta(minutes=5)

    async def save_scan_progress() -> None:
        await guard()
        # 投影候选先在内存聚合; 发出整批消息前不能提交这部分游标。
        await state.save_cursor({**cursor, "projection": committed_projection_cursor})

    async def scan() -> None:
        nonlocal pages, rows_seen
        finished = set()
        while pages < max_pages and len(finished) < len(KINDS):
            branch = int(cursor.get("branch", 0)) % len(KINDS)
            kind = KINDS[branch]
            # 每页轮换分支, 时间预算很小时也不让某类任务长期饥饿。
            cursor["branch"] = (branch + 1) % len(KINDS)
            if kind in finished:
                continue
            # 慢查询或失败页面也轮换分支, 保留其主键游标供后续恢复。
            await save_scan_progress()
            after_id = int(cursor.get(kind, 0))
            async with worker.get_async_db_session() as session:
                repo = worker.KnowledgeFileRepositoryImpl(session)
                if kind == "projection":
                    candidates = await repo.find_projection_candidates(
                        now=datetime.now(),
                        limit=PAGE_SIZE,
                        max_retries=max_attempts,
                        after_id=after_id,
                    )
                elif kind == "permission":
                    candidates = await repo.find_permission_reconcile_candidates(
                        older_than=cutoff,
                        limit=PAGE_SIZE,
                        after_id=after_id,
                    )
                else:
                    candidates = await KnowledgeRepositoryImpl(session).find_retiring_spaces(
                        after_id=after_id,
                        limit=PAGE_SIZE,
                    )
            pages += 1
            rows_seen += len(candidates)
            if kind == "projection":
                for row in candidates:
                    await guard()
                    fingerprint = f"{row.desired_content_generation}:{row.desired_entry_generation}:{row.entry_status}"
                    ticket = await state.reserve("projection", int(row.id), fingerprint)
                    if ticket:
                        projection_tickets.append(ticket)
            elif kind == "permission":
                exhausted_sample.extend(
                    int(row.id) for row in candidates if int(row.projection_retry_count or 0) >= max_attempts
                )
                preparing = [row for row in candidates if row.entry_status == "preparing"]
                for reconcile in (worker._reconcile_permission_candidates, worker._reconcile_rollback_candidates):
                    await reconcile(
                        tenant_id=tenant_id, candidates=preparing, state=state, max_attempts=max_attempts, guard=guard
                    )
            else:
                for row in candidates:
                    await worker._dispatch_scan_recovery(
                        state,
                        guard,
                        "retirement",
                        int(row.id),
                        str(row.create_time),
                        {"space_id": int(row.id)},
                        max_attempts=max_attempts,
                    )
            if len(candidates) < PAGE_SIZE:
                cursor[kind] = 0
                finished.add(kind)
            else:
                cursor[kind] = int(candidates[-1].id)
            await save_scan_progress()

    try:
        cursor = await state.cursor()
        committed_projection_cursor = int(cursor.get("projection", 0))
        try:
            await asyncio.wait_for(scan(), timeout=budget)
        except asyncio.TimeoutError:
            logger.warning("projection scan budget reached tenant_id=%s budget_seconds=%s", tenant_id, budget)
        finally:
            # 达到预算或某类扫描失败后, 仍投递已收集的数据, 每租户每轮只发一次。
            if projection_tickets:
                await worker._publish_scan_task(
                    worker.process_document_projection,
                    state=state,
                    guard=guard,
                    kwargs={
                        "tenant_id": tenant_id,
                        "entry_ids": [ticket["object_id"] for ticket in projection_tickets],
                        "scan_tickets": projection_tickets,
                    },
                )
                dispatched = len(projection_tickets)
            await guard()
            await state.save_cursor(cursor)
    finally:
        try:
            await asyncio.wait_for(lock.release(), IO_TIMEOUT)
        except Exception:
            logger.exception("projection scan lock release failed tenant_id=%s", tenant_id)
        logger.info(
            "projection scan tenant_id=%s pages=%s candidates=%s dispatched=%s cursor=%s",
            tenant_id,
            pages,
            rows_seen,
            dispatched,
            cursor,
        )
        if exhausted_sample:
            logger.warning(
                "projection cleanup requires explicit recovery tenant_id=%s exhausted=%s sample=%s",
                tenant_id,
                len(exhausted_sample),
                exhausted_sample[:10],
            )
    return dispatched
