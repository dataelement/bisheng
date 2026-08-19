from __future__ import annotations

from pathlib import Path

from bisheng.core.config.settings import CeleryConf

KNOWLEDGE_TASK_PREFIX = "bisheng.worker.knowledge.file_change_tasks"
EXPECTED_FILE_CHANGE_BEAT_TASKS = {
    "file_change_approver_reconcile": f"{KNOWLEDGE_TASK_PREFIX}.reconcile_all_file_change_approvers",
    "file_change_deferred_watchdog": f"{KNOWLEDGE_TASK_PREFIX}.watchdog_all_file_change_executions",
    "file_change_execution_compensation": f"{KNOWLEDGE_TASK_PREFIX}.compensate_all_file_change_execution_steps",
    "file_change_cleanup": f"{KNOWLEDGE_TASK_PREFIX}.cleanup_all_file_change_residue",
}


def test_file_change_beat_registers_knowledge_owned_cross_tenant_coordinators():
    schedule = CeleryConf(beat_schedule={}).beat_schedule

    for schedule_name, task_name in EXPECTED_FILE_CHANGE_BEAT_TASKS.items():
        entry = schedule[schedule_name]
        assert entry["task"] == task_name
        assert entry["schedule"] is not None
        assert not entry.get("args")
        assert not entry.get("kwargs")


def test_file_change_beat_preserves_operator_schedule_overrides():
    configured = {
        name: {"task": task_name, "schedule": 17.0} for name, task_name in EXPECTED_FILE_CHANGE_BEAT_TASKS.items()
    }
    schedule = CeleryConf(beat_schedule=configured).beat_schedule
    assert all(schedule[name]["schedule"] == 17.0 for name in configured)


def test_worker_config_routes_every_f046_task_to_knowledge_queue_but_not_decision_delivery():
    config_path = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "config.py"
    source = config_path.read_text(encoding="utf-8")
    assert f'"{KNOWLEDGE_TASK_PREFIX}.*"' in source
    assert '"queue": "knowledge_celery"' in source
    assert "bisheng.worker.approval.decision_delivery_tasks.*" not in source


def test_root_worker_imports_new_knowledge_tasks_and_never_old_approval_module():
    worker_source = (Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "bisheng.worker.knowledge.file_change_tasks" in worker_source
    assert "bisheng.worker.approval.file_change_tasks" not in worker_source
