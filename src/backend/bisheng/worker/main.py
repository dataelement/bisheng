import threading
import time

from celery import Celery
from celery.signals import celeryd_after_setup, worker_shutting_down
from loguru import logger

import bisheng.worker.tenant_context  # noqa: F401 — register tenant signals
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.context import close_app_context, initialize_app_context
from bisheng.core.logger import set_logger_config


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


def worker_alive_beat(all_queues: list[str]):
    """Worker heartbeat function."""
    logger.debug(f"Worker heartbeat function: {all_queues}")
    while _WORKER_START:
        try:
            # upload worker alive timestamp to redis
            current_timestamp = str(int(time.time()))
            redis_client = get_redis_client_sync()
            redis_client.hset(WORKER_ALIVE_KEY, mapping=dict.fromkeys(all_queues, current_timestamp))
            time.sleep(_WORKER_BEAT_SLEEP)
        except Exception as e:
            logger.error(f"Error in worker alive beat: {e}")
            time.sleep(_WORKER_BEAT_SLEEP * 2)
            continue
    logger.debug("Worker alive beat stopped.")


def _register_worker_permission_contexts() -> None:
    """Register lazy permission contexts for Celery task execution."""

    if not settings.openfga.enabled:
        return

    from bisheng.api.services.f048_permission_runtime import (
        initialize_f048_worker_runtime,
    )
    from bisheng.department.domain.services.department_projection_scope import (
        get_department_projection_scope,
        register_department_projection_runtime_context,
    )
    from bisheng.permission.application.process_runtime import (
        register_f048_permission_runtime_context,
    )

    async def initialize(client):
        return await initialize_f048_worker_runtime(
            client,
            external_scopes={
                "department": get_department_projection_scope(),
            },
        )

    register_f048_permission_runtime_context(initialize)
    register_department_projection_runtime_context()


@celeryd_after_setup.connect
def on_worker_init(*args, **kwargs):
    global _WORKER_START
    """Worker initialization signal handler."""
    from bisheng.worker._asyncio_utils import get_worker_loop, run_async_task

    get_worker_loop()  # start the persistent loop thread before any task arrives
    run_async_task(lambda: initialize_app_context(settings, instance_role="celery"))
    _register_worker_permission_contexts()
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
    from bisheng.worker._asyncio_utils import run_async_task

    run_async_task(close_app_context)
    # Stop routing run_async_safe onto the worker loop as it is torn down.
    from bisheng.utils.async_utils import set_preferred_bridge_loop

    set_preferred_bridge_loop(None)
