from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must be installed before loading the worker module.

import importlib.util
import sys
import types
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

for module_name in ("celery", "celery.signals", "celery.schedules", "celery.app", "celery.app.task"):
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()

from test.fixtures.mock_services import premock_import_chain

premock_import_chain()


class _FakeTask:
    def __init__(self, function, options: dict) -> None:
        self.function = function
        self.options = options
        self.apply_async = MagicMock()

    def __call__(self, *args, **kwargs):
        return self.function(*args, **kwargs)


class _FakeCelery:
    def __init__(self) -> None:
        self.tasks: dict[str, _FakeTask] = {}

    def task(self, *decorator_args, **options):
        def decorate(function):
            task = _FakeTask(function, options)
            self.tasks[function.__name__] = task
            return task

        if decorator_args and callable(decorator_args[0]) and len(decorator_args) == 1:
            return decorate(decorator_args[0])
        return decorate


fake_celery = _FakeCelery()
fake_worker_pkg = types.ModuleType("bisheng.worker")
fake_worker_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules["bisheng.worker"] = fake_worker_pkg

fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = fake_celery
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.approval.domain.models.approval_instance import (
    ApprovalException,
    ApprovalExceptionType,
    ApprovalInstance,
    ApprovalInstanceStatus,
)
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeRequest,
    KnowledgeSpaceFileChangeResourceType,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_scenario_handler import (
    FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeScenarioHandler,
)

_WORKER_PATH = Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "approval" / "file_change_tasks.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("file_change_reconcile_worker_test_module", _WORKER_PATH)
assert _WORKER_SPEC and _WORKER_SPEC.loader
_WORKER_MODULE = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(_WORKER_MODULE)


@pytest.fixture(autouse=True)
def reset_worker_state(request):
    tenant_id = (
        23
        if request.node.name
        == "test_repository_cursor_handles_more_than_batch_same_timestamp_cross_tenant_and_empty_page"
        else None
    )
    token = current_tenant_id.set(tenant_id)
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    yield
    current_tenant_id.reset(token)


def test_worker_tasks_use_default_queue_and_exponential_backoff():
    assert {
        "reconcile_space_file_change_approvers",
        "reconcile_tenant_file_change_approvers",
        "reconcile_all_file_change_approvers",
    }.issubset(fake_celery.tasks)

    for task_name in (
        "reconcile_space_file_change_approvers",
        "reconcile_tenant_file_change_approvers",
    ):
        options = fake_celery.tasks[task_name].options
        assert options["bind"] is True
        assert options["acks_late"] is True
        assert options["autoretry_for"] == (Exception,)
        assert options["retry_backoff"] is True
        assert options["retry_jitter"] is True
        assert options["retry_kwargs"]["max_retries"] > 0
        assert "queue" not in options

    assert "queue" not in fake_celery.tasks["reconcile_all_file_change_approvers"].options


@pytest.mark.parametrize(
    "task_name,args",
    [
        ("reconcile_space_file_change_approvers", (8,)),
        ("reconcile_tenant_file_change_approvers", ()),
    ],
)
def test_tenant_worker_restores_header_context_and_resets_outer_context(
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
    args: tuple,
):
    observed: list[int | None] = []

    def fake_run_async_task(coroutine_factory):
        observed.append(get_current_tenant_id())
        coroutine = coroutine_factory()
        coroutine.close()
        return {"ok": True}

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", fake_run_async_task)
    outer_token = set_current_tenant_id(99)
    try:
        task = getattr(_WORKER_MODULE, task_name)
        result = task(SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": "23"})), *args)
        assert result == {"ok": True}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


def test_tenant_worker_resets_outer_context_when_execution_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        _WORKER_MODULE,
        "run_async_task",
        MagicMock(side_effect=RuntimeError("injected worker failure")),
    )
    outer_token = set_current_tenant_id(99)
    try:
        with pytest.raises(RuntimeError, match="injected worker failure"):
            _WORKER_MODULE.reconcile_space_file_change_approvers(
                SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 23})),
                8,
            )
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.parametrize("headers", [None, {}, {"tenant_id": None}, {"tenant_id": "bad"}, {"tenant_id": 0}])
def test_tenant_worker_fails_closed_without_positive_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
):
    run_async_task = MagicMock()
    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run_async_task)

    with pytest.raises(ValueError, match="tenant_id header"):
        _WORKER_MODULE.reconcile_space_file_change_approvers(
            SimpleNamespace(request=SimpleNamespace(headers=headers)),
            8,
        )

    run_async_task.assert_not_called()


