"""覆盖 AC: AC-35、AC-48、AC-49、AC-50、AC-52. Owner destroy only."""

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeExecutionFact
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_kubernetes_repository import NOW
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import (
    ADMISSION,
    HELPER,
    MANAGER,
    document,
    short_hash,
)
from test.app_runtime.test_runtime_kubernetes_service import (
    control as control,
)


async def test_purge_intent_requires_destroy_and_explicit_data_deletion(control):
    service, repository, op = control
    body = document(op, purpose="purge")
    body["template"]["metadata"]["name"] = "app-" + short_hash(op.app_id)
    body["template"]["spec"]["containers"] = [{"name": "maintenance", "image": HELPER}]
    body["template"]["spec"]["volumes"] = [
        {"name": "data", "persistentVolumeClaim": {"claimName": "data-" + short_hash(op.app_id)}}
    ]
    with pytest.raises(RuntimeConflict):
        await service.register_resource(MANAGER, body)
    op.kind = "destroy"
    op.payload = {"purge_volume": False}
    await repository.save(op)
    with pytest.raises(RuntimeConflict, match="purge"):
        await service.register_resource(MANAGER, body)
    op.payload = {"purge_volume": True}
    await repository.save(op)
    assert (await service.register_resource(MANAGER, body))["purpose"] == "purge"


async def test_purge_cannot_mount_another_apps_volume(control):
    service, repository, op = control
    op.kind = "destroy"
    op.payload = {"purge_volume": True}
    await repository.save(op)
    body = document(op, purpose="purge")
    body["template"]["metadata"]["name"] = "app-" + short_hash(op.app_id)
    body["template"]["spec"]["containers"] = [{"name": "maintenance", "image": HELPER}]
    body["template"]["spec"]["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": "foreign-app"}}]
    with pytest.raises(RuntimeConflict, match="volume"):
        await service.register_resource(MANAGER, body)


async def test_production_pvc_delete_requires_durable_purge_and_every_writer_cleanup(control):
    service, repository, op = control
    op.kind = "destroy"
    op.payload = {"purge_volume": True}
    await repository.save(op)
    row = RuntimeExecutionResource(
        tenant_id=op.tenant_id,
        app_id=op.app_id,
        operation_id=op.id,
        node_id=op.node_id,
        cluster_id="cluster-a",
        namespace="namespace-a",
        name="data-" + short_hash(op.app_id),
        kind="PersistentVolumeClaim",
        purpose="serve",
        generation=op.generation,
        owner_epoch=op.owner_epoch,
        controller_epoch=1,
        spec_digest="a" * 64,
        approved_template={},
        status_policy_revision="v1",
        uid="volume-uid",
    )
    await repository.save(row)
    await repository.request_resource_stop(
        row.id, operation_id=op.id, holder_id="controller-a", controller_epoch=1, now=NOW
    )
    assert not (await service.admission_plan(ADMISSION, row.id))["allow_delete"]
    await repository.save(
        RuntimeExecutionFact(
            tenant_id=op.tenant_id,
            app_id=op.app_id,
            operation_id=op.id,
            node_id=op.node_id,
            generation=op.generation,
            owner_epoch=op.owner_epoch,
            sequence=1,
            phase="stopping",
            detail={"maintenance_progress": {"purge": {"result": {"purged": True}}}},
        )
    )
    assert not (await service.admission_plan(ADMISSION, row.id))["allow_delete"]
    writer = RuntimeExecutionResource(
        tenant_id=op.tenant_id,
        app_id=op.app_id,
        operation_id=op.id,
        node_id=op.node_id,
        cluster_id="cluster-a",
        namespace="namespace-a",
        name="app-" + short_hash(op.app_id),
        kind="Pod",
        purpose="purge",
        generation=op.generation,
        owner_epoch=op.owner_epoch,
        controller_epoch=1,
        spec_digest="b" * 64,
        approved_template={},
        status_policy_revision="v1",
        uid="purge-uid",
        stop_state="confirmed",
        cleanup_state="pending",
    )
    await repository.save(writer)
    assert not (await service.admission_plan(ADMISSION, row.id))["allow_delete"]
    writer.cleanup_state = "complete"
    await repository.save(writer)
    assert (await service.admission_plan(ADMISSION, row.id))["allow_delete"]
