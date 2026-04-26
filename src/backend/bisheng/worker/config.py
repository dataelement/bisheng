from bisheng.common.services.config_service import settings
from bisheng.core.config.celery_redis import build_celery_redis_config

_celery_redis_config = build_celery_redis_config(settings.celery_redis_url)

broker_url = _celery_redis_config['broker_url']
broker_transport_options = _celery_redis_config.get('broker_transport_options', {})

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Asia/Shanghai'
enable_utc = False
task_routes = settings.celery_task.task_routers
# redisHealth check interval, unit sec
redis_backend_health_check_interval = 5

beat_schedule = settings.celery_task.beat_schedule