async def test_permission_event_space_worker_calls_full_handler_and_continues_with_header(
    monkeypatch: pytest.MonkeyPatch,
):
    handler = SimpleNamespace(
        reconcile_space_pending_approvers=AsyncMock(
            return_value={
                "processed": 2,
                "failed": 0,
                "has_more": True,
                "next_after_instance_id": 102,
            }
        )
    )
    monkeypatch.setattr(_WORKER_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))

    result = await _WORKER_MODULE._reconcile_space_async(
        tenant_id=23,
        space_id=8,
        after_instance_id=0,
    )

    assert result["processed"] == 2
    handler.reconcile_space_pending_approvers.assert_awaited_once_with(
        tenant_id=23,
        space_id=8,
        trigger="permission_event",
        after_instance_id=0,
        limit=_WORKER_MODULE.RECONCILE_BATCH_SIZE,
    )
    _WORKER_MODULE.reconcile_space_file_change_approvers.apply_async.assert_called_once_with(
        args=[8],
        kwargs={"after_instance_id": 102},
        headers={"tenant_id": 23},
    )


async def test_tenant_page_calls_full_handler_and_uses_stable_cursor_for_continuation(
    monkeypatch: pytest.MonkeyPatch,
):
    handler = SimpleNamespace(
        reconcile_tenant_pending_approvers=AsyncMock(
            return_value={
                "processed": 2,
                "failed": 0,
                "has_more": True,
                "next_after_update_time": "2026-08-10T09:30:00",
                "next_after_request_id": 202,
            }
        )
    )
    monkeypatch.setattr(_WORKER_MODULE, "build_runtime_handler", AsyncMock(return_value=handler))

    result = await _WORKER_MODULE._reconcile_tenant_async(
        tenant_id=23,
        after_update_time=None,
        after_request_id=0,
    )

    assert result["processed"] == 2
    handler.reconcile_tenant_pending_approvers.assert_awaited_once_with(
        tenant_id=23,
        trigger="beat",
        after_update_time=None,
        after_request_id=0,
        limit=_WORKER_MODULE.RECONCILE_BATCH_SIZE,
    )
    _WORKER_MODULE.reconcile_tenant_file_change_approvers.apply_async.assert_called_once_with(
        kwargs={
            "after_update_time": "2026-08-10T09:30:00",
            "after_request_id": 202,
        },
        headers={"tenant_id": 23},
    )


async def test_beat_enumerates_once_under_bypass_and_isolates_tenant_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    events: list[str] = []

    @contextmanager
    def tracked_bypass():
        events.append("bypass_enter")
        try:
            yield
        finally:
            events.append("bypass_exit")

    async def load_tenants():
        events.append("load")
        return [11, 12, 13]

    def dispatch(*, kwargs, headers):
        events.append(f"dispatch:{headers['tenant_id']}")
        if headers["tenant_id"] == 12:
            raise RuntimeError("broker unavailable for tenant 12")

    monkeypatch.setattr(_WORKER_MODULE, "bypass_tenant_filter", tracked_bypass)
    monkeypatch.setattr(_WORKER_MODULE, "_load_active_tenant_ids", load_tenants)
    _WORKER_MODULE.reconcile_tenant_file_change_approvers.apply_async.side_effect = dispatch

    result = await _WORKER_MODULE._coordinate_all_tenants_async()

    assert result == {"tenant_count": 3, "dispatched": 2, "failed": 1}
    assert events == [
        "bypass_enter",
        "load",
        "bypass_exit",
        "dispatch:11",
        "dispatch:12",
        "dispatch:13",
    ]
    for call in _WORKER_MODULE.reconcile_tenant_file_change_approvers.apply_async.call_args_list:
        assert call.kwargs["headers"] == {"tenant_id": call.kwargs["headers"]["tenant_id"]}
        assert "queue" not in call.kwargs


@pytest_asyncio.fixture
async def reconcile_repository_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ApprovalInstance.__table__,
        ApprovalException.__table__,
        KnowledgeSpaceFileChangeRequest.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    yield engine
    await engine.dispose()


async def _insert_candidate(
    session: AsyncSession,
    *,
    tenant_id: int,
    request_id: int,
    instance_id: int,
    space_id: int,
    update_time: datetime,
    status: str = ApprovalInstanceStatus.PENDING,
    exception_type: str | None = None,
) -> None:
    session.add(
        ApprovalInstance(
            id=instance_id,
            tenant_id=tenant_id,
            scenario_code=FILE_CHANGE_SCENARIO_CODE,
            scenario_name="file change",
            handler_key=FILE_CHANGE_SCENARIO_CODE,
            business_key=f"change:{tenant_id}:{request_id}",
            business_resource_type="knowledge_space_file_change",
            business_resource_id=str(request_id),
            business_name=f"request-{request_id}",
            applicant_user_id=7,
            applicant_user_name="applicant",
            status=status,
        )
    )
    session.add(
        KnowledgeSpaceFileChangeRequest(
            id=request_id,
            tenant_id=tenant_id,
            space_id=space_id,
            action=KnowledgeSpaceFileChangeAction.RENAME,
            resource_type=KnowledgeSpaceFileChangeResourceType.KNOWLEDGE_FILE,
            resource_id=1000 + request_id,
            applicant_user_id=7,
            approval_instance_id=instance_id,
            update_time=update_time,
        )
    )
    if exception_type is not None:
        session.add(
            ApprovalException(
                tenant_id=tenant_id,
                instance_id=instance_id,
                exception_type=exception_type,
                status="open",
            )
        )


