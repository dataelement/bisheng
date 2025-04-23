from celery import Celery
from celery.schedules import crontab

from bisheng.interface.utils import setup_llm_caching

setup_llm_caching()

bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
bisheng_celery.config_from_object('bisheng.worker.config')
bisheng_celery.conf.beat_schedule = {
    'check_model_status_task': {
        'task': 'bisheng.worker.model.check_models.check_model_status_task',
        'schedule': crontab(minute='*/1'),
    }
}

