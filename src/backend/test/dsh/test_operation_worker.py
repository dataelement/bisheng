"""覆盖 AC: AC-09, AC-11, AC-23, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-33, AC-34."""

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context import tenant as context
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository
from bisheng.dsh.domain.services.profile import DshProfileService, profile_scope
from test.dsh.test_policy_repository import NOW, sql_store  # noqa: F401


@pytest.fixture
def operation_scope(sql_store):  # noqa: F811
    @contextmanager
    def scope():
        with Session(sql_store) as session, session.begin():
            yield DshOperationRepository(session)

    return scope


async def test_profile_response_loss_retries_same_snapshot(operation_scope):
    from bisheng.worker.dsh.profiles import ProfileOutboxWorker

    state = {"now": NOW}
    gateway = SimpleNamespace(request=AsyncMock(side_effect=[TimeoutError(), {"accepted": 1}]))
    snapshot = {
        "tenant_id": "2",
        "user_id": "20",
        "username": "Before",
        "display_name": "Before",
        "profile_version": 4,
    }
    with operation_scope() as repo:
        operation_id = DshProfileService.record_change(repo.session, snapshot).operation_id
    worker = ProfileOutboxWorker(repository_scope=operation_scope, gateway=gateway, now=lambda: state["now"])
    result = await worker.resume(operation_id)
    assert result["status"] == "PROCESSING"
    state["now"] += timedelta(seconds=31)
    result = await worker.resume(operation_id)
    assert result["status"] == "SUCCEEDED"
    assert gateway.request.await_args_list[0] == gateway.request.await_args_list[1]
    assert result["payload"] == snapshot


async def test_dispatch_uses_durable_action_and_restores_all_tenant_context(operation_scope):
    from bisheng.worker.dsh.operations import dispatch_operation

    with operation_scope() as repo:
        operation_id = DshProfileService.record_change(
            repo.session,
            {
                "tenant_id": "2",
                "user_id": "20",
                "username": "B",
                "display_name": "B",
                "profile_version": 1,
            },
        ).operation_id
    observed = []

    async def resume(op_id):
        observed.append((context.get_current_tenant_id(), context.is_tenant_filter_bypassed()))
        raise TimeoutError()

    runtime = SimpleNamespace(repository_scope=operation_scope, profiles=SimpleNamespace(resume=resume))
    token = context._bypass_tenant_filter.set(True)
    try:
        with pytest.raises(TimeoutError):
            await dispatch_operation({"tenant_id": 2}, 2, operation_id, runtime)
        assert context.is_tenant_filter_bypassed() is True
        assert observed == [(2, False)]
        with pytest.raises(ValueError):
            await dispatch_operation({"tenant_id": 3}, 2, operation_id, runtime)
    finally:
        context._bypass_tenant_filter.reset(token)
    with profile_scope(3):
        with pytest.raises(DshOperationConflictError):
            await dispatch_operation({"tenant_id": 3}, 3, operation_id, runtime)
    assert observed == [(2, False)]


async def test_due_scan_finds_lost_delivery_and_ignores_live_lease(operation_scope):
    with operation_scope() as repo:
        for version in (1, 2):
            DshProfileService.record_change(
                repo.session,
                {
                    "tenant_id": "2",
                    "user_id": "20",
                    "username": "B",
                    "display_name": "B",
                    "profile_version": version,
                },
            )
        due = repo.due(now=NOW, limit=100)
        assert len(due) == 2
        repo.claim(due[0].operation_id, now=NOW)
        assert len(repo.due(now=NOW, limit=100)) == 1
        assert len(repo.due(now=NOW + timedelta(seconds=31), limit=100)) == 2


def test_profile_sweep_batches_fit_signed_body_limit():
    import json

    from bisheng.worker.dsh.profiles import profile_batches

    profiles = [
        {
            "tenant_id": "2",
            "user_id": str(index + 1),
            "username": "用" * 128,
            "display_name": "名" * 128,
            "profile_version": 1,
        }
        for index in range(100)
    ]
    batches = list(profile_batches(profiles))
    assert len(batches) > 1
    assert [item for batch in batches for item in batch] == profiles
    assert all(
        len(batch) <= 100
        and len(json.dumps({"items": batch}, ensure_ascii=False, separators=(",", ":")).encode()) <= 65536
        for batch in batches
    )


async def test_oversized_profile_is_terminal_audit_not_infinite_retry(operation_scope):
    from bisheng.worker.dsh.profiles import ProfileOutboxWorker

    gateway = SimpleNamespace(request=AsyncMock())
    snapshot = {
        "tenant_id": "2",
        "user_id": "20",
        "username": "x" * 65536,
        "display_name": "Name",
        "profile_version": 1,
    }
    with operation_scope() as repo:
        operation_id = DshProfileService.record_change(repo.session, snapshot).operation_id
    result = await ProfileOutboxWorker(repository_scope=operation_scope, gateway=gateway, now=lambda: NOW).resume(
        operation_id
    )
    assert result["status"] == "FAILED" and result["result_code"] == "invalid_request"
    gateway.request.assert_not_awaited()
