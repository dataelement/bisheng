"""AC-03/04/05/06/08: department-only, bounded original intent recovery."""

import pytest

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.permission.domain.services.projection_plan import ProjectionPlan, ProjectionTupleDelta
from bisheng.permission.domain.services.projection_service import ProjectionService
from test.permission.test_f048_projection_service import (
    FakeFGAProjection,
    FakeProjectionRepository,
    FakeRecentMarker,
    FakeScopeGuard,
)


def plan():
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key="dept-11",
        operation_type="DEPARTMENT_CREATE",
        scope_type="department",
        scope_key="11",
        expected_version=0,
        target_version=1,
        store_id="s",
        model_id="m",
        operator_id=0,
        change_item_count=1,
        deltas=(
            ProjectionTupleDelta(
                phase="COMMIT",
                sequence=0,
                action="WRITE",
                user="department:1",
                relation="parent",
                object="department:11",
            ),
        ),
    )


async def service():
    repo = FakeProjectionRepository()
    fga = FakeFGAProjection(set())
    svc = ProjectionService(repository=repo, fga=fga, marker=FakeRecentMarker(), scope_guard=FakeScopeGuard())
    await svc.prepare(plan())
    return svc, repo, fga


async def test_original_failed_mixed_can_forward_only_under_owner_proof():
    svc, repo, fga = await service()
    repo.operation.status = "FAILED_CLOSED"
    outcome = await svc.recover_department_operation(1, verify_owner=lambda p, o: verify(p, o))
    assert outcome.target_version == 1
    assert repo.operation.status == "FINALIZED"
    assert len(fga.calls) == 1


async def verify(p, operation):
    assert p.scope_key == "11" and operation.id == 1


async def test_committed_missing_after_never_rewrites():
    svc, repo, fga = await service()
    repo.operation.status = "COMMITTED"
    with pytest.raises(PermissionPublishNotReadyError):
        await svc.recover_department_operation(1, verify_owner=verify)
    assert not fga.calls


@pytest.mark.parametrize(
    "entry", ["reconcile_operation", "inspect_failed_closed_recovery", "recover_failed_closed_operation"]
)
async def test_maintenance_type_rejected_before_empty_tuple_or_finalized_fast_path(entry):
    svc, repo, _ = await service()
    repo.operation.operation_type = "DEPARTMENT_RECONCILE"
    repo.operation.status = "FINALIZED"
    repo.tuples = []
    with pytest.raises(PermissionPublishNotReadyError) as error:
        kwargs = {"confirmation_checksum": "x"} if entry.startswith("recover_") else {}
        await getattr(svc, entry)(1, **kwargs)
    assert "dedicated" in str(error.value).lower()
