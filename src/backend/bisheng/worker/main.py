from celery import Celery
from redbeat import RedBeatSchedulerEntry
from celery.schedules import crontab

from bisheng.interface.utils import setup_llm_caching

setup_llm_caching()

bisheng_celery = Celery('bisheng', include=['bisheng.worker'])
bisheng_celery.config_from_object('bisheng.worker.config')
schedule = {'minute': '*/20'}
beat_task = RedBeatSchedulerEntry(name='check_model_status_task',
                    task='bisheng.worker.model.check_models.check_model_status_task',
                    schedule=crontab(**schedule),
                    app=bisheng_celery)
beat_task.save()