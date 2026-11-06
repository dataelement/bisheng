"""Exercise recovery dispatch and worker retry without a live broker."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def worker_module(monkeypatch):
    from bisheng.worker import main

    registrations = {}

    def task(**options):
        def register(function):
            registrations[options["name"]] = options
            return function

        return register

    monkeypatch.setattr(main, "bisheng_celery", SimpleNamespace(task=task))
    path = Path(__file__).parents[2] / "bisheng/worker/knowledge/space_delete.py"
    spec = importlib.util.spec_from_file_location("space_delete_worker_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, registrations


async def test_scan_keeps_routing_other_tenants_when_one_publish_fails(monkeypatch):
    module, registrations = worker_module(monkeypatch)
    repository = SimpleNamespace(due_jobs=AsyncMock(return_value=[(42, "first"), (43, "second")]))
    monkeypatch.setattr(module, "KnowledgeSpaceDirectDeleteService", lambda: SimpleNamespace(repository=repository))
    dispatch = AsyncMock(side_effect=[ConnectionError("broker disconnected"), None])
    monkeypatch.setattr(module, "dispatch_delete_job", dispatch)
    assert await module._dispatch_pending() == 1
    assert [call.kwargs for call in dispatch.await_args_list] == [
        {"tenant_id": 42, "job_id": "first"},
        {"tenant_id": 43, "job_id": "second"},
    ]
    assert registrations[module.PURGE_TASK]["acks_late"] is True
    assert registrations[module.SCAN_TASK]["acks_late"] is True


def test_cleanup_error_reaches_celery_retry(monkeypatch):
    module, _ = worker_module(monkeypatch)
    failure = RuntimeError("external cleanup failed")
    monkeypatch.setattr(module, "run_async_task", MagicMock(side_effect=failure))
    task = SimpleNamespace(retry=MagicMock(side_effect=ValueError("retry requested")))
    with pytest.raises(ValueError, match="retry requested"):
        module.purge_space_delete(task, job_id="durable-job")
    task.retry.assert_called_once_with(exc=failure, countdown=60)


def test_recovery_schedule_and_queue_preserve_existing_configuration(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(
            celery_redis_url="redis://localhost/1",
            dsh=SimpleNamespace(enabled=False),
            celery_task=SimpleNamespace(
                task_routers={"existing-task": {"queue": "existing"}}, beat_schedule={"existing-scan": {"schedule": 10}}
            ),
        ),
    )
    path = Path(__file__).parents[2] / "bisheng/worker/config.py"
    spec = importlib.util.spec_from_file_location("delete_worker_config_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.task_routes["existing-task"] == {"queue": "existing"}
    assert module.task_routes["bisheng.worker.knowledge.space_delete.*"] == {"queue": "knowledge_celery"}
    assert module.beat_schedule["existing-scan"] == {"schedule": 10}
    assert module.beat_schedule["knowledge-space-delete-recovery"] == {
        "task": "bisheng.worker.knowledge.space_delete.dispatch_pending_deletes",
        "schedule": 60.0,
    }


def test_delete_model_is_discovered_for_schema_creation_and_tenant_filter():
    from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
    from bisheng.core.database.tenant_filter import _TENANT_AWARE_MODEL_MODULES

    name = "bisheng.knowledge.domain.models.knowledge_space_delete_job"
    assert name in discover_sqlmodel_module_names()
    assert name in _TENANT_AWARE_MODEL_MODULES
