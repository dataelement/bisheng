"""T616: actual Celery registration, queue routing and Beat recovery."""

import bisheng.worker as registered
from bisheng.worker import config
from bisheng.worker.knowledge import processing_jobs
from bisheng.worker.main import bisheng_celery


def test_processing_tasks_export_actual_registered_handlers_on_knowledge_queue():
    for name in ("execute_processing_job", "dispatch_pending_processing_jobs"):
        task = getattr(registered, name)
        assert task is getattr(processing_jobs, name)
        assert bisheng_celery.tasks[task.name] is task
        routed = bisheng_celery.amqp.router.route({}, task.name)
        assert routed["queue"].name == "knowledge_celery"


def test_beat_scans_durable_intent_periodically_through_actual_task():
    entry = config.beat_schedule["knowledge-processing-recovery"]
    assert entry["task"] == processing_jobs.SCAN_TASK
    assert 0 < entry["schedule"] <= 60
    assert not entry.get("args") and not entry.get("kwargs")
    assert bisheng_celery.conf.beat_schedule["knowledge-processing-recovery"] == entry
