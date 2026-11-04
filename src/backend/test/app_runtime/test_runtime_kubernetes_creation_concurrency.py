"""覆盖 AC: AC-13、AC-14、AC-48、AC-49、AC-52.

These deterministic two-Session interleavings test SQLAlchemy identity-map
refresh, not MySQL/DM8 row-lock scheduling. The reader commits its preload
before the independent writer commits, retaining only the cached ORM object.
"""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.repositories.runtime_kubernetes_repository import RuntimeKubernetesRepository
from bisheng.app_runtime.domain.services.runtime_kubernetes_service import RuntimeKubernetesService
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import ADMISSION, MANAGER, REF, register, short_hash
from test.app_runtime.test_runtime_kubernetes_service import control as control


async def observe(service, action, **detail):
    return await service.observe_resource(
        MANAGER, REF, {"action": action, "holder_id": "controller-a", "controller_epoch": 1, **detail}
    )


def absence():
    return {
        "evidence_kind": "not_created",
        "namespace": "namespace-a",
        "name": "app-" + short_hash("app-a"),
        "observed_at": NOW.isoformat() + "Z",
        "api_status": 404,
    }


def independent_service(repository):
    sessions = []

    @asynccontextmanager
    async def factory():
        async with repository._factory() as session:
            sessions.append(session)
            yield session

    return RuntimeKubernetesService(RuntimeKubernetesRepository(factory), clock=lambda: NOW), sessions


async def test_committed_begin_refreshes_cached_unattempted_before_fence(control):
    service, repository, operation = control
    await register(control)
    other, sessions = independent_service(repository)
    async with repository.transaction() as reader:
        cached = await repository.get(RuntimeExecutionResource, REF)
        assert cached.observed_state["creation"]["state"] == "unattempted"
        # End the SQLite read snapshot while keeping this Session's identity map.
        await reader.commit()
        await observe(other, "create_begin", create_attempt_id=str(uuid4()))
        assert sessions and all(session is not reader for session in sessions)
        assert cached.observed_state["creation"]["state"] == "unattempted"
        with pytest.raises(RuntimeConflict, match="resource_creation_unconfirmed"):
            await observe(service, "create_fence")
        assert cached.observed_state["creation"]["state"] == "started"
        assert cached.stop_requested_at is None and cached.stop_state == "held"
    assert (await repository.find(RuntimeCapacityReservation, operation_id=operation.id))[0].state == "held"


async def test_committed_fence_refreshes_cached_unattempted_before_begin(control):
    service, repository, _ = control
    await register(control)
    other, sessions = independent_service(repository)
    async with repository.transaction() as reader:
        cached = await repository.get(RuntimeExecutionResource, REF)
        await reader.commit()
        await observe(other, "create_fence")
        assert sessions and all(session is not reader for session in sessions)
        assert cached.stop_requested_at is None
        with pytest.raises(RuntimeConflict, match="resource_creation_already_attempted"):
            await observe(service, "create_begin", create_attempt_id=str(uuid4()))
        assert cached.observed_state["creation"]["state"] == "fenced"
        assert cached.stop_requested_at is not None
    assert (await service.admission_plan(ADMISSION, REF))["allow_create"] is False


async def test_committed_uid_binding_refreshes_cached_absence_before_404_proof(control):
    service, repository, operation = control
    await register(control)
    await observe(service, "create_fence")
    other, sessions = independent_service(repository)
    async with repository.transaction() as reader:
        cached = await repository.get(RuntimeExecutionResource, REF)
        assert cached.uid is None
        await reader.commit()
        await observe(other, "bind", uid=UID, node_name="worker-a")
        assert sessions and all(session is not reader for session in sessions)
        assert cached.uid is None
        with pytest.raises(RuntimeConflict, match="resource_creation_unconfirmed"):
            await observe(service, "not_created", evidence=absence())
        assert cached.uid == UID and cached.stop_state != "confirmed"
    assert (await repository.find(RuntimeCapacityReservation, operation_id=operation.id))[0].state == "held"


async def test_committed_absence_refreshes_cached_fence_before_late_uid_bind(control):
    service, repository, _ = control
    await register(control)
    await observe(service, "create_fence")
    other, sessions = independent_service(repository)
    async with repository.transaction() as reader:
        cached = await repository.get(RuntimeExecutionResource, REF)
        assert cached.stop_state == "requested"
        await reader.commit()
        await observe(other, "not_created", evidence=absence())
        assert sessions and all(session is not reader for session in sessions)
        assert cached.stop_state == "requested"
        with pytest.raises(RuntimeConflict, match="resource_creation_fenced"):
            await observe(service, "bind", uid=UID, node_name="worker-a")
        assert cached.uid is None and cached.stop_state == "confirmed"
        assert cached.stop_evidence["evidence_kind"] == "not_created"
