from bisheng.common.services.config_service import settings

broker_url = settings.celery_redis_url

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'Asia/Shanghai'
enable_utc = False
task_routes = settings.celery_task.task_routers
# redis健康检查间隔，单位秒
redis_backend_health_check_interval = 5
