from bisheng.settings import settings

broker_url = settings.celery_redis_url

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Asia/Shanghai'
enable_utc = False
beat_scheduler = 'redbeat.RedBeatScheduler'
redbeat_redis_url = settings.celery_redis_url
# redbeat_lock_key = None
# redbeat_lock_timeout = 10
task_routes = settings.celery_task.task_routers
