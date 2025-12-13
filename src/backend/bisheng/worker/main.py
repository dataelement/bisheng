from celery import Celery

from bisheng.common.services.config_service import settings
from bisheng.core.logger import set_logger_config


def create_celery_app():
    """
    Celery 异步任务
    :return:
    """
    set_logger_config(settings.logger_conf)
    # loop = app_ctx.get_event_loop()
    bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
    bisheng_celery.config_from_object('bisheng.worker.config')
    return bisheng_celery


bisheng_celery = create_celery_app()
