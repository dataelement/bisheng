from celery import Celery
from bisheng.common.services.config_service import settings
from bisheng.utils.logger import configure
from bisheng.interface.utils import setup_llm_caching


def create_celery_app():
    """
    Celery 异步任务
    :return:
    """
    setup_llm_caching()
    configure(settings.logger_conf)
    # loop = app_ctx.get_event_loop()
    bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
    bisheng_celery.config_from_object('bisheng.worker.config')
    return bisheng_celery


bisheng_celery = create_celery_app()
