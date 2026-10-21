"""覆盖 AC: AC-08、AC-13、AC-15、AC-35、AC-48、AC-49、AC-52. Real SQLite transactions, no cluster."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RUNTIME_TABLES,
    RuntimeCapacityReservation,
    RuntimeNode,
    RuntimeOperation,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import KUBERNETES_TABLES, RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.core.context.tenant import current_tenant_id

NOW = datetime(2026, 10, 21, 6, 0)
UID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
async def repo():
    from bisheng.app_runtime.domain.repositories.runtime_kubernetes_repository import RuntimeKubernetesRepository

    token = current_tenant_id.set(1)
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def connect(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    async with engine.begin() as c:
        for model in (*RUNTIME_TABLES, *KUBERNETES_TABLES):
            await c.run_sync(model.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    result = RuntimeKubernetesRepository(sessions)
    await result.save(
        RuntimeNode(
            id="node-a",
            engine_id="cluster-a/namespace-a",
            platform="linux/amd64",
            memory_budget_mb=4096,
            cpu_budget_millicores=4000,
            heartbeat_at=NOW,
            executor_kind="kubernetes",
            capabilities={"status_protection": True, "binding_protection": True, "status_policy_revision": "v1"},
        )
    )
    try:
        yield result
    finally:
        await engine.dispose()
        current_tenant_id.reset(token)


async def setup_operation(repo, key="one", generation=1):
    op = RuntimeOperation(
        tenant_id=1,
        app_id="app-a",
        scope_key="1/app-a",
        idempotency_key=key,
        request_digest="a" * 64,
        kind="deploy",
        node_id="node-a",
        deadline=datetime.utcnow() + timedelta(hours=1),
        generation=generation,
    )
    op = await repo.create_operation(op)
    await repo.claim(op.id, node_id="node-a", generation=generation, owner_epoch=1)
    await repo.save(
        RuntimeCapacityReservation(
            tenant_id=1,
            app_id=op.app_id,
            operation_id=op.id,
            node_id="node-a",
            purpose="deploy",
            memory_mb=512,
            cpu_millicores=250,
        )
    )
    return op


def resource(op, name="app-a", kind="Pod", purpose="serve"):
    return RuntimeExecutionResource(
        tenant_id=1,
        app_id=op.app_id,
        operation_id=op.id,
        node_id="node-a",
        cluster_id="cluster-a",
        namespace="namespace-a",
        name=name,
        kind=kind,
        purpose=purpose,
        generation=op.generation,
        owner_epoch=1,
        controller_epoch=1,
        spec_digest="a" * 64,
        status_policy_revision="v1",
        approved_template={"kind": kind, "metadata": {"name": name}},
    )


async def leased(repo):
    return await repo.claim_controller("node-a", holder_id="controller-a", expected_epoch=0, now=NOW)


async def intent(repo, op, **kwargs):
    return await repo.create_resource_intent(
        resource(op, **kwargs), holder_id="controller-a", controller_epoch=1, now=NOW
    )


async def bind(repo, row, *, node_name="worker-a"):
    return await repo.bind_resource(
        row.id, uid=UID, node_name=node_name, holder_id="controller-a", controller_epoch=1, now=NOW
    )


def evidence(*, node_name="worker-a", kind="kubelet_terminal"):
    return {
        "uid": UID,
        "namespace": "namespace-a",
        "name": "app-a",
        "resource_version": "17",
        "node_name": node_name,
        "evidence_kind": kind,
        "deletion_timestamp": NOW.isoformat() + "Z",
        "policy_revision": "v1",
        "status_digest": "c" * 64,
        "observed_at": (NOW + timedelta(seconds=1)).isoformat() + "Z",
    }


async def test_controller_claim_renew_expiry_and_cas(repo):
    first = await leased(repo)
    assert first.controller_epoch == 1
    again = await repo.claim_controller(
        "node-a", holder_id="controller-a", expected_epoch=1, now=NOW + timedelta(seconds=1)
    )
    assert again.lease_until == first.lease_until
    with pytest.raises(RuntimeConflict, match="lease"):
        await repo.claim_controller(
            "node-a", holder_id="controller-b", expected_epoch=1, now=NOW + timedelta(seconds=1)
        )
    renewed = await repo.renew_controller(
        "node-a", holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=10)
    )
    assert renewed.lease_until == NOW + timedelta(seconds=40)
    with pytest.raises(RuntimeConflict, match="epoch"):
        await repo.claim_controller(
            "node-a", holder_id="controller-b", expected_epoch=0, now=NOW + timedelta(seconds=41)
        )
    second = await repo.claim_controller(
        "node-a", holder_id="controller-b", expected_epoch=1, now=NOW + timedelta(seconds=41)
    )
    assert second.controller_epoch == 2
    with pytest.raises(RuntimeConflict, match="lease"):
        await repo.renew_controller(
            "node-a", holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=42)
        )


async def test_resource_intent_is_idempotent_and_rejects_changed_plan(repo):
    await leased(repo)
    op = await setup_operation(repo)
    a = await intent(repo, op)
    b = await intent(repo, op)
    assert a.id == b.id and a.uid is None
    changed = resource(op)
    changed.spec_digest = "b" * 64
    with pytest.raises(RuntimeConflict, match="intent"):
        await repo.create_resource_intent(changed, holder_id="controller-a", controller_epoch=1, now=NOW)


async def test_uid_binding_is_one_way_and_comes_from_installed_policy(repo):
    await leased(repo)
    op = await setup_operation(repo)
    row = await intent(repo, op)
    row = await bind(repo, row)
    assert row.uid == UID and row.protected_since_creation and row.binding_policy_verified
    assert (await bind(repo, row)).uid == UID
    with pytest.raises(RuntimeConflict, match="uid"):
        await repo.bind_resource(
            row.id, uid="other", node_name="worker-a", holder_id="controller-a", controller_epoch=1, now=NOW
        )


async def test_expired_controller_and_cross_tenant_cannot_mutate(repo):
    await leased(repo)
    op = await setup_operation(repo)
    with pytest.raises(RuntimeConflict, match="lease"):
        await repo.create_resource_intent(
            resource(op), holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=31)
        )
    token = current_tenant_id.set(2)
    try:
        with pytest.raises(RuntimeConflict, match="tenant"):
            await intent(repo, op)
    finally:
        current_tenant_id.reset(token)


async def test_unknown_stop_blocks_second_production_writer_and_capacity_release(repo):
    await leased(repo)
    op = await setup_operation(repo)
    a = await bind(repo, await intent(repo, op))
    with pytest.raises(RuntimeConflict, match="writer"):
        await intent(repo, op, name="second-position")
    with pytest.raises(RuntimeConflict, match="stopped"):
        await repo.release_resources(op.id)
    held = (await repo.find(RuntimeCapacityReservation, operation_id=op.id))[0]
    assert held.state == "held" and (await repo.get(RuntimeExecutionResource, a.id)).stop_state == "held"


@pytest.mark.parametrize(
    "change",
    [
        {"uid": "other"},
        {"policy_revision": "wrong"},
        {"evidence_kind": "unknown"},
        {"node_name": "other"},
        {"resource_version": "0"},
        {"observed_at": "2026-10-21T05:50:00Z"},
    ],
)
async def test_stop_evidence_must_match_recorded_uid_scope_policy_and_request(repo, change):
    await leased(repo)
    op = await setup_operation(repo)
    row = await bind(repo, await intent(repo, op))
    await repo.request_resource_stop(row.id, operation_id=op.id, holder_id="controller-a", controller_epoch=1, now=NOW)
    with pytest.raises(RuntimeConflict, match="stop"):
        await repo.confirm_resource_stop(
            row.id,
            {**evidence(), **change},
            holder_id="controller-a",
            controller_epoch=1,
            now=NOW + timedelta(seconds=2),
        )
    assert (await repo.get(RuntimeExecutionResource, row.id)).stop_state != "confirmed"


async def test_confirmed_stop_then_release_and_terminal_cleanup_plan_retention(repo):
    await leased(repo)
    op = await setup_operation(repo)
    row = await bind(repo, await intent(repo, op))
    with pytest.raises(RuntimeConflict, match="stop"):
        await repo.confirm_resource_stop(
            row.id, evidence(), holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=2)
        )
    await repo.request_resource_stop(row.id, operation_id=op.id, holder_id="controller-a", controller_epoch=1, now=NOW)
    row = await repo.confirm_resource_stop(
        row.id, evidence(), holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=2)
    )
    assert row.stop_state == "confirmed"
    await repo.release_resources(op.id)
    op.status = "completed"
    op.cleanup_status = "complete"
    await repo.save(op)
    assert row.id in [r.id for r in await repo.resources_to_reconcile("node-a")]
    await repo.complete_resource_cleanup(
        row.id, uid=UID, holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=3)
    )
    assert not await repo.resources_to_reconcile("node-a")


async def test_never_scheduled_proof_requires_empty_historical_binding(repo):
    await leased(repo)
    op = await setup_operation(repo)
    row = await bind(repo, await intent(repo, op), node_name="")
    await repo.request_resource_stop(row.id, operation_id=op.id, holder_id="controller-a", controller_epoch=1, now=NOW)
    row = await repo.confirm_resource_stop(
        row.id,
        evidence(node_name="", kind="never_scheduled"),
        holder_id="controller-a",
        controller_epoch=1,
        now=NOW + timedelta(seconds=2),
    )
    assert row.stop_state == "confirmed"


async def test_unconfirmed_pod_cleanup_and_secret_plaintext_are_refused(repo):
    await leased(repo)
    op = await setup_operation(repo)
    row = await bind(repo, await intent(repo, op))
    with pytest.raises(RuntimeConflict, match="stopped"):
        await repo.complete_resource_cleanup(row.id, uid=UID, holder_id="controller-a", controller_epoch=1, now=NOW)
    secret = resource(op, name="material-a", kind="Secret")
    secret.approved_template["data"] = {"key": "fake"}
    with pytest.raises(RuntimeConflict, match="secret"):
        await repo.create_resource_intent(secret, holder_id="controller-a", controller_epoch=1, now=NOW)


async def test_released_operation_cannot_create_another_pod_without_admission(repo):
    await leased(repo)
    op = await setup_operation(repo)
    await repo.release_resources(op.id)
    with pytest.raises(RuntimeConflict, match="capacity"):
        await intent(repo, op)


async def test_later_capability_report_cannot_retroactively_protect_an_old_pod(repo):
    await leased(repo)
    op = await setup_operation(repo)
    node = await repo.get(RuntimeNode, "node-a")
    node.capabilities = {}
    await repo.save(node)
    row = await bind(repo, await intent(repo, op))
    assert not row.protected_since_creation
    node.capabilities = {"status_protection": True, "status_policy_revision": "v1"}
    await repo.save(node)
    row = await bind(repo, row)
    assert not row.protected_since_creation
