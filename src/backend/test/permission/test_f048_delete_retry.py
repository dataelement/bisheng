"""Delete retries reuse the original ledger after the business row is gone."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor


def _runtime(status, *, state="CURRENT", version=1, operation_id=9):
    runtime = object.__new__(F048PermissionRuntime)
    runtime._runtime_catalog = AsyncMock(return_value=SimpleNamespace(store_id="store", model_id="model", release_id=1))
    runtime._state = SimpleNamespace(
        mode_for_target=AsyncMock(
            return_value=SimpleNamespace(
                version=version,
                parent_type="knowledge_space",
                parent_id="128",
                projection_state=state,
                operation_id=operation_id,
            )
        ),
        mark_projecting=AsyncMock(),
    )
    runtime._projection = SimpleNamespace(
        prepare=AsyncMock(return_value=SimpleNamespace(status=status, id=9)),
        execute=AsyncMock(return_value=SimpleNamespace(status="FINALIZED")),
        abandon_prepared=AsyncMock(),
    )
    return runtime


def _target():
    return VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="folder",
        resource_id="57268",
        resource_version=1,
        context_version="delete-snapshot",
        parent_type="knowledge_space",
        parent_id="128",
    )


@pytest.mark.parametrize("status", ["FINALIZED", "COMMITTED", "STAGING", "COMMIT_UNKNOWN"])
async def test_delete_retry_resumes_original_plan_without_current_version_check(status):
    runtime = _runtime(status, version=2)
    await runtime.project_delete(actor=PermissionActor(user_id=5, current_tenant_id=7), target=_target())
    runtime._state.mode_for_target.assert_not_awaited()
    runtime._state.mark_projecting.assert_not_awaited()
    plan = runtime._projection.prepare.await_args.args[0]
    runtime._projection.execute.assert_awaited_once_with(plan)
    assert plan.expected_version == 1
    assert plan.target_version == 2
    assert plan.operation_type == "RESOURCE_DELETE"


@pytest.mark.parametrize("state", ["CURRENT", "PROJECTING"])
async def test_prepared_delete_can_reclaim_its_own_reservation(state):
    runtime = _runtime("PREPARED", state=state)
    await runtime.project_delete(actor=PermissionActor(user_id=5, current_tenant_id=7), target=_target())
    runtime._state.mark_projecting.assert_awaited_once()
    runtime._projection.execute.assert_awaited_once()


@pytest.mark.parametrize(
    "state,version,operation_id", [("CURRENT", 2, 9), ("PROJECTING", 1, 10), ("FAILED_CLOSED", 1, 9)]
)
async def test_new_delete_cannot_overwrite_a_changed_or_foreign_reservation(state, version, operation_id):
    runtime = _runtime("PREPARED", state=state, version=version, operation_id=operation_id)
    with pytest.raises(PermissionPublishNotReadyError):
        await runtime.project_delete(actor=PermissionActor(user_id=5, current_tenant_id=7), target=_target())
    runtime._projection.execute.assert_not_awaited()
    runtime._projection.abandon_prepared.assert_awaited_once()
