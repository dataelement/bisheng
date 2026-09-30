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

required = {
    "bisheng.worker.knowledge.background_jobs.drain",
    "bisheng.worker.knowledge.portal_recommendation.rebuild_portal_recommendation_pools",
    "bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection_batch",
    "bisheng.worker.knowledge.portal_hot_search.rebuild_portal_hot_search_snapshot",
}
removed = {
    "bisheng.worker.knowledge.portal_recommendation.prepare_pool_rebuild",
    "bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection",
    "bisheng.worker.knowledge.portal_hot_search.trigger_portal_hot_search_rebuild",
    "bisheng.worker.knowledge.file_title_worker.extract_knowledge_file_title_celery",
}
missing_tasks.extend(sorted(required - set(bisheng_celery.tasks)))
assert bisheng_celery.conf.beat_schedule["knowledge_background_jobs"]["task"] == "bisheng.worker.knowledge.background_jobs.drain"
assert not removed.intersection(bisheng_celery.tasks), "obsolete knowledge tasks remain registered"

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
expected_times = {
    "telemetry_sync_mid_active_user": (1, 20),
    "telemetry_sync_mid_doc_parse_dtl": (1, 35),
    "telemetry_sync_mid_knowledge_file_increment": (0, 50),
    "telemetry_sync_mid_model_call_dtl": (1, 50),
    "telemetry_sync_mid_sessions_increment": (2, 10),
    "telemetry_sync_mid_tool_call_dtl": (2, 40),
    "telemetry_sync_mid_session_run_dtl": (3, 10),
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
    hour, minute = expected_times[key]
    if schedule.minute != {minute} or schedule.hour != {hour}:
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


def test_reconcile_schedules_are_staggered_and_preserve_overrides() -> None:
    """检查最终注册时间、原有执行次数和显式配置优先级。"""
    script = r"""
from celery.schedules import crontab
from bisheng.core.config.settings import CeleryConf
from bisheng.worker.main import bisheng_celery
from bisheng.worker.knowledge.fulltext_engagement import register_fulltext_engagement_beat_schedule

schedule = bisheng_celery.conf.beat_schedule
assert len(schedule) == 50
assert schedule["scan_portal_course_media_cleanup"]["schedule"] == 300.0

daily = {
    "daily_knowledge_fulltext_reconcile": (1, 0),
    "telemetry_sync_mid_knowledge_space_content_stat": (3, 40),
    "fanout_shared_storage_reconcile": (4, 20),
    "reconcile_knowledge_fulltext_engagement": (5, 0),
    "points_reconcile_balances": (5, 40),
}
for key, (hour, minute) in daily.items():
    cron = schedule[key]["schedule"]
    assert cron.hour == {hour} and cron.minute == {minute}, key
    assert len(cron.day_of_week) == 7 and len(cron.day_of_month) == 31 and len(cron.month_of_year) == 12, key

for key, minute in [("reconcile_all_organizations", 25), ("reconcile_user_tenant_assignments", 55)]:
    cron = schedule[key]["schedule"]
    assert cron.hour == {0, 6, 12, 18} and cron.minute == {minute}, key

for key, hour, minute, weekday in [
    ("portal_recommendation_full_weekly", 6, 40, 0),
    ("report_ts_conflicts_weekly", 9, 20, 1),
]:
    cron = schedule[key]["schedule"]
    assert cron.hour == {hour} and cron.minute == {minute} and cron.day_of_week == {weekday}, key

# 核验主配置与动态注册均尊重用户已配置的周期和参数。
keys = [*daily, "scan_portal_course_media_cleanup", "reconcile_all_organizations",
        "reconcile_user_tenant_assignments", "portal_recommendation_full_weekly", "report_ts_conflicts_weekly"]
overrides = {key: {**schedule[key], "schedule": crontab(hour=11, minute=17)}
             for key in keys if key != "daily_knowledge_fulltext_reconcile"}
conf = CeleryConf(beat_schedule=overrides)
bisheng_celery.conf.beat_schedule = conf.beat_schedule
register_fulltext_engagement_beat_schedule()
for key, expected in overrides.items():
    assert bisheng_celery.conf.beat_schedule[key] == expected, key
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
