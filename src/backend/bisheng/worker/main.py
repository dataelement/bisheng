import asyncio
import threading
import time
from typing import List

from celery import Celery
from celery.signals import celeryd_after_setup, worker_shutting_down
from loguru import logger

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.logger import set_logger_config

import bisheng.worker.tenant_context  # noqa: F401 — register tenant signals


def create_celery_app():
    """
    Celery Asynchronous Tasks
    :return:
    """
    set_logger_config(settings.logger_conf)
    # loop = app_ctx.get_event_loop()
    bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
    bisheng_celery.config_from_object('bisheng.worker.config')
    return bisheng_celery


_WORKER_START = False
_WORKER_BEAT_SLEEP = 5  # seconds
WORKER_ALIVE_KEY = "celery_worker_alive_queues"

bisheng_celery = create_celery_app()


def worker_alive_beat(all_queues: List[str]):
    """Worker heartbeat function."""
    logger.debug(f"Worker heartbeat function: {all_queues}")
    while _WORKER_START:
        try:
            # upload worker alive timestamp to redis
            current_timestamp = str(int(time.time()))
            redis_client = get_redis_client_sync()
            redis_client.hset(WORKER_ALIVE_KEY, mapping={one: current_timestamp for one in all_queues})
            time.sleep(_WORKER_BEAT_SLEEP)
        except Exception as e:
            logger.error(f"Error in worker alive beat: {e}")
            time.sleep(_WORKER_BEAT_SLEEP * 2)
            continue
    logger.debug('Worker alive beat stopped.')


async def _init_worker_openfga() -> None:
    """Initialize OpenFGA context in Celery workers for retry/reconcile tasks."""
    if not settings.openfga.enabled:
        return
    try:
        from bisheng.core.context.manager import app_context
        from bisheng.core.openfga.manager import FGAManager, aget_fga_client

        try:
            app_context.get_context('openfga')
        except KeyError:
            app_context.register_context(FGAManager(openfga_config=settings.openfga), optional=True)

        await aget_fga_client()
        logger.info("Celery worker OpenFGA context initialized.")
    except Exception as e:  # noqa: BLE001 - OpenFGA is optional at worker startup.
        logger.warning("Celery worker OpenFGA context initialization failed: {}", e)


def _init_worker_openfga_sync() -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_init_worker_openfga())
    finally:
        loop.close()


@celeryd_after_setup.connect
def on_worker_init(*args, **kwargs):
    global _WORKER_START
    """Worker initialization signal handler."""
    _init_worker_openfga_sync()
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
