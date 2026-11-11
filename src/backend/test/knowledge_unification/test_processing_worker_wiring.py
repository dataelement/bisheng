"""T616: actual Celery registration, queue routing and Beat recovery."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def actual_worker():
    # Root conftest pre-mocks Celery globally. A fresh interpreter exercises
    # real registration without undoing another test's module state. Only log
    # file setup is isolated; every socket connect is rejected before IO.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import socket
def offline(*args, **kwargs):
    raise AssertionError("worker import attempted network IO")
socket.socket.connect = offline
import bisheng.core.logger
bisheng.core.logger.set_logger_config = lambda conf: None
import bisheng.worker as registered
from bisheng.worker import config
from bisheng.worker.knowledge import processing_jobs
from bisheng.worker.main import bisheng_celery
tasks = []
for name in ("execute_processing_job", "dispatch_pending_processing_jobs"):
    task = getattr(registered, name)
    assert task is getattr(processing_jobs, name)
    assert bisheng_celery.tasks[task.name].run == task.run
    tasks.append(bisheng_celery.amqp.router.route({}, task.name)["queue"].name)
entry = config.beat_schedule["knowledge-processing-recovery"]
assert entry == bisheng_celery.conf.beat_schedule["knowledge-processing-recovery"]
print(json.dumps({"tasks": tasks, "entry": entry, "scan": processing_jobs.SCAN_TASK}))
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_processing_tasks_export_actual_registered_handlers_on_knowledge_queue(actual_worker):
    assert actual_worker["tasks"] == ["knowledge_celery", "knowledge_celery"]


def test_beat_scans_durable_intent_periodically_through_actual_task(actual_worker):
    entry = actual_worker["entry"]
    assert entry["task"] == actual_worker["scan"]
    assert 0 < entry["schedule"] <= 60
    assert not entry.get("args") and not entry.get("kwargs")
