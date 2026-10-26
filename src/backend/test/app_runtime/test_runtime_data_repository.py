"""覆盖 AC: AC-04、AC-05、AC-18、AC-33、AC-34、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52、AC-55."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeCapacityReservation,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


@pytest.fixture
async def owned(runtime_repo):
    node = await runtime_repo.get(RuntimeNode, "node-a")
    node.executor_kind = "kubernetes"
    await runtime_repo.save(node)
    serving = operation("serving")
    serving.generation = 3
    serving.status, serving.stage, serving.cleanup_status = "completed", "completed", "complete"
    await runtime_repo.save(serving)
    assignment = await runtime_repo.save(
        RuntimeAssignment(
            tenant_id=1, app_id="app-a", node_id="node-a", generation=3, owner_epoch=1, active_operation_id=serving.id
        )
    )
    return runtime_repo, assignment, serving


def data_operation(key="data-a"):
    op = operation(key)
    op.kind, op.generation = "data", 3
    op.deadline = datetime.utcnow() + timedelta(seconds=60)
    op.payload = {"request_id": key, "action": "tables", "parameters_digest": "a" * 64}
    return op


async def test_data_session_keeps_serving_owner_and_generation_unchanged(owned):
    repo, assignment, serving = owned
    data = await repo.acquire_data_operation(data_operation())
    stored = await repo.get(RuntimeAssignment, assignment.id)
    assert (stored.active_operation_id, stored.generation, stored.owner_epoch) == (serving.id, 3, 1)
    assert stored.data_operation_id == data.id
    assert (await repo.acquire_data_operation(data_operation())).id == data.id
    await repo.claim(data.id, node_id="node-a", generation=3, owner_epoch=1)
    assert (await repo.get(RuntimeAssignment, assignment.id)).generation == 3
    reservation = (await repo.find(RuntimeCapacityReservation, operation_id=data.id))[0]
    assert reservation.memory_mb == 128 and reservation.cpu_millicores == 100


@pytest.mark.parametrize("available_cpu,accepted", [(99, False), (100, True)])
async def test_offline_data_reserves_actual_cpu_capacity_atomically(owned, available_cpu, accepted):
    """覆盖 AC: AC-18、AC-33、AC-43、AC-48、AC-49、AC-55."""
    repo, assignment, serving = owned
    node = await repo.get(RuntimeNode, "node-a")
    node.cpu_budget_millicores, node.memory_budget_mb = available_cpu, 128
    await repo.save(node)
    op = data_operation()
    if accepted:
        await repo.acquire_data_operation(op)
        reservation = (await repo.find(RuntimeCapacityReservation, operation_id=op.id))[0]
        assert (reservation.memory_mb, reservation.cpu_millicores, reservation.state) == (128, 100, "held")
        assert (await repo.get(RuntimeAssignment, assignment.id)).data_operation_id == op.id
    else:
        with pytest.raises(RuntimeConflict, match=r"^capacity_exhausted$"):
            await repo.acquire_data_operation(op)
        assert await repo.get(RuntimeOperation, op.id) is None
        assert not await repo.find(RuntimeCapacityReservation, operation_id=op.id)
        assert (await repo.get(RuntimeAssignment, assignment.id)).data_operation_id == ""
    owner = await repo.get(RuntimeAssignment, assignment.id)
    assert (owner.active_operation_id, owner.generation, owner.owner_epoch) == (serving.id, 3, 1)


async def test_online_data_adds_no_reservation_even_when_unreserved_capacity_is_empty(owned):
    """覆盖 AC: AC-18、AC-33、AC-43、AC-48、AC-49、AC-55."""
    repo, assignment, serving = owned
    node = await repo.get(RuntimeNode, "node-a")
    node.cpu_budget_millicores = node.memory_budget_mb = 0
    await repo.save(node)
    data = await repo.acquire_data_operation(data_operation(), offline=False)
    assert not await repo.find(RuntimeCapacityReservation, operation_id=data.id)
    owner = await repo.get(RuntimeAssignment, assignment.id)
    assert (owner.active_operation_id, owner.generation, owner.owner_epoch, owner.data_operation_id) == (
        serving.id,
        3,
        1,
        data.id,
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("kind", "deploy", "data_operation_deadline_invalid"),
        ("deadline", -1, "data_operation_deadline_invalid"),
        ("deadline", 61, "data_operation_deadline_invalid"),
        ("generation", 4, "data_owner_fence_stale"),
        ("owner_epoch", 2, "data_owner_fence_stale"),
    ],
)
async def test_data_cpu_adjustment_preserves_operation_and_owner_fences(owned, field, value, reason):
    """覆盖 AC: AC-33、AC-43、AC-48、AC-49、AC-55."""
    repo, assignment, _ = owned
    op = data_operation()
    setattr(op, field, datetime.utcnow() + timedelta(seconds=value) if field == "deadline" else value)
    with pytest.raises(RuntimeConflict, match="^" + reason + "$"):
        await repo.acquire_data_operation(op)
    assert await repo.get(RuntimeOperation, op.id) is None
    assert not await repo.find(RuntimeCapacityReservation, operation_id=op.id)
    assert (await repo.get(RuntimeAssignment, assignment.id)).data_operation_id == ""


@pytest.mark.parametrize("kind", ["deploy", "stop", "destroy", "migrate", "restore"])
async def test_data_session_blocks_new_lifecycle_submissions(owned, kind):
    repo, _, _ = owned
    await repo.acquire_data_operation(data_operation())
    lifecycle = operation("lifecycle")
    lifecycle.kind, lifecycle.generation = kind, 4
    with pytest.raises(RuntimeConflict, match="data"):
        await repo.create_operation(lifecycle)


async def test_pending_lifecycle_submission_blocks_a_new_data_session(owned):
    repo, _, _ = owned
    await repo.create_operation(operation("pending-deploy"))
    with pytest.raises(RuntimeConflict, match="operation"):
        await repo.acquire_data_operation(data_operation())


async def test_lifecycle_claim_cannot_overtake_an_unfinished_data_session(owned):
    repo, assignment, _ = owned
    lifecycle = operation("claiming")
    lifecycle.generation = 4
    # Simulate an operation committed before the data lock was established.
    await repo.save(lifecycle)
    data = data_operation()
    await repo.save(data)
    assignment.data_operation_id = data.id
    await repo.save(assignment)
    with pytest.raises(RuntimeConflict, match="data"):
        await repo.claim(lifecycle.id, node_id="node-a", generation=4, owner_epoch=1)


async def test_unknown_or_expired_data_session_holds_exclusivity_until_cleanup(owned):
    repo, assignment, _ = owned
    data = await repo.acquire_data_operation(data_operation())
    data.status, data.deadline = "timed_out", datetime.utcnow() - timedelta(seconds=1)
    await repo.save(data)
    with pytest.raises(RuntimeConflict):
        await repo.acquire_data_operation(data_operation("new-data"))
    with pytest.raises(RuntimeConflict):
        await repo.release(data.id, stopped=True)
    assert (await repo.get(RuntimeAssignment, assignment.id)).data_operation_id == data.id
    data.cleanup_status = "complete"
    await repo.save(data)
    await repo.release(data.id, stopped=True)
    assert (await repo.get(RuntimeAssignment, assignment.id)).data_operation_id == ""
    assert (await repo.acquire_data_operation(data_operation("new-data"))).id != data.id


async def test_data_claim_rejects_changed_serving_generation(owned):
    repo, assignment, _ = owned
    data = await repo.acquire_data_operation(data_operation())
    assignment.generation = 4
    await repo.save(assignment)
    with pytest.raises(RuntimeConflict, match="fence"):
        await repo.claim(data.id, node_id="node-a", generation=3, owner_epoch=1)


@pytest.mark.parametrize("kind,extra", [("deploy", 128), ("restore", 128), ("probe", 0), ("prepare", 0)])
async def test_kubernetes_reservations_include_the_actual_data_sidecar(runtime_repo, kind, extra):
    from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    node = await runtime_repo.get(RuntimeNode, "node-a")
    node.executor_kind = "kubernetes"
    await runtime_repo.save(node)

    async def app_loader(app_id):
        return SimpleNamespace(id=app_id, tenant_id=1, state="draft")

    svc = RuntimeOperationService(runtime_repo, app_loader=app_loader)
    result = await svc.create(
        OperationInput(
            idempotency_key="overhead",
            app_id="app-a",
            kind=kind,
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            payload={"tier": {"memory_mb": 512, "cpu_millicores": 250}},
        )
    )
    reserved = (await runtime_repo.find(RuntimeCapacityReservation, operation_id=result["operation_id"]))[0]
    assert reserved.memory_mb == 512 + extra
    assert reserved.cpu_millicores == 250 + (25 if extra else 0)


async def test_data_concurrency_limit_is_global_across_tenants(owned):
    from bisheng.core.context.tenant import current_tenant_id

    repo, _, _ = owned
    await repo.acquire_data_operation(data_operation())
    for app_id, tenant in (("app-b", 1), ("app-c", 2)):
        token = current_tenant_id.set(tenant)
        try:
            serving = operation("serve-" + app_id, app=app_id)
            serving.tenant_id, serving.scope_key = tenant, f"{tenant}/{app_id}"
            serving.status, serving.cleanup_status, serving.generation = "completed", "complete", 3
            await repo.save(serving)
            await repo.save(
                RuntimeAssignment(
                    tenant_id=tenant,
                    app_id=app_id,
                    node_id="node-a",
                    generation=3,
                    owner_epoch=1,
                    active_operation_id=serving.id,
                )
            )
            data = data_operation("data-" + app_id)
            data.app_id, data.tenant_id, data.scope_key = app_id, tenant, f"{tenant}/{app_id}"
            if tenant == 1:
                await repo.acquire_data_operation(data)
            else:
                with pytest.raises(RuntimeConflict, match="capacity"):
                    await repo.acquire_data_operation(data)
        finally:
            current_tenant_id.reset(token)
