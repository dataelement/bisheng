"""昆联控制面任务。默认队列与有界批次。持久需求和 fence 由领域服务拥有。"""

import asyncio
from uuid import uuid4

from loguru import logger

from bisheng.common.errcode.sso_sync import (
    KunlianDependencyUnavailableError,
    KunlianError,
    KunlianTrustRejectedError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.sso_sync.application.runtime import KunlianRuntimeProvider
from bisheng.sso_sync.domain.services.kunlian_logout import KunlianLogoutService
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


def _require_control_header(task):
    headers = task.request.headers or {}
    if type(headers.get("tenant_id")) is not int or headers["tenant_id"] != 1:
        raise KunlianTrustRejectedError()


async def run_control_operation(operation: str, *, connection_id: str | None = None, after_key=""):
    from bisheng.common.services.config_service import settings

    config = settings.sso_sync.kunlian
    if not config.directory_enabled:
        return {"status": "DISABLED"}
    if not config.connection_id or (connection_id is not None and connection_id != config.connection_id):
        raise KunlianTrustRejectedError()
    runtime = KunlianRuntimeProvider()
    try:
        with tenant_execution_scope(1):
            try:
                services = await runtime.worker_services()
                if services.config.connection_id != config.connection_id or not services.config.directory_enabled:
                    raise KunlianTrustRejectedError()
                if operation == "dispatch":
                    async with asyncio.timeout(30):
                        version = await services.directory.request_directory_sync(config.connection_id, "BEAT")
                    # 先提交需求。丢失投递由下次 Beat 读取持久状态恢复。
                    sync_directory.apply_async(args=[config.connection_id], headers={"tenant_id": 1}, queue="celery")
                    recover_projection.apply_async(
                        args=[config.connection_id], headers={"tenant_id": 1}, queue="celery"
                    )
                    return {"status": "REQUESTED", "requested_version": version}
                if operation == "sync":
                    async with asyncio.timeout(930):
                        outcome = await services.directory.run_sync(config.connection_id, str(uuid4()))
                    if outcome.directory_status == "PUBLISHED":
                        recover_projection.apply_async(
                            args=[config.connection_id], headers={"tenant_id": 1}, queue="celery"
                        )
                    return {
                        "directory_status": outcome.directory_status,
                        "projection_status": outcome.projection_status,
                        "batch_id": outcome.batch_id,
                    }
                if operation == "recover":
                    async with asyncio.timeout(300):
                        result = await services.projection.project_pending(
                            config.connection_id, after_key=after_key, limit=25
                        )
                    if result["has_more"]:
                        recover_projection.apply_async(
                            args=[config.connection_id, result["next_after_key"]],
                            headers={"tenant_id": 1},
                            queue="celery",
                        )
                    return result
                raise KunlianTrustRejectedError()
            finally:
                await runtime.aclose()
    except KunlianError:
        raise
    except Exception:
        logger.error("Kunlian worker operation failed: DEPENDENCY_UNAVAILABLE")
        raise KunlianDependencyUnavailableError() from None


@bisheng_celery.task(bind=True, acks_late=True, soft_time_limit=45, time_limit=60)
def dispatch_sync(self):
    _require_control_header(self)
    return run_async_task(lambda: run_control_operation("dispatch"))


@bisheng_celery.task(bind=True, acks_late=True, soft_time_limit=1000, time_limit=1050)
def sync_directory(self, connection_id: str):
    _require_control_header(self)
    return run_async_task(lambda: run_control_operation("sync", connection_id=connection_id))


@bisheng_celery.task(bind=True, acks_late=True, soft_time_limit=330, time_limit=360)
def recover_projection(self, connection_id: str, after_key: str = ""):
    _require_control_header(self)
    return run_async_task(lambda: run_control_operation("recover", connection_id=connection_id, after_key=after_key))


async def run_expiry_operation():
    from bisheng.common.services.config_service import settings

    config = settings.sso_sync.kunlian
    if not config.connection_id:
        return {"status": "DISABLED"}
    try:
        with tenant_execution_scope(1):
            result = await KunlianLogoutService.for_material_cleanup(config).expire_materials()
            if result["has_more"]:
                expire_session_material.apply_async(headers={"tenant_id": 1}, queue="celery")
            return result
    except KunlianError:
        raise
    except Exception:
        logger.error("Kunlian material cleanup failed: DEPENDENCY_UNAVAILABLE")
        raise KunlianDependencyUnavailableError() from None


@bisheng_celery.task(bind=True, acks_late=True, soft_time_limit=30, time_limit=45)
def expire_session_material(self):
    _require_control_header(self)
    return run_async_task(run_expiry_operation)
