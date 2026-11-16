"""Bounded original-intent recovery. No IAM, no provider-pull reconciliation."""

import asyncio
import time

from loguru import logger
from sqlmodel import select

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import bypass_tenant_filter, exact_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.lock.token_safe_redis_lock import RedisLockBusyError, TokenSafeRedisLock
from bisheng.database.models.tenant import Tenant
from bisheng.department.domain.repositories.projection_recovery_repository import DepartmentRecoveryRepository
from bisheng.department.domain.services.department_projection_scope import get_department_projection_runtime
from bisheng.permission.application.department_recovery import emit_projection_alert, reason_from_exception
from bisheng.permission.application.department_recovery_runtime import abnormal_department
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True, time_limit=660, soft_time_limit=630)
def recover_department_projections():
    return run_async_task(_periodic)


@bisheng_celery.task(acks_late=True, time_limit=180, soft_time_limit=150)
def recover_department_projection(tenant_id, department_id, operation_id):
    async def run():
        if not settings.openfga.enabled or not settings.department_projection_recovery.enabled:
            return {"status": "DISABLED"}
        with exact_tenant_filter(int(tenant_id)):
            repository = DepartmentRecoveryRepository()
            row = await repository.get(int(department_id))
            if row is None or row["operation_id"] != int(operation_id):
                return {"status": "SUPERSEDED"}
            runtime = await get_department_projection_runtime()
            try:
                await runtime.reconcile_operation(int(operation_id))
                return {"status": "RECOVERED"}
            except (ValueError, PermissionPublishNotReadyError, RedisLockBusyError):
                logger.exception("Department recovery hint requires manual review: {}", department_id)
                return {"status": "MANUAL_REQUIRED"}

    return run_async_task(run)


async def _periodic():
    conf = settings.department_projection_recovery
    if not settings.openfga.enabled or not conf.enabled:
        return {"status": "DISABLED"}
    redis = await get_redis_client()
    raw = getattr(redis, "async_connection", redis)
    started = time.monotonic()
    report = {"attempted": 0, "scanned": 0, "recovered": 0, "blocked": 0, "complete": True}
    try:
        async with TokenSafeRedisLock(
            redis,
            "f086:department-recovery:scan",
            ttl_seconds=conf.run_budget_seconds + 30,
            renewal_interval_seconds=15,
        ):
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    tenants = list(
                        (
                            await session.exec(
                                select(Tenant.id).where(Tenant.status == "active").order_by(Tenant.id).limit(10001)
                            )
                        ).all()
                    )
            if len(tenants) > 10000:
                raise RuntimeError("Department recovery tenant scan exceeds 10000")
            # Rotate tenants as well as department rows; no permanent first-tenant bias.
            tenant_cursor = int(await raw.get("f086:department-recovery:tenant") or 0)
            tenants = [t for t in tenants if t > tenant_cursor] + [t for t in tenants if t <= tenant_cursor]
            repository = DepartmentRecoveryRepository()
            operations = ProjectionRepository()
            runtime = await get_department_projection_runtime()
            for tenant_id in tenants:
                with exact_tenant_filter(int(tenant_id)):
                    key = f"f086:department-recovery:cursor:{tenant_id}"
                    cursor = int(await raw.get(key) or 0)
                    upper = await repository.high_water()
                    while cursor < upper:
                        page = await repository.page(cursor, upper, conf.page_size)
                        if not page:
                            cursor = upper
                            break
                        ids = [r["operation_id"] for r in page if r["operation_id"]]
                        metadata = await operations.aget_bound_operation_metadata(sorted(set(ids)))
                        for row in page:
                            if (
                                time.monotonic() - started >= conf.run_budget_seconds
                                or report["scanned"] >= conf.max_scan_rows
                                or report["attempted"] >= conf.batch_limit
                            ):
                                report["complete"] = False
                                await raw.set(key, cursor)
                                return report
                            report["scanned"] += 1
                            if abnormal_department(row, metadata) and not row["operation_id"]:
                                emit_projection_alert(
                                    "MANUAL_REQUIRED",
                                    reason_code="BOUND_OPERATION_MISSING",
                                    tenant_id=tenant_id,
                                    department_id=row["id"],
                                    details={
                                        "current_state": row["state"],
                                        "current_version": row["version"],
                                        "mode": "AUTO_ORIGINAL",
                                    },
                                )
                            if abnormal_department(row, metadata) and row["operation_id"]:
                                cooldown = f"f086:department-recovery:cooldown:{tenant_id}:{row['id']}"
                                if await raw.get(cooldown):
                                    cursor = row["id"]
                                    await raw.set(key, cursor)
                                    continue
                                report["attempted"] += 1
                                try:
                                    async with asyncio.timeout(
                                        max(1, conf.run_budget_seconds - (time.monotonic() - started))
                                    ):
                                        await runtime.reconcile_operation(row["operation_id"])
                                    report["recovered"] += 1
                                except (ValueError, PermissionPublishNotReadyError, RedisLockBusyError) as error:
                                    await raw.set(cooldown, 1, ex=900)
                                    emit_projection_alert(
                                        "MANUAL_REQUIRED",
                                        reason_code=reason_from_exception(error),
                                        tenant_id=tenant_id,
                                        department_id=row["id"],
                                        operation_id=row["operation_id"],
                                        details={"phase": "periodic_recovery"},
                                    )
                                    # Invalid business/binding is manual work; advance fairly.
                                    report["blocked"] += 1
                                    logger.exception(
                                        "Department recovery blocked tenant={} department={}", tenant_id, row["id"]
                                    )
                            cursor = row["id"]
                            await raw.set(key, cursor)
                    await raw.set(key, 0)
                    await raw.set("f086:department-recovery:tenant", tenant_id)
            return report
    except RedisLockBusyError:
        return report | {"status": "PROCESSING", "complete": False}
    finally:
        logger.info("Department recovery summary {} elapsed={}", report, round(time.monotonic() - started, 3))
