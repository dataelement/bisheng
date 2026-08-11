from __future__ import annotations

from bisheng.core.config.settings import CeleryConf

EXPECTED_FILE_CHANGE_BEAT_TASKS = {
    "file_change_approver_reconcile": ("bisheng.worker.approval.file_change_tasks.reconcile_all_file_change_approvers"),
    "file_change_deferred_watchdog": ("bisheng.worker.approval.file_change_tasks.watchdog_all_file_change_executions"),
    "file_change_execution_compensation": (
        "bisheng.worker.approval.file_change_tasks.compensate_all_file_change_execution_steps"
    ),
    "file_change_cleanup": ("bisheng.worker.approval.file_change_tasks.cleanup_all_file_change_residue"),
}


def test_file_change_beat_registers_single_cross_tenant_coordinators_on_default_queue():
    schedule = CeleryConf(beat_schedule={}).beat_schedule

    for schedule_name, task_name in EXPECTED_FILE_CHANGE_BEAT_TASKS.items():
        entry = schedule[schedule_name]
        assert entry["task"] == task_name
        assert entry["schedule"] is not None
        assert not entry.get("args")
        assert not entry.get("kwargs")
        assert "queue" not in entry.get("options", {})


def test_file_change_beat_preserves_operator_schedule_overrides():
    custom = 17.0
    configured = {
        name: {"task": task_name, "schedule": custom} for name, task_name in EXPECTED_FILE_CHANGE_BEAT_TASKS.items()
    }

    schedule = CeleryConf(beat_schedule=configured).beat_schedule

    assert all(schedule[name]["schedule"] == custom for name in configured)
