from __future__ import annotations

# ruff: noqa: E402, I001 -- fake Celery modules must exist before importing the worker.

import importlib.util
import sys
import types
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

for module_name in (
    "celery",
    "celery.signals",
    "celery.schedules",
    "celery.app",
    "celery.app.task",
):
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
# Do NOT replace the bisheng.worker package itself: these stubs live in
# sys.modules for the whole session, and other modules import names straight
# off the package (e.g. `from bisheng.worker import rebuild_knowledge_celery`).
# Only the two submodules that would pull in a live Celery app are stubbed.
fake_worker_main = types.ModuleType("bisheng.worker.main")
fake_worker_main.bisheng_celery = fake_celery
sys.modules["bisheng.worker.main"] = fake_worker_main

fake_asyncio_utils = types.ModuleType("bisheng.worker._asyncio_utils")
fake_asyncio_utils.run_async_task = MagicMock()
sys.modules["bisheng.worker._asyncio_utils"] = fake_asyncio_utils

from bisheng.core.context.tenant import (
    current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)
from bisheng.permission.domain.models.resource_user_invite_request import (
    ResourceUserInviteExecutionState,
    ResourceUserInviteRequest,
)
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
)

_WORKER_PATH = (
    Path(__file__).resolve().parents[2] / "bisheng" / "worker" / "permission" / "resource_user_invite_tasks.py"
)
_WORKER_SPEC = importlib.util.spec_from_file_location(
    "resource_user_invite_worker_test_module",
    _WORKER_PATH,
)
assert _WORKER_SPEC and _WORKER_SPEC.loader
_WORKER_MODULE = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(_WORKER_MODULE)

execute_resource_user_invite = _WORKER_MODULE.execute_resource_user_invite
_execute_resource_user_invite_async = _WORKER_MODULE._execute_resource_user_invite_async

TENANT_ID = 7


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ResourceUserInviteRequest.__table__.create)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    tenant_token = set_current_tenant_id(TENANT_ID)
    try:
        yield factory
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


@pytest.fixture(autouse=True)
def reset_worker_state():
    token = current_tenant_id.set(None)
    for task in fake_celery.tasks.values():
        task.apply_async.reset_mock()
        task.apply_async.side_effect = None
    yield
    current_tenant_id.reset(token)


async def _create_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: int = TENANT_ID,
    execution_state: str = ResourceUserInviteExecutionState.QUEUED,
    execution_token: str | None = None,
    result_snapshot: dict | None = None,
) -> ResourceUserInviteRequest:
    async with session_factory() as session, session.begin():
        row = ResourceUserInviteRequest(
            tenant_id=tenant_id,
            business_key="resource-user-invite:knowledge_space:88:user:201",
            active_marker=0,
            request_fingerprint="request-fingerprint",
            resource_type="knowledge_space",
            resource_id="88",
            resource_name="Docs",
            inviter_user_id=101,
            inviter_user_name="inviter-a",
            target_user_id=201,
            target_user_name="target-a",
            relation="editor",
            model_id="model-1",
            include_children=True,
            role_snapshot={"permissions": ["read", "write"]},
            role_fingerprint="role-fingerprint",
            approval_instance_id=501,
            decision_event_id=9001,
            execution_state=execution_state,
            execution_token=execution_token,
            result_snapshot=result_snapshot or {},
        )
        session.add(row)
        await session.flush()
        assert row.id is not None
    return row


async def _get_request(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: int,
) -> ResourceUserInviteRequest:
    async with session_factory() as session:
        row = await session.get(ResourceUserInviteRequest, request_id)
    assert row is not None
    return row


