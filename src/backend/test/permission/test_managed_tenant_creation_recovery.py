"""Fixed-key creation recovery resumes its durable plan and completes owner mirrors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.permission.application.runtime import F048PermissionRuntime, _idempotency_key
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.permission.domain.services.projection_plan import build_projection_operation, projection_request_checksum
from bisheng.permission.domain.services.resource_lifecycle_policy import build_create_plan
from test.permission.test_f048_projection_sql_runtime import session_factory as session_factory
from test.permission.test_f048_projection_sql_runtime import tenant_context as tenant_context


@pytest.fixture
def recovery(monkeypatch):
    from bisheng.permission.domain.repositories import creation_recovery_repository

    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=2, resource_type="tool", resource_id="9", resource_version=0, context_version="ctx"
    )
    plan = build_create_plan(
        target,
        store_id="store",
        model_id="model",
        operator_id=7,
        idempotency_key=_idempotency_key("create", 2, "tool", "9", 7),
        protected_deltas=(),
        permission_mode="CUSTOM",
    )
    operation, tuples = build_projection_operation(plan, request_checksum=projection_request_checksum(plan))
    operation.id = 30
    operation.status = "COMMIT_UNKNOWN"
    repository = SimpleNamespace(
        aget_operation_by_idempotency=AsyncMock(return_value=operation),
        aget_operation_tuples=AsyncMock(return_value=tuples),
        finalize_creation=AsyncMock(),
    )
    monkeypatch.setattr(creation_recovery_repository, "CreationRecoveryRepository", lambda: repository)
    projection = SimpleNamespace(
        reconcile_operation=AsyncMock(return_value=SimpleNamespace(operation_id=30, status="FINALIZED"))
    )
    runtime = F048PermissionRuntime(
        client=object(),
        state=object(),
        marker=object(),
        decision=object(),
        projection=projection,
        sources=object(),
        owner=object(),
        grants=object(),
        modes=object(),
        explain=object(),
    )
    runtime._runtime_catalog = AsyncMock(return_value=SimpleNamespace(store_id="store", model_id="model"))
    runtime.authorize_created = AsyncMock()
    return runtime, repository, projection, operation, target


async def test_unknown_commit_resumes_exact_operation_and_owner_finalize(recovery):
    runtime, repo, projection, _op, target = recovery
    await runtime.resume_created(actor=PermissionActor(user_id=7, tenant_id=2), target=target, owner_user_id=7)
    projection.reconcile_operation.assert_awaited_once_with(30)
    repo.finalize_creation.assert_awaited_once_with(target, 30, 7)
    runtime.authorize_created.assert_not_awaited()


async def test_failed_closed_uses_original_fenced_recovery_without_generating_new_key(recovery):
    runtime, repo, projection, op, target = recovery
    op.status = "FAILED_CLOSED"
    projection.inspect_failed_closed_recovery = AsyncMock(
        return_value=SimpleNamespace(confirmation_checksum="frozen-confirmation")
    )
    projection.recover_failed_closed_operation = AsyncMock(return_value="outcome")
    assert (
        await runtime.resume_created(actor=PermissionActor(user_id=7, tenant_id=2), target=target, owner_user_id=7)
        == "outcome"
    )
    projection.inspect_failed_closed_recovery.assert_awaited_once_with(op.id)
    projection.recover_failed_closed_operation.assert_awaited_once_with(
        op.id, confirmation_checksum="frozen-confirmation"
    )
    projection.reconcile_operation.assert_not_awaited()
    repo.finalize_creation.assert_awaited_once_with(target, op.id, 7)
    runtime.authorize_created.assert_not_awaited()


async def test_actor_or_catalog_drift_is_rejected(recovery):
    runtime, _repo, projection, _op, target = recovery
    with pytest.raises(PermissionInvalidResourceError):
        await runtime.resume_created(actor=PermissionActor(user_id=8, tenant_id=2), target=target, owner_user_id=7)
    runtime._runtime_catalog.return_value = SimpleNamespace(store_id="other", model_id="model")
    with pytest.raises(PermissionInvalidResourceError):
        await runtime.resume_created(actor=PermissionActor(user_id=7, tenant_id=2), target=target, owner_user_id=7)
    projection.reconcile_operation.assert_not_awaited()


async def test_prepared_without_owner_sql_reuses_original_key(recovery):
    runtime, repo, projection, op, target = recovery
    op.status = "PREPARED"
    repo.has_prepared_owner = AsyncMock(return_value=False)
    await runtime.resume_created(actor=PermissionActor(user_id=7, tenant_id=2), target=target, owner_user_id=7)
    assert runtime.authorize_created.await_args.kwargs["idempotency_key"] == op.idempotency_key
    projection.reconcile_operation.assert_not_awaited()


@pytest.fixture
def creation_sql_store(session_factory):
    return session_factory


async def test_sql_owner_finalize_requires_original_finalized_fence(creation_sql_store, tenant_context):
    from sqlmodel import select

    from bisheng.common.errcode.permission import PermissionVersionConflictError
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.permission.domain.models import (
        PermissionGrant,
        PermissionGrantAssignee,
        PermissionProjectionOperation,
        PermissionVisibleSourceProjection,
        ResourcePermissionMode,
    )
    from bisheng.permission.domain.repositories.creation_recovery_repository import CreationRecoveryRepository
    from test.permission.test_f048_projection_sql_runtime import _seed_projecting_state

    op_id = await _seed_projecting_state(creation_sql_store)
    with bypass_tenant_filter():
        async with creation_sql_store() as session, session.begin():
            op = await session.get(PermissionProjectionOperation, op_id)
            op.operation_type = "RESOURCE_CREATE"
            op.scope_key = "tool:9"
            op.target_version = 1
            for model in (PermissionGrant, ResourcePermissionMode, PermissionVisibleSourceProjection):
                for row in (await session.execute(select(model))).scalars().all():
                    row.resource_type, row.resource_id = "tool", "9"
            mode = (await session.execute(select(ResourcePermissionMode))).scalars().one()
            mode.version, mode.projection_state = 1, "CURRENT"
            grant = (await session.execute(select(PermissionGrant))).scalars().one()
            grant.model_key = "owner"
            owner = await session.get(PermissionGrantAssignee, 101)
            owner.source_type, owner.subject_id = "CREATOR", "7"
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7, resource_type="tool", resource_id="9", resource_version=0, context_version="ctx"
    )
    repo = CreationRecoveryRepository(creation_sql_store)
    with pytest.raises(PermissionVersionConflictError):
        await repo.finalize_creation(target, op_id, 7)
    with bypass_tenant_filter():
        async with creation_sql_store() as session, session.begin():
            (await session.get(PermissionProjectionOperation, op_id)).status = "FINALIZED"
    await repo.finalize_creation(target, op_id, 7)
    await repo.finalize_creation(target, op_id, 7)
    with bypass_tenant_filter():
        async with creation_sql_store() as session:
            grant = (await session.execute(select(PermissionGrant))).scalars().one()
            assert (grant.state, grant.projection_state) == ("ACTIVE", "CURRENT")
            assert (await session.get(PermissionGrantAssignee, 101)).state == "ACTIVE"
            assert (await session.get(PermissionGrantAssignee, 102)).state == "PENDING_DELETE"
