"""覆盖 AC: AC-35、AC-43、AC-48、AC-49、AC-52. Real destroy creation and SQL rollback.

No already-admitted deployment is retyped as destroy. Cluster I/O and filesystem
purging are deliberately absent: rejected admission must leave no executable work.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation, RuntimeNode, RuntimeOperation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo


@pytest.fixture
async def control(repo):
    node = await repo.get(RuntimeNode, "node-a")
    node.heartbeat_at = datetime.utcnow()
    await repo.save(node)

    async def load(app_id):
        return SimpleNamespace(id=app_id, tenant_id=1, state="stopped")

    return RuntimeOperationService(repo, app_loader=load), repo


def request(*, kind="destroy", payload=None, key="owner-delete", app="app-a"):
    return OperationInput(
        app_id=app,
        node_id="node-a",
        generation=1,
        owner_epoch=1,
        kind=kind,
        idempotency_key=key,
        payload={"purge_volume": True} if payload is None else payload,
    )


async def test_real_destroy_create_preallocates_only_trusted_helper_budget(control):
    """AC-35, AC-43: actual owner destroy has a bounded helper budget before any Pod intent."""
    service, repository = control
    document = await service.create(
        request(payload={"purge_volume": True, "tier": {"memory_mb": 999999, "cpu_millicores": 999999}})
    )
    reservations = await repository.find(RuntimeCapacityReservation, operation_id=document["operation_id"])
    assert len(reservations) == 1
    assert (reservations[0].purpose, reservations[0].memory_mb, reservations[0].cpu_millicores) == ("destroy", 128, 25)
    assert reservations[0].state == "held" and document["stage"] == "admitted"


@pytest.mark.parametrize(
    "executor,kind,payload",
    [
        ("docker", "destroy", {"purge_volume": True}),
        ("docker", "stop", {"purge_volume": True}),
        ("kubernetes", "destroy", {}),
        ("kubernetes", "destroy", {"purge_volume": False}),
        ("kubernetes", "destroy", {"purge_volume": "true"}),
        ("kubernetes", "destroy", {"purge_volume": 1}),
        ("kubernetes", "stop", {"purge_volume": True}),
    ],
)
async def test_plain_stop_destroy_and_docker_keep_their_existing_budget_contract(control, executor, kind, payload):
    """AC-35, AC-56: only an explicit K8s data purge creates a new maintenance workload."""
    service, repository = control
    node = await repository.get(RuntimeNode, "node-a")
    node.executor_kind = executor
    await repository.save(node)
    document = await service.create(request(kind=kind, payload=payload))
    assert await repository.find(RuntimeCapacityReservation, operation_id=document["operation_id"]) == []


@pytest.mark.parametrize("field,budget", [("memory_budget_mb", 127), ("cpu_budget_millicores", 24)])
async def test_purge_capacity_refusal_rolls_back_intent_and_retry_after_capacity_returns(control, field, budget):
    """AC-35, AC-43, AC-52: failed admission leaves no destroy intent or reservation to execute."""
    service, repository = control
    node = await repository.get(RuntimeNode, "node-a")
    generation = node.generation
    setattr(node, field, budget)
    await repository.save(node)
    with pytest.raises(RuntimeConflict, match="capacity_exhausted"):
        await service.create(request())
    assert await repository.find(RuntimeOperation, idempotency_key="owner-delete") == []
    assert await repository.find(RuntimeCapacityReservation) == []
    assert (await repository.get(RuntimeNode, "node-a")).generation == generation
    node = await repository.get(RuntimeNode, "node-a")
    setattr(node, field, 4096)
    await repository.save(node)
    accepted = await service.create(request())
    assert len(await repository.find(RuntimeCapacityReservation, operation_id=accepted["operation_id"])) == 1


async def test_repeated_create_reuses_same_destroy_and_capacity_once(control):
    """AC-48: a lost create response does not reserve twice or create a second purge."""
    service, repository = control
    first = await service.create(request())
    second = await service.create(request())
    assert first["operation_id"] == second["operation_id"]
    reservations = await repository.find(RuntimeCapacityReservation)
    assert len(reservations) == 1 and reservations[0].memory_mb == 128


async def test_outer_transaction_rollback_removes_destroy_and_budget_together(control):
    """AC-48, AC-52: caller rollback cannot leave a committed, executable purge intent."""
    service, repository = control
    with pytest.raises(RuntimeError, match="caller rollback"):
        async with repository.transaction():
            await service.create(request())
            raise RuntimeError("caller rollback")
    assert await repository.find(RuntimeOperation, idempotency_key="owner-delete") == []
    assert await repository.find(RuntimeCapacityReservation) == []


async def test_unknown_other_writer_budget_is_never_borrowed_by_destroy(control):
    """AC-43, AC-49: unknown previous execution still occupies capacity; deletion cannot borrow it."""
    service, repository = control
    previous = await service.create(
        request(
            kind="prepare",
            app="app-b",
            key="other-prepare",
            payload={"tier": {"memory_mb": 4096, "cpu_millicores": 100}},
        )
    )
    old = await repository.get(RuntimeOperation, previous["operation_id"])
    old.status, old.cleanup_status = "failed", "unknown"
    await repository.save(old)
    with pytest.raises(RuntimeConflict, match="execution_not_confirmed_stopped"):
        await repository.release(old.id, stopped=False)
    with pytest.raises(RuntimeConflict, match="capacity_exhausted"):
        await service.create(request())
    assert await repository.find(RuntimeOperation, idempotency_key="owner-delete") == []
    reservation = (await repository.find(RuntimeCapacityReservation, operation_id=old.id))[0]
    assert reservation.state == "held" and reservation.memory_mb == 4096
