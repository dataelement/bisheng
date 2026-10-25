"""Only platform policy intents remain dispatchable. 覆盖 AC: AC-04, AC-10."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import Session

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context import tenant as context
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository
from bisheng.worker.dsh.operations import dispatch_operation
from test.dsh.test_policy_repository import NOW, sql_store  # noqa: F401


@pytest.fixture
def operation_scope(sql_store):  # noqa: F811
    @contextmanager
    def scope():
        with Session(sql_store) as session, session.begin():
            yield DshOperationRepository(session)

    return scope


async def test_dispatch_policy_uses_trusted_tenant_and_preserves_scope(operation_scope):
    operation = SimpleNamespace(action="UPDATE_POLICY")

    @contextmanager
    def scope():
        yield SimpleNamespace(get=lambda _: operation)

    observed = []

    async def resume(_):
        observed.append((context.get_current_tenant_id(), context.is_tenant_filter_bypassed()))
        return "done"

    runtime = SimpleNamespace(repository_scope=scope, policy=SimpleNamespace(resume=resume))
    token = context._bypass_tenant_filter.set(True)
    try:
        assert await dispatch_operation({"tenant_id": 2}, 2, "operation", runtime) == "done"
        assert observed == [(2, False)]
        assert context.is_tenant_filter_bypassed()
        with pytest.raises(ValueError):
            await dispatch_operation({"tenant_id": 3}, 2, "operation", runtime)
        operation.action = "SYNC_PROFILE"
        with pytest.raises(DshOperationConflictError):
            await dispatch_operation({"tenant_id": 2}, 2, "operation", runtime)
    finally:
        token.var.reset(token)


def test_due_scan_excludes_retired_remote_intents(operation_scope):
    with operation_scope() as repository:
        for action in ("SYNC_PROFILE", "UPDATE_POLICY"):
            repository.session.add(
                DshAdminOperation(
                    operation_id=str(uuid4()),
                    tenant_id=2,
                    user_id=20,
                    actor_user_id=90,
                    action=action,
                    expected_policy_version=0,
                    payload_hash="x" * 64,
                    payload={},
                )
            )
        repository.session.flush()
        due = repository.due(now=NOW, limit=100)
        assert [row.action for row in due] == ["UPDATE_POLICY"]