class FakeGrantRegistry:
    def __init__(self) -> None:
        self.execute_calls: list[ResourceGrantCommand] = []
        self.verify_calls: list[ResourceGrantCommand] = []
        self.authoritative_applied = False
        self.execute_marks_applied = True
        self.execute_error: Exception | None = None
        self.apply_before_error = False
        self.replace_execution_token: str | None = None
        self.states_seen: list[str] = []
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    async def execute(self, command: ResourceGrantCommand) -> None:
        self.execute_calls.append(command)
        if self.session_factory is not None:
            row = await _get_request(self.session_factory, command.request_id)
            self.states_seen.append(row.execution_state)
        if self.apply_before_error:
            self.authoritative_applied = True
        if self.replace_execution_token is not None and self.session_factory is not None:
            async with self.session_factory() as session, session.begin():
                result = await session.execute(
                    select(ResourceUserInviteRequest).where(
                        ResourceUserInviteRequest.tenant_id == command.tenant_id,
                        ResourceUserInviteRequest.id == command.request_id,
                    )
                )
                row = result.scalars().one()
                row.execution_token = self.replace_execution_token
                session.add(row)
        if self.execute_error is not None:
            raise self.execute_error
        if self.execute_marks_applied:
            self.authoritative_applied = True

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        self.verify_calls.append(command)
        return ResourceGrantVerificationResult(
            applied=self.authoritative_applied,
            result_snapshot={
                "request_id": command.request_id,
                "grant_visible": self.authoritative_applied,
            },
        )


class FakeBusinessNotificationService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def notify_execution_result(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _install_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    registry: FakeGrantRegistry,
) -> None:
    registry.session_factory = session_factory
    monkeypatch.setattr(_WORKER_MODULE, "get_async_db_session", session_factory)
    monkeypatch.setattr(
        _WORKER_MODULE,
        "_build_grant_executor_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        _WORKER_MODULE,
        "_build_business_notification_service",
        FakeBusinessNotificationService,
    )


def _run_coroutine(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(coroutine_factory):
        import asyncio

        return asyncio.run(coroutine_factory())

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run)


def test_worker_public_task_uses_default_queue_late_ack_and_retry_backoff() -> None:
    assert "execute_resource_user_invite" in fake_celery.tasks
    options = fake_celery.tasks["execute_resource_user_invite"].options

    assert options["bind"] is True
    assert options["acks_late"] is True
    assert options["autoretry_for"] == (Exception,)
    assert options["retry_backoff"] is True
    assert options["retry_jitter"] is True
    assert options["retry_kwargs"]["max_retries"] > 0
    assert "queue" not in options
    assert options["name"] == ("bisheng.worker.permission.resource_user_invite_tasks.execute_resource_user_invite")


def test_task_restores_explicit_tenant_header_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[int | None] = []

    def fake_run(coroutine_factory):
        observed.append(get_current_tenant_id())
        coroutine = coroutine_factory()
        coroutine.close()
        return {"status": "applied", "request_id": 41}

    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", fake_run)
    outer_token = set_current_tenant_id(99)
    try:
        result = execute_resource_user_invite(
            SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": "23"})),
            request_id=41,
        )
        assert result == {"status": "applied", "request_id": 41}
        assert observed == [23]
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


def test_task_restores_outer_tenant_context_when_execution_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _WORKER_MODULE,
        "run_async_task",
        MagicMock(side_effect=RuntimeError("grant backend unavailable")),
    )
    outer_token = set_current_tenant_id(99)
    try:
        with pytest.raises(RuntimeError, match="grant backend unavailable"):
            execute_resource_user_invite(
                SimpleNamespace(request=SimpleNamespace(headers={"tenant_id": 23})),
                request_id=41,
            )
        assert get_current_tenant_id() == 99
    finally:
        current_tenant_id.reset(outer_token)


@pytest.mark.parametrize(
    "headers",
    [
        None,
        {},
        {"tenant_id": None},
        {"tenant_id": True},
        {"tenant_id": "bad"},
        {"tenant_id": 0},
        {"tenant_id": -1},
    ],
)
def test_task_fails_closed_without_positive_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict | None,
) -> None:
    run_async_task = MagicMock()
    monkeypatch.setattr(_WORKER_MODULE, "run_async_task", run_async_task)

    with pytest.raises(ValueError, match="tenant_id header"):
        execute_resource_user_invite(
            SimpleNamespace(request=SimpleNamespace(headers=headers)),
            request_id=41,
        )

    run_async_task.assert_not_called()


