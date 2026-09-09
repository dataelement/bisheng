"""Celery registration and bounded active-stream scheduling for DSH."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from celery.signals import worker_shutting_down

from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.worker.dsh.operations import register_operation_tasks
from bisheng.worker.dsh.profiles import register_profile_tasks
from bisheng.worker.dsh.reconciliation import register_reconciliation_tasks
from bisheng.worker.dsh.usage import register_usage_tasks


def register_dsh_tasks(app):
    from bisheng.dsh.operations_runtime import (
        active_tenant_ids,
        administration_worker_runtime,
        operations_worker_runtime,
        projection_worker_runtime,
    )
    from bisheng.worker._asyncio_utils import run_async_task

    register_profile_tasks(app, administration_worker_runtime)
    project = register_usage_tasks(app, projection_worker_runtime)
    register_reconciliation_tasks(app, operations_worker_runtime)
    register_operation_tasks(
        app, administration_worker_runtime, active_tenant_ids, lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    @app.task(bind=True, name="dsh.inspect_usage")
    def inspect_usage(task, tenant_id: int, user_id: int, cursor: int = 0):
        async def execute():
            if (
                type((task.request.headers or {}).get("tenant_id")) is not int
                or task.request.headers["tenant_id"] != tenant_id
            ):
                raise ValueError("DSH inspection requires a matching trusted tenant header")
            with profile_scope(tenant_id):
                async with projection_worker_runtime() as service:
                    next_cursor, changed = await service.inspect_running(
                        tenant_id, user_id, now=datetime.now(UTC), timeout_seconds=3600, cursor=cursor
                    )
                    await service.cleanup_batch(tenant_id, user_id)
                    if next_cursor:
                        inspect_usage.apply_async(
                            args=[tenant_id, user_id, next_cursor], headers={"tenant_id": tenant_id}
                        )
                    return changed

        return run_async_task(execute)

    @app.task(name="dsh.scan_usage")
    def scan_usage(cursor: int = 0, inspect_requests: bool = False, owner: str | None = None):
        async def execute():
            async with operations_worker_runtime() as runtime:
                await runtime.activate()
                quota = runtime.quota
                scan_owner = owner or uuid4().hex
                lease_key = quota.prefix + (":inspect_scan_lease" if inspect_requests else ":projection_scan_lease")
                async with quota.topology.lock:
                    await quota.topology.check()
                    if owner is None:
                        if cursor != 0 or not await quota.redis.set(lease_key, scan_owner, nx=True, px=60000):
                            return 0
                    elif not await quota.redis.eval(
                        "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('PEXPIRE',KEYS[1],60000) end return 0",
                        1,
                        lease_key,
                        scan_owner,
                    ):
                        return 0
                    next_cursor, keys = await quota.redis.scan(cursor, match=quota.prefix + ":*:events", count=100)
                    partitions = []
                    for key in keys:
                        match = re.fullmatch(re.escape(quota.prefix) + r":\{([1-9][0-9]*):([1-9][0-9]*)\}:events", key)
                        if not match:
                            raise ValueError("Malformed quota stream partition")
                        tenant_id, user_id = map(int, match.groups())
                        groups = await quota.redis.xinfo_groups(key)
                        group = next((row for row in groups if row["name"] == "dsh-sql-projection-v1"), None)
                        if inspect_requests or group is None or group.get("pending") or group.get("lag") != 0:
                            partitions.append((tenant_id, user_id))
                for tenant_id, user_id in partitions:
                    with profile_scope(tenant_id):
                        target = inspect_usage if inspect_requests else project
                        target.apply_async(args=[tenant_id, user_id], headers={"tenant_id": tenant_id})
                if next_cursor:
                    scan_usage.apply_async(args=[next_cursor, inspect_requests, scan_owner])
                else:
                    await quota.redis.eval(
                        "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                        1,
                        lease_key,
                        scan_owner,
                    )
                return len(partitions)

        return run_async_task(execute)

    return {"project": project, "inspect": inspect_usage, "scan": scan_usage}


def close_dsh_worker_runtime(**kwargs):
    from bisheng.dsh.operations_runtime import close_operations_worker_runtime
    from bisheng.worker._asyncio_utils import run_async_task

    run_async_task(close_operations_worker_runtime)


worker_shutting_down.connect(close_dsh_worker_runtime)
