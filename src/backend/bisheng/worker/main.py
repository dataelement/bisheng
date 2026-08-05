import threading
import time

from celery import Celery
from celery.signals import celeryd_after_setup, worker_shutting_down
from loguru import logger

import bisheng.worker.tenant_context  # noqa: F401 — register tenant signals
from bisheng.common.errcode.permission import (
    AuthorizationModelMismatchError,
    PermissionPublishNotReadyError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.logger import set_logger_config
from bisheng.core.openfga.worker_runtime import ensure_worker_fga_runtime


def create_celery_app():
    """
    Celery Asynchronous Tasks
    :return:
    """
    set_logger_config(settings.logger_conf)
    # loop = app_ctx.get_event_loop()
    bisheng_celery = Celery("bisheng", include=["bisheng.worker"])
    bisheng_celery.config_from_object("bisheng.worker.config")
    return bisheng_celery


_WORKER_START = False
_WORKER_BEAT_SLEEP = 5  # seconds
WORKER_ALIVE_KEY = "celery_worker_alive_queues"

bisheng_celery = create_celery_app()


async def _heartbeat_worker_openfga() -> None:
    if not settings.openfga.enabled:
        return
    from bisheng.core.context.manager import app_context

    manager = app_context.get_context("openfga")
    if manager.readiness().get("migration_required"):
        return
    if not await manager.heartbeat():
        raise RuntimeError("Celery F048 OpenFGA runtime heartbeat failed")


def worker_alive_beat(all_queues: list[str]):
    """Worker heartbeat function."""
    logger.debug(f"Worker heartbeat function: {all_queues}")
    while _WORKER_START:
        try:
            # upload worker alive timestamp to redis
            current_timestamp = str(int(time.time()))
            redis_client = get_redis_client_sync()
            redis_client.hset(WORKER_ALIVE_KEY, mapping=dict.fromkeys(all_queues, current_timestamp))
            if settings.openfga.enabled:
                from bisheng.worker._asyncio_utils import run_async_task

                run_async_task(_heartbeat_worker_openfga)
            time.sleep(_WORKER_BEAT_SLEEP)
        except Exception as e:
            logger.error(f"Error in worker alive beat: {e}")
            time.sleep(_WORKER_BEAT_SLEEP * 2)
            continue
    logger.debug("Worker alive beat stopped.")


async def _init_worker_openfga() -> bool:
    """Initialize OpenFGA context in Celery workers for retry/reconcile tasks."""
    if not settings.openfga.enabled:
        return True
    from bisheng.core.context.manager import app_context
    from bisheng.core.openfga.manager import FGAManager

    try:
        manager = app_context.get_context("openfga")
    except KeyError:
        manager = FGAManager(
            openfga_config=settings.openfga,
            instance_role="celery",
        )
        app_context.register_context(manager, optional=False)

    client = await manager.async_get_instance()
    if manager.readiness().get("migration_required"):
        logger.warning(
            "F048 data migration is required; Celery starts without the "
            "permission runtime until migration completes and the worker restarts"
        )
        return False
    # Celery tasks run business code (tool init, resource checks), so this process
    # needs the resource registry the bare background runtime leaves unset.
    from bisheng.api.services.f048_permission_runtime import (
        initialize_f048_worker_runtime,
    )
    from bisheng.department.domain.services.department_projection_scope import (
        configure_department_projection_runtime,
        get_department_projection_scope,
    )
    from bisheng.permission.application.process_runtime import (
        bind_f048_process_runtime,
    )

    try:
        components = await initialize_f048_worker_runtime(
            client,
            external_scopes={
                "department": get_department_projection_scope(),
            },
        )
    except (
        AuthorizationModelMismatchError,
        PermissionPublishNotReadyError,
    ) as exc:
        await manager.mark_migration_required()
        logger.warning(
            "F048 permission data is not ready; Celery starts without the "
            "permission runtime until migration completes and the worker restarts: {}",
            exc,
        )
        return False
    configure_department_projection_runtime(components.projection)
    await bind_f048_process_runtime(
        manager,
        components.facade,
    )
    readiness = await ensure_worker_fga_runtime(manager)
    logger.info(
        "Celery worker F048 runtime initialized: store={} model={} catalog={}",
        readiness["store_id"],
        readiness["model_id"],
        readiness["catalog_release_id"],
    )
    return True


@celeryd_after_setup.connect
def on_worker_init(*args, **kwargs):
    global _WORKER_START
    """Worker initialization signal handler."""
    from bisheng.worker._asyncio_utils import get_worker_loop, run_async_task

    get_worker_loop()  # start the persistent loop thread before any task arrives
    f048_ready = run_async_task(_init_worker_openfga)
    if not f048_ready:
        logger.warning(
            "Celery task consumption is paused until the explicit F048 migration completes and this worker is restarted"
        )
        # The deployment contract requires an explicit post-migration restart;
        # do not poll and activate a worker against a model published mid-run.
        while True:
            time.sleep(_WORKER_BEAT_SLEEP)
    queues = bisheng_celery.amqp.queues
    all_queues = []
    for queue_name, _ in queues.items():
        all_queues.append(queue_name)
    _WORKER_START = True
    t = threading.Thread(target=worker_alive_beat, args=(all_queues,), daemon=True)
    t.start()
    logger.debug("Celery worker alive beat started.")


@worker_shutting_down.connect
def on_worker_shutdown(*args, **kwargs):
    logger.debug("Celery worker shutting down.")
    global _WORKER_START
    _WORKER_START = False
    # Stop routing run_async_safe onto the worker loop as it is torn down.
    from bisheng.utils.async_utils import set_preferred_bridge_loop

    set_preferred_bridge_loop(None)
