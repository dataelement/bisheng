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
# Approval async tasks (outbox execution / retry) intentionally have NO route here,
# so they fall through to Celery's default `celery` queue. The `workflow_celery`
# queue is reserved for workflow DAG execution only.
task_routes = {**settings.celery_task.task_routers}
task_routes.setdefault("bisheng.worker.knowledge.space_delete.*", {"queue": "knowledge_celery"})
# redisHealth check interval, unit sec
redis_backend_health_check_interval = 5

beat_schedule = dict(settings.celery_task.beat_schedule)
beat_schedule.setdefault(
    "knowledge-space-delete-recovery",
    {"task": "bisheng.worker.knowledge.space_delete.dispatch_pending_deletes", "schedule": 60.0},
)
if settings.dsh.enabled:
    beat_schedule.setdefault(
        "dsh-audit-tree-preparation",
        {"task": "dsh.scan_audit_trees", "schedule": settings.dsh.audit_state_scan_interval_seconds},
    )
    beat_schedule.setdefault(
        "dsh-model-audit-inspection",
        {"task": "dsh.scan_model_audit", "schedule": settings.dsh.audit_state_scan_interval_seconds},
    )
    beat_schedule.setdefault("dsh-usage-projection", {"task": "dsh.scan_usage", "schedule": 5.0})
    beat_schedule.setdefault(
        "dsh-usage-inspection", {"task": "dsh.scan_usage", "schedule": 60.0, "kwargs": {"inspect_requests": True}}
    )
    beat_schedule.setdefault("dsh-operation-recovery", {"task": "dsh.scan_operations", "schedule": 5.0})
