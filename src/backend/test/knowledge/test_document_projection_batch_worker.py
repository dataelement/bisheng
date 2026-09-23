"""批量任务必须发送一个完整 ID 列表, 并兼容同入口的旧消息。"""

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setitem(sys.modules, "bisheng.worker._asyncio_utils", SimpleNamespace(run_async_task=MagicMock()))
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.approval.tasks",
        SimpleNamespace(
            execute_approval_outbox=MagicMock(),
            retry_approval_outbox=MagicMock(),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "bisheng.worker.main",
        SimpleNamespace(
            bisheng_celery=SimpleNamespace(task=lambda **kwargs: lambda function: function),
        ),
    )
    path = Path(__file__).resolve().parents[2] / "bisheng/worker/knowledge/document_projection.py"
    spec = importlib.util.spec_from_file_location("projection_batch_worker_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    return module


def test_producer_sends_one_message_for_more_than_an_internal_batch(worker, monkeypatch):
    publish = MagicMock()
    monkeypatch.setattr(worker.process_document_projection, "apply_async", publish, raising=False)
    worker.enqueue_document_projection_entries(tenant_id=7, entry_ids=[*list(range(1, 1502)), 1, 2])
    publish.assert_called_once_with(
        kwargs={"tenant_id": 7, "entry_ids": list(range(1, 1502))},
        headers={"tenant_id": 7},
        queue="celery",
    )
    worker.enqueue_document_projection_entries(tenant_id=7, entry_ids=[])
    assert publish.call_count == 1


@pytest.mark.parametrize("kwargs", [{"entry_id": 41}, {"entry_ids": [41, 41]}])
def test_same_task_accepts_old_and_new_message_shape(worker, monkeypatch, kwargs):
    execute = AsyncMock(return_value={"total": 1})
    monkeypatch.setattr(worker, "_process_projection_batch_async", execute)
    monkeypatch.setattr(worker, "run_async_task", lambda function: asyncio.run(function()))
    assert worker.process_document_projection(SimpleNamespace(), tenant_id=7, **kwargs) == {"total": 1}
    assert execute.await_args.args[:2] == (7, [41])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tenant_id": 8, "entry_ids": [1]},
        {"tenant_id": 7, "entry_ids": [True]},
        {"tenant_id": 7, "entry_id": 1, "entry_ids": [2]},
        {"tenant_id": 7, "entry_ids": [-1]},
    ],
)
def test_invalid_or_cross_tenant_message_never_starts_io(worker, monkeypatch, kwargs):
    execute = MagicMock()
    monkeypatch.setattr(worker, "run_async_task", execute)
    with pytest.raises(ValueError):
        worker.process_document_projection(SimpleNamespace(), **kwargs)
    execute.assert_not_called()


async def test_content_rebuild_is_published_to_parse_worker(worker, monkeypatch):
    publish = MagicMock()
    monkeypatch.setattr(worker.rebuild_document_content, "apply_async", publish, raising=False)
    await worker._dispatch_content_rebuild(7, [101, 102], "rebuild:token")
    publish.assert_called_once_with(
        kwargs={"tenant_id": 7, "entry_ids": [101, 102], "rebuild_owner": "rebuild:token"},
        headers={"tenant_id": 7},
        queue="knowledge_celery",
        task_id="rebuild:token",
        retry=False,
    )


def test_content_worker_enables_heavy_processing_after_tenant_validation(worker, monkeypatch):
    execute = AsyncMock(return_value={"total": 1})
    monkeypatch.setattr(worker, "_process_projection_batch_async", execute)
    monkeypatch.setattr(worker, "run_async_task", lambda function: asyncio.run(function()))
    assert worker.rebuild_document_content(SimpleNamespace(), 7, [101, 101], "rebuild:token") == {"total": 1}
    assert execute.await_args.args[:2] == (7, [101])
    assert execute.await_args.kwargs == {
        "allow_content_rebuild": True,
        "handoff_owner": "rebuild:token",
        "content_manifests": None,
    }
    with pytest.raises(ValueError, match="tenant"):
        worker.rebuild_document_content(SimpleNamespace(), 8, [101], "rebuild:token")


def test_registered_rebuild_task_uses_real_celery_parse_route():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from bisheng.worker.main import bisheng_celery
prefix = "bisheng.worker.knowledge.document_projection."
for name, queue in (("rebuild_document_content", "knowledge_celery"), ("process_document_projection", "celery")):
    assert prefix + name in bisheng_celery.tasks
    route = bisheng_celery.amqp.router.route({}, prefix + name)
    assert route["queue"].name == queue, route
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
