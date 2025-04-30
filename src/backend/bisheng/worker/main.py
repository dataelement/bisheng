from celery import Celery
from redbeat import RedBeatSchedulerEntry
from celery.schedules import crontab

from bisheng.interface.utils import setup_llm_caching

setup_llm_caching()

bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
bisheng_celery.config_from_object('bisheng.worker.config')