async def test_repository_cursor_handles_more_than_batch_same_timestamp_cross_tenant_and_empty_page(
    reconcile_repository_engine,
):
    same_time = datetime(2026, 8, 10, 9, 30, 0)
    async with AsyncSession(bind=reconcile_repository_engine, expire_on_commit=False) as session:
        async with session.begin():
            for offset in range(5):
                await _insert_candidate(
                    session,
                    tenant_id=23,
                    request_id=101 + offset,
                    instance_id=201 + offset,
                    space_id=8 + (offset % 2),
                    update_time=same_time,
                )
            await _insert_candidate(
                session,
                tenant_id=24,
                request_id=106,
                instance_id=206,
                space_id=8,
                update_time=same_time,
            )
            await _insert_candidate(
                session,
                tenant_id=23,
                request_id=107,
                instance_id=207,
                space_id=8,
                update_time=same_time,
                status=ApprovalInstanceStatus.EXECUTED,
            )
            await _insert_candidate(
                session,
                tenant_id=23,
                request_id=108,
                instance_id=208,
                space_id=8,
                update_time=same_time,
                status=ApprovalInstanceStatus.EXCEPTION,
                exception_type=ApprovalExceptionType.APPROVER_EMPTY,
            )
            await _insert_candidate(
                session,
                tenant_id=23,
                request_id=109,
                instance_id=209,
                space_id=8,
                update_time=same_time,
                status=ApprovalInstanceStatus.EXCEPTION,
                exception_type=ApprovalExceptionType.ROUTE_MISSING,
            )

        repository = KnowledgeSpaceFileChangeRequestRepository(session)
        collected = []
        cursor_time = None
        cursor_id = 0
        while True:
            page, has_more = await repository.list_reconcile_candidates(
                tenant_id=23,
                after_update_time=cursor_time,
                after_request_id=cursor_id,
                limit=2,
            )
            collected.extend(page)
            if not page:
                assert has_more is False
                break
            cursor_time = page[-1].update_time
            cursor_id = page[-1].request_id
            if not has_more:
                empty, empty_has_more = await repository.list_reconcile_candidates(
                    tenant_id=23,
                    after_update_time=cursor_time,
                    after_request_id=cursor_id,
                    limit=2,
                )
                assert empty == []
                assert empty_has_more is False
                break

    assert [row.request_id for row in collected] == [101, 102, 103, 104, 105, 108]
    assert {row.tenant_id for row in collected} == {23}
    assert len({row.instance_id for row in collected}) == len(collected)


async def test_handler_tenant_page_deduplicates_instances_and_isolates_one_failure():
    same_time = datetime(2026, 8, 10, 9, 30, 0)
    candidates = [
        SimpleNamespace(
            tenant_id=23,
            request_id=101,
            instance_id=201,
            space_id=8,
            update_time=same_time,
        ),
        SimpleNamespace(
            tenant_id=23,
            request_id=102,
            instance_id=201,
            space_id=8,
            update_time=same_time,
        ),
        SimpleNamespace(
            tenant_id=23,
            request_id=103,
            instance_id=203,
            space_id=9,
            update_time=same_time,
        ),
    ]
    reconcile = AsyncMock(side_effect=[RuntimeError("strict resolver unavailable"), None])
    handler = KnowledgeSpaceFileChangeScenarioHandler(
        tenant_candidate_loader=AsyncMock(return_value=(candidates, True)),
        reconcile_instance=reconcile,
    )

    tenant_token = set_current_tenant_id(23)
    try:
        result = await handler.reconcile_tenant_pending_approvers(
            tenant_id=23,
            trigger="beat",
            after_update_time=None,
            after_request_id=0,
            limit=3,
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert result == {
        "processed": 1,
        "failed": 1,
        "has_more": True,
        "next_after_update_time": same_time.isoformat(),
        "next_after_request_id": 103,
    }
    assert [call.kwargs["instance_id"] for call in reconcile.await_args_list] == [201, 203]
    assert all(call.kwargs["trigger"] == "beat" for call in reconcile.await_args_list)
