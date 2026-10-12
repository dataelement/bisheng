"""Creation rollback preserves the projection ledger and removes live state."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionVersionConflictError
from bisheng.permission.application import runtime as module
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import build_projection_operation, projection_request_checksum
from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan


@pytest.fixture
def rollback(monkeypatch):
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_file",
        resource_id="348",
        resource_version=0,
        parent_type="knowledge_space",
        parent_id="348",
        context_version="created:knowledge_file:348",
    )
    original = build_create_plan(
        target,
        store_id="store",
        model_id="model",
        operator_id=9,
        idempotency_key=module._idempotency_key("create", 7, "knowledge_file", "348", 9),
        protected_deltas=(
            module.ProjectionTupleDelta(
                phase="STAGE",
                sequence=0,
                action="WRITE",
                user="user:9",
                relation="assignee",
                object="permission_grant:17",
            ),
        ),
        permission_mode="INHERIT",
    )
    creation, tuples = build_projection_operation(original, request_checksum=projection_request_checksum(original))
    creation.id = 1
    creation.status = "FINALIZED"
    repository = SimpleNamespace(
        aget_operation_by_idempotency=AsyncMock(return_value=creation),
        aget_operation_tuples=AsyncMock(return_value=tuples),
        purge=AsyncMock(),
    )
    monkeypatch.setattr(module, "CreationRollbackRepository", lambda: repository)
    runtime = object.__new__(module.F048PermissionRuntime)
    runtime._runtime_catalog = AsyncMock(return_value=SimpleNamespace(release_id=1, store_id="store", model_id="model"))
    mode = SimpleNamespace(
        version=1, parent_type="knowledge_space", parent_id="348", operation_id=1, projection_state="CURRENT"
    )
    runtime._state = SimpleNamespace(mode_for_target=AsyncMock(return_value=mode), mark_projecting=AsyncMock())
    runtime._projection = SimpleNamespace(
        abandon_prepared=AsyncMock(),
        prepare=AsyncMock(return_value=SimpleNamespace(id=2, status="PREPARED")),
        execute=AsyncMock(return_value=SimpleNamespace(operation_id=2)),
    )
    return SimpleNamespace(runtime=runtime, repository=repository, target=target, mode=mode, original=original)


async def _rollback(fixture):
    await fixture.runtime.rollback_created(actor=SimpleNamespace(user_id=9), target=fixture.target, owner_user_id=9)


async def test_rollback_uses_exact_inverse_of_creation_including_grant_tuples(rollback):
    await _rollback(rollback)
    plan = rollback.runtime._projection.execute.await_args.args[0]
    assert plan.operation_type == "RESOURCE_CREATE_ROLLBACK"
    assert {delta.key for delta in plan.deltas} == {delta.key for delta in rollback.original.deltas}
    assert all(delta.action == "DELETE" and delta.phase == "COMMIT" for delta in plan.deltas)
    assert any(delta.object == "permission_grant:17" for delta in plan.deltas)
    assert (plan.expected_version, plan.target_version) == (1, 2)
    rollback.repository.purge.assert_awaited_once_with(rollback.target, 2)


async def test_uninitialized_file_needs_no_permission_state(rollback):
    rollback.repository.aget_operation_by_idempotency.return_value = None
    await _rollback(rollback)
    rollback.runtime._projection.execute.assert_not_awaited()
    rollback.repository.purge.assert_not_awaited()


async def test_projection_failure_does_not_purge_permission_mirrors(rollback):
    rollback.runtime._projection.execute.side_effect = [None, RuntimeError("transport failure")]
    with pytest.raises(RuntimeError, match="transport failure"):
        await _rollback(rollback)
    rollback.repository.purge.assert_not_awaited()


async def test_changed_resource_is_not_rolled_back(rollback):
    rollback.mode.version = 2
    with pytest.raises(PermissionVersionConflictError):
        await _rollback(rollback)
    assert rollback.runtime._projection.execute.await_count == 1
    rollback.repository.purge.assert_not_awaited()
    rollback.runtime._projection.abandon_prepared.assert_awaited_once()


async def test_reserved_rollback_can_resume(rollback):
    rollback.mode.operation_id = 2
    rollback.mode.projection_state = "PROJECTING"
    await _rollback(rollback)
    rollback.repository.purge.assert_awaited_once()


async def test_finalized_rollback_can_repeat_sql_cleanup(rollback):
    rollback.runtime._projection.prepare.return_value.status = "FINALIZED"
    await _rollback(rollback)
    rollback.runtime._state.mode_for_target.assert_not_awaited()
    rollback.runtime._state.mark_projecting.assert_not_awaited()
    rollback.repository.purge.assert_awaited_once()


async def test_inverse_projection_removes_all_created_tuples_and_is_idempotent(rollback):
    from bisheng.permission.domain.services.projection_service import ProjectionService
    from test.permission.test_f048_projection_service import (
        FakeFGAProjection,
        FakeProjectionRepository,
        FakeRecentMarker,
        FakeScopeGuard,
    )

    await _rollback(rollback)
    plan = rollback.runtime._projection.execute.await_args.args[0]
    unrelated = ("user:9", "owner", "knowledge_space:348")
    fga = FakeFGAProjection({delta.key for delta in rollback.original.deltas} | {unrelated})
    projection = ProjectionService(
        repository=FakeProjectionRepository(),
        marker=FakeRecentMarker(),
        scope_guard=FakeScopeGuard(),
        fga=fga,
    )
    assert (await projection.execute(plan)).status == "FINALIZED"
    assert fga.present == {unrelated}
    assert (await projection.execute(plan)).idempotent
    assert fga.present == {unrelated}


async def test_catalog_change_blocks_replaying_creation(rollback):
    rollback.runtime._runtime_catalog.return_value.model_id = "different-model"
    with pytest.raises(module.PermissionPublishNotReadyError):
        await _rollback(rollback)
    rollback.runtime._projection.execute.assert_not_awaited()
    rollback.repository.purge.assert_not_awaited()
