"""Compose department Owner recovery with public permission infrastructure."""

import asyncio

from loguru import logger

from bisheng.common.services.config_service import settings


async def build_department_executor(components, scope):
    """Shared Owner/permission composition for API and Worker processes."""
    from uuid import NAMESPACE_URL, uuid5

    from bisheng.api.services.current_department_repair_runtime import CurrentDepartmentRepairRuntime
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.lock.token_safe_redis_lock import TokenSafeRedisLock
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.department.domain.services.department_projection_recovery import DepartmentProjectionExecutor

    redis = await get_redis_client()
    reader = CurrentDepartmentRepairRuntime("automatic", qps=settings.department_projection_recovery.max_fga_qps)
    from bisheng.permission.application.department_recovery_model import discover_batch_model

    model_cache = {}

    async def discover_current():
        async with asyncio.timeout(10):
            return await discover_batch_model(reader.client._http, model_cache)

    reader.discover = discover_current
    try:
        await reader.initialize()
    except Exception:
        await reader.client.close()
        raise

    def lease_factory(tenant_id, department_id):
        return TokenSafeRedisLock(
            redis,
            f"f048:department-projection:{tenant_id}:{department_id}",
            ttl_seconds=60,
            renewal_interval_seconds=15,
        )

    def require_runtime_pin(value):
        if components.client is None or (components.client.store_id, components.client.model_id) != (
            value["store_id"],
            value["model_id"],
        ):
            from bisheng.common.errcode.permission import PermissionPublishNotReadyError

            raise PermissionPublishNotReadyError(msg="OPERATION_MODEL_PIN_MISMATCH")
        return value["store_id"], value["model_id"]

    async def business_environment(session):
        # Normal mutations use the runtime's already validated model pin.
        # Lock the SQL release without probing all FGA models per request.
        async with reader.catalog.bind_session(session):
            value = await reader.catalog.aget_recovery_environment(lock=True)
        return require_runtime_pin(value)

    async def environment(session):
        async with reader.catalog.bind_session(session):
            value = await reader.environment(lock=True, refresh=True)
        return require_runtime_pin(value)

    async def audit(session, plan, operation_id, stage, reason):
        from sqlmodel import select

        identity = uuid5(NAMESPACE_URL, f"f086:auto:{operation_id}:{plan.idempotency_key}:{stage}").hex
        exists = (await session.exec(select(AuditLog.id).where(AuditLog.id == identity))).first()
        if exists is None:
            session.add(
                AuditLog(
                    id=identity,
                    tenant_id=plan.tenant_id,
                    operator_id=0,
                    action=f"permission.department.recovery.{stage}",
                    target_type="department_projection",
                    target_id=str(plan.scope_key),
                    audit_metadata={
                        "mode": "BUSINESS_PROJECTION" if reason == "BUSINESS_PROJECTION" else "AUTO_ORIGINAL",
                        "operation_id": operation_id,
                        "request_id": plan.idempotency_key,
                        "reason": None if reason == "BUSINESS_PROJECTION" else reason,
                    },
                )
            )
            await session.flush()

    async def dispatch(tenant_id, department_id, operation_id):
        try:
            from bisheng.worker.department.projection_recovery import recover_department_projection

            raw = getattr(redis, "async_connection", redis)
            key = f"f086:recovery-hint:{tenant_id}:{department_id}:{operation_id}"
            attempt = int(await raw.incr(key))
            await raw.expire(key, 900)
            if attempt <= 4:
                recover_department_projection.apply_async(
                    args=(tenant_id, department_id, operation_id),
                    headers={"tenant_id": tenant_id},
                    countdown=(5, 15, 60, 300)[attempt - 1],
                )
        except Exception:
            # Dispatch is only a hint. Durable D binding and periodic scan remain.
            logger.exception("Department recovery dispatch failed for {}", department_id)

    async def archive_obligations(session, dept):
        from bisheng.common.errcode.permission import PermissionPublishNotReadyError
        from bisheng.department.domain.repositories.iam_archive_repository import IamArchiveDepartmentRepository
        from bisheng.role.domain.repositories.department_retirement_repository import DepartmentRoleRetirementRepository

        archive_repo = IamArchiveDepartmentRepository()
        await archive_repo.require_leaf(dept, session=session)
        before, _ = await archive_repo.archive_snapshot(
            dept, DepartmentRoleRetirementRepository(), session=session, lock=True
        )
        if any(before.values()):
            raise PermissionPublishNotReadyError(msg="ARCHIVE_OWNER_CLEANUP_REQUIRED")

    executor = DepartmentProjectionExecutor(
        ledger=components.projection,
        scope=scope,
        lease_factory=lease_factory,
        observed=reader.observed,
        environment=environment,
        business_environment=business_environment,
        audit=audit,
        dispatch=dispatch,
        write_gate=lambda: reader.limiter.on_request(None),
        archive_obligations=archive_obligations,
    )
    executor.close = reader.client.close
    return executor
