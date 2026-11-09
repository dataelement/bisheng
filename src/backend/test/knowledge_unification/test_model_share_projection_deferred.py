"""Unbound model journals stay PREPARED; other scopes keep failure semantics."""

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.domain.models import ProjectionOperationStatus
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services import projection_service as module
from bisheng.permission.domain.services.projection_service import (
    ProjectionPlan,
    ProjectionService,
    ProjectionTupleDelta,
)
from test.permission import test_f048_projection_sql_runtime as native

tenant_context = native.tenant_context
session_factory = native.session_factory


class Marker:
    async def is_ready(self):
        return True

    async def arm(self, plan):
        return None


class Scope:
    def __init__(self, deferred):
        self.deferred, self.bound, self.failed = deferred, False, False

    async def reserve(self, plan, operation_id):
        if not self.bound:
            kind = getattr(module, "ProjectionScopeDeferred", PermissionPublishNotReadyError)
            raise (kind if self.deferred else PermissionPublishNotReadyError)(msg="not yet business-bound")

    async def fail_closed(self, plan, reason):
        self.failed = True

    async def is_expected_version(self, plan, operation_id):
        return self.bound

    async def finalize(self, plan, operation_id):
        assert self.bound


class Transport:
    def __init__(self):
        self.present = {("tenant:101", "shared_with", "llm_server:1")}
        self.writes = 0

    async def write_atomic(self, *, writes, deletes):
        self.writes += 1
        for delta in writes:
            self.present.add(delta.key)
        for delta in deletes:
            self.present.discard(delta.key)
        return "f" * 64

    async def read_present(self, deltas, *, consistency):
        return frozenset(delta.key for delta in deltas if delta.key in self.present)


def plan():
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key="model-share-deferred-native",
        operation_type="model_delete_sharing",
        scope_type="llm_model_deletion",
        scope_key="llm_server:1",
        expected_version=1,
        target_version=2,
        store_id="store",
        model_id="model",
        operator_id=9,
        change_item_count=1,
        deltas=(ProjectionTupleDelta("COMMIT", 0, "DELETE", "tenant:101", "shared_with", "llm_server:1"),),
    )


@pytest.mark.parametrize("deferred", [True, False])
async def test_actual_unbound_native_ledger_is_deferred_only_for_explicit_model_scope(session_factory, deferred):
    repository, scope, transport = ProjectionRepository(session_factory), Scope(deferred), Transport()
    service = ProjectionService(
        repository=repository,
        marker=Marker(),
        scope_guard=scope,
        fga=transport,
        finalizer=scope,
    )
    operation = await service.prepare(plan())
    with pytest.raises(PermissionPublishNotReadyError):
        await service.reconcile_operation(operation.id)
    stored = await repository.aget_operation(operation.id)
    assert stored.status == ("PREPARED" if deferred else "FAILED_CLOSED")
    # Original abandon_prepared closes only its journal, not an unbound scope.
    assert scope.failed is False and transport.writes == 0
    if deferred:
        scope.bound = True
        outcome = await service.reconcile_operation(operation.id)
        assert outcome.status == ProjectionOperationStatus.FINALIZED.value and transport.writes == 1
        again = await service.reconcile_operation(operation.id)
        assert again.idempotent and transport.writes == 1
