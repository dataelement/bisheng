"""批量任务必须发送一个完整 ID 列表, 并兼容同入口的旧消息。"""

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.knowledge.projection_scan_helpers import scan_state as _scan_state_fixture

scan_state = _scan_state_fixture


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
    for name, relative in (("bisheng.worker", "bisheng/worker"), ("bisheng.worker.knowledge", "bisheng/worker/knowledge")):
        if name in sys.modules:
            monkeypatch.setattr(sys.modules[name], "__path__", [str(Path(__file__).resolve().parents[2] / relative)], raising=False)
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


async def test_scan_delivery_only_processes_owned_entries_once(worker, scan_state, monkeypatch):
    ticket = await scan_state.reserve("projection", 41, "v1")
    execute = AsyncMock(return_value={"total": 1})
    monkeypatch.setattr(worker, "_process_projection_batch_async", execute)
    monkeypatch.setattr(worker, "run_async_task", lambda factory: factory())
    for _ in range(2):
        await worker.process_document_projection(None, tenant_id=7, entry_ids=[41], scan_tickets=[ticket])
    execute.assert_awaited_once()
    assert execute.await_args.args[:2] == (7, [41])


@pytest.mark.parametrize("still_pending,expected_status,expected_calls", [(True, "failed", 4), (False, "completed", 0)])
async def test_approval_recovery_has_finite_budget_and_skips_resolved_entries(
    worker, scan_state, monkeypatch, still_pending, expected_status, expected_calls,
):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def db():
        yield None

    action = AsyncMock(return_value=False)
    approvals = sys.modules["bisheng.worker.approval.tasks"]
    approvals._execute_approval_outbox_async = action
    approvals._retry_approval_outbox_async = action
    monkeypatch.setattr(worker, "run_async_task", lambda factory: factory())
    monkeypatch.setattr(worker, "get_async_db_session", db)
    monkeypatch.setattr(worker, "KnowledgeFileRepositoryImpl", lambda session: SimpleNamespace(
        has_preparing_approval_entries=AsyncMock(return_value=still_pending),
    ))
    monkeypatch.setattr(worker.ApprovalInstanceRepository, "get_outbox", AsyncMock(
        return_value=SimpleNamespace(status="failed", instance_id=101),
    ))
    for _ in range(4):
        ticket = await scan_state.reserve("approval", 91, "91", max_attempts=4)
        result = await worker.recover_document_projection_scan_item(7, ticket, {"outbox_id": 91})
        assert result["status"] == expected_status
        scan_state.clock[0] += 3601
    assert await scan_state.reserve("approval", 91, "91", max_attempts=4) is None
    assert action.await_count == expected_calls


def test_scan_request_uses_the_single_merged_task(worker, monkeypatch):
    publish = MagicMock()
    monkeypatch.setattr(worker.scan_document_projections, "apply_async", publish, raising=False)
    worker.enqueue_document_projection_entries(tenant_id=7, entry_ids=None)
    publish.assert_called_once_with(kwargs={"tenant_id": 7}, headers={"tenant_id": 7}, queue="celery")


@pytest.mark.parametrize("tenant_id", [8, 0, -1, True, None])
def test_merged_scan_rejects_mismatched_or_invalid_tenant(worker, monkeypatch, tenant_id):
    execute = MagicMock()
    monkeypatch.setattr(worker, "run_async_task", execute)
    with pytest.raises(ValueError):
        worker.scan_document_projections(tenant_id)
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
for name, queue in (("rebuild_document_content", "knowledge_celery"), ("process_document_projection", "celery"),
                    ("recover_scan_item", "celery"), ("scan_document_projections", "celery")):
    assert prefix + name in bisheng_celery.tasks
    route = bisheng_celery.amqp.router.route({}, prefix + name)
    assert route["queue"].name == queue, route
assert prefix + "fanout_document_projection_scan" not in bisheng_celery.tasks
assert prefix + "scan_tenant_document_projections" not in bisheng_celery.tasks
from bisheng.worker.knowledge._projection_scan import tenant_scan_context
from bisheng.worker.tenant_context import inject_tenant_header
from bisheng.core.context.tenant import get_current_tenant_id
previous = get_current_tenant_id()
with tenant_scan_context(7):
    headers = {"tenant_id": 1}
    inject_tenant_header(headers=headers)
    assert headers["tenant_id"] == 7
assert get_current_tenant_id() == previous
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
