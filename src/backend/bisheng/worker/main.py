import asyncio

from celery import Celery

from bisheng.settings import settings
from bisheng.utils.logger import configure
from bisheng.interface.utils import setup_llm_caching

setup_llm_caching()
configure(settings.logger_conf)
loop = asyncio.get_event_loop()

bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
bisheng_celery.config_from_object('bisheng.worker.config')
