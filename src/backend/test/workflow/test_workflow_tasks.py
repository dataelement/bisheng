import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

# The shared test bootstrap replaces ``bisheng.worker`` with a lightweight
# module. Give that stub a package path so this focused test can import the real
# workflow task module while retaining the mocked Celery application.
worker_package = ModuleType("bisheng.worker")
worker_package.__path__ = [str(Path(__file__).parents[2] / "bisheng" / "worker")]
sys.modules["bisheng.worker"] = worker_package
tasks = importlib.import_module("bisheng.worker.workflow.tasks")


@pytest.mark.parametrize(
    ("task", "runner_name"),
    [
        (tasks.execute_workflow, "_execute_workflow"),
        (tasks.continue_workflow, "_continue_workflow"),
    ],
)
def test_telemetry_failure_does_not_change_workflow_task_outcome(monkeypatch, task, runner_name):
    from bisheng.workflow.domain.repositories.creation_repository import CreationRepository

    monkeypatch.setattr(CreationRepository, "tenant_for_message", lambda _: 1)
    runner = Mock()
    monkeypatch.setattr(tasks, runner_name, runner)
    monkeypatch.setattr(
        tasks.WorkFlowService,
        "get_one_workflow_simple_info_sync",
        Mock(side_effect=RuntimeError("telemetry metadata unavailable")),
    )

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.worker import tenant_context as task_context

    # Direct .run bypasses Celery; do not let the shared MagicMock invent a header.
    monkeypatch.setattr(task_context, "current_task", SimpleNamespace(_get_current_object=lambda: None))
    with tenant_execution_scope(1):
        task.run("run-id", "workflow-id", "chat-id", 42)

    runner.assert_called_once_with("run-id", "workflow-id", "chat-id", 42, "platform")
