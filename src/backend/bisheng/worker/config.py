from bisheng.settings import settings

broker_url = settings.celery_redis_url

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Asia/Shanghai'
enable_utc = False
