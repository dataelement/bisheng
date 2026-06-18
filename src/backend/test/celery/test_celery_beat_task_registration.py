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


def test_derived_telemetry_beat_tasks_use_default_daily_schedule() -> None:
    """Derived telemetry tasks must stay on the backend default beat cadence."""
    script = r"""
import json

from bisheng.common.services.config_service import settings

expected = {
    "telemetry_sync_mid_active_user": "bisheng.worker.telemetry.derived_mid_table.sync_mid_active_user",
    "telemetry_sync_mid_doc_parse_dtl": "bisheng.worker.telemetry.derived_mid_table.sync_mid_doc_parse_dtl",
    "telemetry_sync_mid_knowledge_file_increment": (
        "bisheng.worker.telemetry.derived_mid_table.sync_mid_knowledge_file_increment"
    ),
    "telemetry_sync_mid_model_call_dtl": "bisheng.worker.telemetry.derived_mid_table.sync_mid_model_call_dtl",
    "telemetry_sync_mid_sessions_increment": "bisheng.worker.telemetry.derived_mid_table.sync_mid_sessions_increment",
    "telemetry_sync_mid_tool_call_dtl": "bisheng.worker.telemetry.derived_mid_table.sync_mid_tool_call_dtl",
    "telemetry_sync_mid_session_run_dtl": "bisheng.worker.telemetry.derived_mid_table.sync_mid_session_run_dtl",
}

errors = []
for key, task_name in expected.items():
    task_info = settings.celery_task.beat_schedule.get(key)
    if not task_info:
        errors.append(f"missing:{key}")
        continue
    if task_info["task"] != task_name:
        errors.append(f"task:{key}:{task_info['task']}")
    schedule = task_info["schedule"]
    if getattr(schedule, "_orig_minute", None) != "30" or getattr(schedule, "_orig_hour", None) != "0":
        errors.append(f"schedule:{key}:{schedule!r}")

print("DERIVED_TELEMETRY_ERRORS=" + json.dumps(errors, ensure_ascii=False))
raise SystemExit(1 if errors else 0)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
