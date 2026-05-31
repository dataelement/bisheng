from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_all_configured_beat_tasks_are_registered_by_worker_package() -> None:
    """Celery beat must not publish tasks that workers never import."""
    script = r"""
import json

from bisheng.common.services.config_service import settings
from bisheng.worker.main import bisheng_celery

scheduled_tasks = sorted({
    task_info["task"]
    for task_info in settings.celery_task.beat_schedule.values()
})
missing_tasks = [
    task_name
    for task_name in scheduled_tasks
    if task_name not in bisheng_celery.tasks
]

print("MISSING_BEAT_TASKS=" + json.dumps(missing_tasks, ensure_ascii=False))
raise SystemExit(1 if missing_tasks else 0)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
