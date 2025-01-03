from loguru import logger

from bisheng.worker.main import bisheng_celery

@bisheng_celery.task
def add(x,y):
    logger.info(f"add {x} + {y}")
    return x+y
