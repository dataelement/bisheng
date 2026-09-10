from bisheng.common.services.config_service import settings
from bisheng.core.config.celery_redis import build_celery_redis_config

_celery_redis_config = build_celery_redis_config(settings.celery_redis_url)

broker_url = _celery_redis_config["broker_url"]
broker_transport_options = _celery_redis_config.get("broker_transport_options", {})

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "Asia/Shanghai"
enable_utc = False
# Approval and F046 control tasks use the default `celery` queue. F046 only
# persists business state and hands parsing to the file scheduler; routing it to
# `knowledge_celery` lets long-running parsers block later approved requests.
# Keep this specific route before the configurable broad Knowledge route so
# named dispatches and Beat use the same queue as registered task dispatches.
_F046_CONTROL_TASK_ROUTE = "bisheng.worker.knowledge.file_change_tasks.*"
task_routes = {
    _F046_CONTROL_TASK_ROUTE: {"queue": "celery"},
    **{
        pattern: route
        for pattern, route in settings.celery_task.task_routers.items()
        if pattern != _F046_CONTROL_TASK_ROUTE
    },
}
# redisHealth check interval, unit sec
redis_backend_health_check_interval = 5

beat_schedule = settings.celery_task.beat_schedule
