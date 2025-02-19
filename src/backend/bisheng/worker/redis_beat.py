import json

from celery.beat import Scheduler
import redis
from celery.schedules import crontab

from bisheng.settings import settings

beat_redis_client = None

class DynamicScheduler(Scheduler):
    def __init__(self, *args, **kwargs):
        self.redis_client = redis.from_url(settings.celery_redis_url)
        super(DynamicScheduler, self).__init__(*args, **kwargs)

    def setup_schedule(self):
        # 从 Redis 加载任务
        tasks = self.redis_client.hgetall('celery_dynamic_tasks')
        for task_name, config in tasks.items():
            config = json.loads(config)
            self.schedule[task_name] = {
                'task': config['task'],
                'schedule': crontab(**config['schedule']),
                'args': config.get('args', ()),
                'kwargs': config.get('kwargs', {}),
            }

    def sync(self):
        # 将当前调度器状态同步回 Redis
        for name, entry in self.schedule.items():
            self.redis_client.hset(
                'celery_dynamic_tasks',
                name,
                json.dumps({
                    'task': entry.task,
                    'schedule': entry.schedule._orig,
                    'args': entry.args,
                    'kwargs': entry.kwargs,
                })
            )


def add_beat_task(dynamic_task_name: str,  schedule: dict, task: str, *args, **kwargs):
    global beat_redis_client
    if beat_redis_client is None:
        beat_redis_client = redis.from_url(settings.celery_redis_url)

    beat_redis_client.hset(
        'celery_dynamic_tasks',
        dynamic_task_name,
        json.dumps({
            'task': task,
            'schedule': schedule,
            'args': args,
            'kwargs': kwargs,
        })
    )
