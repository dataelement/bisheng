from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(
    acks_late=True, time_limit=720, soft_time_limit=700, name="bisheng.worker.knowledge.background_jobs.drain"
)
def drain_knowledge_background_jobs():
    from bisheng.knowledge.domain.services.knowledge_background_service import KnowledgeBackgroundService

    return run_async_task(lambda: KnowledgeBackgroundService().drain(limit=100))


schedule = dict(bisheng_celery.conf.beat_schedule or {})
schedule.setdefault(
    "knowledge_background_jobs", {"task": "bisheng.worker.knowledge.background_jobs.drain", "schedule": 60.0}
)
bisheng_celery.conf.beat_schedule = schedule
