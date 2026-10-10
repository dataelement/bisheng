"""Every beat-scheduled task must be reachable from the worker's task registry.

A beat entry only carries a task *name*. Celery resolves that name against the
tasks registered when ``bisheng.worker`` is imported, so a task whose module is
never imported there is scheduled forever and never runs: the worker just logs
``Received unregistered task`` every period and the periodic work silently does
not happen.

The check is on the import source rather than a live Celery registry because
importing every worker module pulls in the whole runtime; the registry is the
import list, so reading it is equivalent and cheap.
"""

from __future__ import annotations

import re
from pathlib import Path

from bisheng.core.config.settings import CeleryConf

_WORKER_ROOT = Path(__file__).resolve().parents[2] / "bisheng" / "worker"


def _registered_modules() -> set[str]:
    source = (_WORKER_ROOT / "__init__.py").read_text(encoding="utf-8")
    return set(re.findall(r"^from ([\w.]+) import", source, flags=re.MULTILINE))


def _scheduled_task_names() -> set[str]:
    schedule = CeleryConf(beat_schedule={}).beat_schedule
    return {entry["task"] for entry in schedule.values()}


def test_every_beat_scheduled_task_module_is_imported_by_the_worker_package():
    registered = _registered_modules()
    missing = {task_name for task_name in _scheduled_task_names() if task_name.rsplit(".", 1)[0] not in registered}
    assert not missing, (
        f"beat schedules tasks whose modules are never imported in bisheng/worker/__init__.py: {sorted(missing)}"
    )


def test_every_beat_scheduled_task_callable_exists_in_its_module():
    for task_name in _scheduled_task_names():
        module_path, attribute = task_name.rsplit(".", 1)
        relative = Path(*module_path.split(".")[2:]).with_suffix(".py")
        module_file = _WORKER_ROOT / relative
        assert module_file.is_file(), f"beat task {task_name} has no module at {module_file}"
        source = module_file.read_text(encoding="utf-8")
        assert re.search(rf"^def {re.escape(attribute)}\b", source, flags=re.MULTILINE), (
            f"beat task {task_name} names no task function in {module_file}"
        )