async def test_queued_request_is_claimed_applied_and_releases_active_slot(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    result = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    persisted = await _get_request(session_factory, int(row.id))
    assert result["status"] == ResourceUserInviteExecutionState.APPLIED
    assert result["request_id"] == row.id
    assert result["execution_token"] == persisted.execution_token
    assert persisted.execution_state == ResourceUserInviteExecutionState.APPLIED
    assert persisted.active_marker == row.id
    assert persisted.error_summary is None
    assert persisted.result_snapshot == {
        "grant_result": {
            "request_id": row.id,
            "grant_visible": True,
        }
    }
    assert persisted.execution_token
    assert len(persisted.execution_token) <= 64
    assert registry.states_seen == [ResourceUserInviteExecutionState.APPLYING]
    assert len(registry.execute_calls) == len(registry.verify_calls) == 1
    assert registry.execute_calls[0] == registry.verify_calls[0]
    assert registry.execute_calls[0] == ResourceGrantCommand(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
        request_fingerprint="request-fingerprint",
        resource_type="knowledge_space",
        resource_id="88",
        inviter_user_id=101,
        target_user_id=201,
        relation="editor",
        model_id="model-1",
        include_children=True,
        role_snapshot={"permissions": ["read", "write"]},
        role_fingerprint="role-fingerprint",
    )


async def test_applied_result_preserves_subscriber_event_evidence_in_separate_snapshot_partition(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    decision_evidence = {
        "accepted_decision": "approved",
        "accepted_decision_version": 1,
        "accepted_event_id": 9001,
        "accepted_event_version": 1,
        "dispatch_state": "dispatched",
    }
    row = await _create_request(session_factory, result_snapshot=decision_evidence)
    registry = FakeGrantRegistry()
    _install_dependencies(monkeypatch, session_factory=session_factory, registry=registry)

    await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    persisted = await _get_request(session_factory, int(row.id))
    assert {key: persisted.result_snapshot[key] for key in decision_evidence} == decision_evidence
    assert persisted.result_snapshot["grant_result"] == {
        "request_id": row.id,
        "grant_visible": True,
    }


async def test_failed_then_retried_execution_preserves_subscriber_event_evidence(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    decision_evidence = {
        "accepted_decision": "approved",
        "accepted_decision_version": 1,
        "accepted_event_id": 9001,
        "accepted_event_version": 1,
        "dispatch_state": "dispatched",
    }
    row = await _create_request(session_factory, result_snapshot=decision_evidence)
    registry = FakeGrantRegistry()
    registry.execute_error = RuntimeError("temporary grant failure")
    _install_dependencies(monkeypatch, session_factory=session_factory, registry=registry)

    with pytest.raises(RuntimeError, match="temporary grant failure"):
        await _execute_resource_user_invite_async(tenant_id=TENANT_ID, request_id=int(row.id))
    failed = await _get_request(session_factory, int(row.id))
    assert failed.result_snapshot == decision_evidence

    registry.execute_error = None
    await _execute_resource_user_invite_async(tenant_id=TENANT_ID, request_id=int(row.id))
    applied = await _get_request(session_factory, int(row.id))
    assert {key: applied.result_snapshot[key] for key in decision_evidence} == decision_evidence


async def test_execute_failure_is_verified_then_persisted_only_in_permission_request(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    registry.execute_error = RuntimeError("openfga unavailable")
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    with pytest.raises(RuntimeError, match="openfga unavailable"):
        await _execute_resource_user_invite_async(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
        )

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.FAILED
    assert persisted.active_marker == 0
    assert persisted.execution_token
    assert persisted.error_summary == "RuntimeError"
    assert len(registry.execute_calls) == len(registry.verify_calls) == 1


async def test_execute_without_authoritative_visibility_is_failed_not_applied(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    registry.execute_marks_applied = False
    _install_dependencies(monkeypatch, session_factory=session_factory, registry=registry)

    with pytest.raises(RuntimeError, match=r"verified|visible|applied"):
        await _execute_resource_user_invite_async(tenant_id=TENANT_ID, request_id=int(row.id))

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.FAILED
    assert persisted.active_marker == 0
    assert len(registry.execute_calls) == len(registry.verify_calls) == 1


async def test_execute_ack_loss_uses_authoritative_verification_without_false_failure(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    registry.apply_before_error = True
    registry.execute_error = RuntimeError("grant response lost")
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    result = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    persisted = await _get_request(session_factory, int(row.id))
    assert result["status"] == ResourceUserInviteExecutionState.APPLIED
    assert persisted.execution_state == ResourceUserInviteExecutionState.APPLIED
    assert persisted.active_marker == row.id
    assert persisted.error_summary is None
    assert len(registry.execute_calls) == len(registry.verify_calls) == 1


async def test_repeated_task_is_idempotent_and_keeps_the_stable_execution_token(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    first = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )
    second = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    assert first == second
    assert len(registry.execute_calls) == 1
    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_token == first["execution_token"]
    assert persisted.execution_state == ResourceUserInviteExecutionState.APPLIED


async def test_failed_request_retries_the_same_request_with_the_same_execution_token(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    registry.execute_error = RuntimeError("temporary grant failure")
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    with pytest.raises(RuntimeError, match="temporary grant failure"):
        await _execute_resource_user_invite_async(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
        )
    failed = await _get_request(session_factory, int(row.id))
    failed_token = failed.execution_token
    failed_instance_id = failed.approval_instance_id

    registry.execute_error = None
    result = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    persisted = await _get_request(session_factory, int(row.id))
    assert result["request_id"] == row.id
    assert persisted.execution_state == ResourceUserInviteExecutionState.APPLIED
    assert persisted.execution_token == failed_token
    assert persisted.approval_instance_id == failed_instance_id
    assert len(registry.execute_calls) == 2


async def test_redelivery_of_applying_request_verifies_before_any_duplicate_execute(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(
        session_factory,
        execution_state=ResourceUserInviteExecutionState.APPLYING,
        execution_token="stable-generation-token",
    )
    registry = FakeGrantRegistry()
    registry.authoritative_applied = True
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    result = await _execute_resource_user_invite_async(
        tenant_id=TENANT_ID,
        request_id=int(row.id),
    )

    persisted = await _get_request(session_factory, int(row.id))
    assert result["status"] == ResourceUserInviteExecutionState.APPLIED
    assert persisted.execution_token == "stable-generation-token"
    assert registry.execute_calls == []
    assert len(registry.verify_calls) == 1


async def test_lost_execution_token_cas_cannot_finalize_another_worker_claim(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    registry.replace_execution_token = "newer-worker-token"
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    with pytest.raises(RuntimeError, match=r"claim|token|ownership"):
        await _execute_resource_user_invite_async(
            tenant_id=TENANT_ID,
            request_id=int(row.id),
        )

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.APPLYING
    assert persisted.execution_token == "newer-worker-token"
    assert persisted.active_marker == 0


async def test_tenant_mismatch_cannot_claim_or_execute_another_tenants_request(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    row = await _create_request(session_factory)
    registry = FakeGrantRegistry()
    _install_dependencies(
        monkeypatch,
        session_factory=session_factory,
        registry=registry,
    )

    mismatch_token = set_current_tenant_id(8)
    try:
        with pytest.raises((LookupError, RuntimeError, ValueError)):
            await _execute_resource_user_invite_async(
                tenant_id=8,
                request_id=int(row.id),
            )
    finally:
        current_tenant_id.reset(mismatch_token)

    persisted = await _get_request(session_factory, int(row.id))
    assert persisted.execution_state == ResourceUserInviteExecutionState.QUEUED
    assert persisted.execution_token is None
    assert registry.execute_calls == []
    assert registry.verify_calls == []


def test_worker_does_not_import_or_write_approval_persistence() -> None:
    source = _WORKER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "bisheng.approval.domain.models",
        "bisheng.approval.domain.repositories",
        "ApprovalException",
        "ApprovalOutbox",
    )
    assert not any(value in source for value in forbidden)
