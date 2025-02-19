from bisheng.settings import settings

broker_url = settings.celery_redis_url

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Asia/Shanghai'
enable_utc = False
beat_scheduler = 'redbeat.RedBeatScheduler'
redbeat_redis_url = settings.celery_redis_url