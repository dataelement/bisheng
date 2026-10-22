"""覆盖 AC: AC-03、AC-07、AC-08、AC-13、AC-14、AC-48、AC-49、AC-52."""

import copy
import hashlib
from datetime import timedelta

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode, RuntimeOperation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_protocol import ServiceIdentity, content_digest
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID, setup_operation
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo

REF = "33333333-3333-4333-8333-333333333333"
IMAGE = "example.invalid/app@sha256:" + "a" * 64
HELPER = "example.invalid/helper@sha256:" + "b" * 64
MANAGER = ServiceIdentity("manager-a", "node-a", ("manager",))
ADMISSION = ServiceIdentity("admission-a", "node-a", ("admission",))


def short_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()[:40]


def document(op, *, kind="Pod", purpose="serve"):
    name = "app-" + short_hash(op.app_id) if purpose == "serve" else "task-" + short_hash(REF)
    return {
        "resource_ref": REF,
        "operation_id": op.id,
        "holder_id": "controller-a",
        "controller_epoch": 1,
        "cluster_id": "cluster-a",
        "namespace": "namespace-a",
        "purpose": purpose,
        "template": {
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "namespace": "namespace-a",
                "name": name,
                "labels": {
                    "bisheng.managed": "v2",
                    "runtime.bisheng.io/resource": REF,
                    "runtime.bisheng.io/app": short_hash(op.app_id),
                    "runtime.bisheng.io/node": short_hash(op.node_id),
                    "runtime.bisheng.io/purpose": purpose,
                },
                "annotations": {
                    "runtime.bisheng.io/operation": op.id,
                    "runtime.bisheng.io/generation": str(op.generation),
                    "runtime.bisheng.io/owner-epoch": str(op.owner_epoch),
                    "runtime.bisheng.io/status-policy": "v1",
                },
                "finalizers": ["runtime.bisheng.io/stop-confirmed"],
            },
            "spec": {
                "nodeSelector": {"kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64"},
                "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "data-" + short_hash(op.app_id)}}]
                if purpose == "serve" and kind == "Pod"
                else [],
                "containers": [{"name": "app", "image": IMAGE, "command": ["python", "app.py"]}],
            },
        },
    }


@pytest.fixture
async def control(repo):
    from bisheng.app_runtime.domain.services.runtime_kubernetes_service import RuntimeKubernetesService

    node = await repo.get(RuntimeNode, "node-a")
    node.capabilities = {**node.capabilities, "helper_image": HELPER}
    await repo.save(node)
    svc = RuntimeKubernetesService(repo, clock=lambda: NOW)
    op = await setup_operation(repo)
    op = await repo.get(RuntimeOperation, op.id)
    assert op.status == "running"
    op.payload = {"resolved_delivery": {"mode": "bundle", "profile": {"runtime_image": IMAGE, "preparer_image": IMAGE}}}
    await repo.save(op)
    await svc.claim_controller(MANAGER, holder_id="controller-a", expected_epoch=0)
    return svc, repo, op


async def register(control, **changes):
    svc, _, op = control
    body = document(op)
    body.update(changes)
    return await svc.register_resource(MANAGER, body)


async def test_registration_commits_before_a_separate_admission_read(control):
    svc, repository, _ = control
    result = await register(control)
    assert result["resource_ref"] == REF
    assert repository._active.get() is None
    row = await repository.get(RuntimeExecutionResource, REF)
    assert row.spec_digest == content_digest(row.approved_template)
    plan = await svc.admission_plan(ADMISSION, REF)
    assert plan["template"] == row.approved_template
    assert plan["allow_create"] is True and plan["uid"] is None
    assert "tenant_id" not in plan and "holder_id" not in plan


async def test_registration_is_idempotent_and_never_changes_a_frozen_plan(control):
    svc, repository, op = control
    first = await register(control)
    assert await register(control) == first
    changed = document(op)
    changed["template"]["spec"]["containers"][0]["command"] = ["python", "other.py"]
    with pytest.raises(RuntimeConflict):
        await svc.register_resource(MANAGER, changed)
    assert (await repository.get(RuntimeExecutionResource, REF)).approved_template == document(op)["template"]


@pytest.mark.parametrize(
    "field,value",
    [("cluster_id", "other"), ("namespace", "kube-system"), ("controller_epoch", 2), ("holder_id", "other")],
)
async def test_registration_rejects_wrong_execution_domain_or_controller(control, field, value):
    with pytest.raises(RuntimeConflict):
        await register(control, **{field: value})


@pytest.mark.parametrize(
    "mutation",
    [
        "namespace",
        "name",
        "operation",
        "generation",
        "app",
        "resource",
        "purpose",
        "policy",
        "kind",
        "image",
        "plaintext",
    ],
)
async def test_registration_rejects_unbound_or_unfrozen_resource_content(control, mutation):
    svc, _, op = control
    body = document(op)
    template = body["template"]
    meta = template["metadata"]
    if mutation in {"namespace", "name"}:
        meta[mutation] = "foreign"
    elif mutation in {"operation", "generation", "policy"}:
        key = "status-policy" if mutation == "policy" else mutation
        meta["annotations"]["runtime.bisheng.io/" + key] = "foreign"
    elif mutation in {"app", "resource", "purpose"}:
        meta["labels"]["runtime.bisheng.io/" + mutation] = "foreign"
    elif mutation == "kind":
        template["kind"] = "Deployment"
    elif mutation == "image":
        template["spec"]["containers"][0]["image"] = "example.invalid/unapproved@sha256:" + "c" * 64
    else:
        template["spec"]["containers"][0]["env"] = [{"name": "TOKEN", "value": "must-not-store"}]
    with pytest.raises(RuntimeConflict):
        await svc.register_resource(MANAGER, body)


async def test_admission_role_cannot_register_or_claim(control):
    svc, _, op = control
    with pytest.raises(RuntimeConflict):
        await svc.register_resource(ADMISSION, document(op))
    with pytest.raises(RuntimeConflict):
        await svc.claim_controller(ADMISSION, holder_id="untrusted", expected_epoch=1)


async def test_cross_node_and_entry_readers_cannot_read_a_plan(control):
    svc, _, _ = control
    await register(control)
    for identity in (
        ServiceIdentity("other", "node-b", ("admission",)),
        ServiceIdentity("entry", "node-a", ("entry",)),
    ):
        with pytest.raises(RuntimeConflict):
            await svc.admission_plan(identity, REF)


async def test_verified_scope_overrides_ambient_bypass_and_restores_it(control):
    token = current_tenant_id.set(999)
    try:
        with bypass_tenant_filter():
            await register(control)
            assert current_tenant_id.get() == 999
    finally:
        current_tenant_id.reset(token)


async def test_stale_controller_lease_does_not_authorize_creation(control):
    svc, repository, _ = control
    await register(control)
    node = await repository.get(RuntimeNode, "node-a")
    node.lease_until = NOW - timedelta(seconds=1)
    await repository.save(node)
    plan = await svc.admission_plan(ADMISSION, REF)
    assert plan["allow_create"] is False
    with pytest.raises(RuntimeConflict):
        await svc.renew_controller(MANAGER, holder_id="controller-a", controller_epoch=1)


async def test_same_name_different_uid_is_never_adopted(control):
    svc, repository, _ = control
    await register(control)
    body = {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"}
    await svc.observe_resource(MANAGER, REF, body)
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(MANAGER, REF, {**body, "uid": "44444444-4444-4444-8444-444444444444"})
    assert (await repository.get(RuntimeExecutionResource, REF)).uid == UID


async def test_terminal_operation_keeps_same_uid_cleanup_but_cannot_create(control):
    svc, repository, op = control
    await register(control)
    auth = {"holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"}
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "bind"})
    op.status = "cancelled"
    await repository.save(op)
    plan = await svc.admission_plan(ADMISSION, REF)
    assert plan["allow_delete"] is False
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "stop", "operation_id": op.id})
    plan = await svc.admission_plan(ADMISSION, REF)
    assert plan["cleanup_only"] is True and plan["allow_create"] is False
    assert plan["allow_delete"] is True and plan["uid"] == UID
    assert not plan.get("stop_confirmed")
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(MANAGER, REF, {**auth, "action": "cleanup"})


async def test_observation_cannot_inject_a_completed_stop_or_change_template(control):
    svc, _, _ = control
    await register(control)
    body = {
        "action": "stopped",
        "holder_id": "controller-a",
        "controller_epoch": 1,
        "evidence": {"evidence_kind": "unknown", "uid": UID},
    }
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(MANAGER, REF, body)
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(
            MANAGER, REF, {"action": "replace", "template": copy.deepcopy(document(control[2])["template"])}
        )


async def test_controller_renewal_keeps_epoch_and_extends_only_its_lease(control):
    svc, repository, _ = control
    node = await repository.get(RuntimeNode, "node-a")
    node.lease_until = NOW + timedelta(seconds=1)
    await repository.save(node)
    result = await svc.renew_controller(MANAGER, holder_id="controller-a", controller_epoch=1)
    assert result["controller_epoch"] == 1
    assert (await repository.get(RuntimeNode, "node-a")).lease_until == NOW + timedelta(seconds=30)


async def test_secret_intent_contains_only_digest_and_no_private_bytes(control):
    svc, repository, op = control
    body = document(op, kind="Secret")
    body["template"].pop("spec")
    body["template"].update(type="Opaque", immutable=True, data_sha256="c" * 64)
    await svc.register_resource(MANAGER, body)
    row = await repository.get(RuntimeExecutionResource, REF)
    assert row.approved_template["data_sha256"] == "c" * 64
    body["template"]["data"] = {"private": "must-not-store"}
    with pytest.raises(RuntimeConflict):
        await svc.register_resource(MANAGER, body)


async def test_lost_assignment_fence_refuses_new_admission(control):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeAssignment

    svc, repository, _ = control
    await register(control)
    assignment = (await repository.find(RuntimeAssignment, app_id=control[2].app_id))[0]
    assignment.generation += 1
    await repository.save(assignment)
    assert (await svc.admission_plan(ADMISSION, REF))["allow_create"] is False


@pytest.mark.parametrize("broken", ["metadata", "spec", "containers", "container", "env", "purpose"])
async def test_malformed_nested_content_is_refused_without_a_runtime_exception(control, broken):
    svc, repository, op = control
    body = document(op)
    if broken in {"metadata", "spec"}:
        body["template"][broken] = None
    elif broken == "containers":
        body["template"]["spec"]["containers"] = None
    elif broken == "container":
        body["template"]["spec"]["containers"] = [None]
    elif broken == "env":
        body["template"]["spec"]["containers"][0]["env"] = None
    else:
        body["purpose"] = []
    with pytest.raises(RuntimeConflict):
        await svc.register_resource(MANAGER, body)
    assert await repository.find(RuntimeExecutionResource, operation_id=op.id) == []


async def test_boolean_controller_epoch_cannot_coerce_to_the_current_epoch(control):
    svc, _, _ = control
    with pytest.raises(RuntimeConflict):
        await register(control, controller_epoch=True)
    with pytest.raises(RuntimeConflict):
        await svc.renew_controller(MANAGER, holder_id="controller-a", controller_epoch=True)


async def test_manager_can_recover_resource_identity_and_protection_without_local_files(control):
    svc, _repository, op = control
    await register(control)
    await svc.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"},
    )
    row = await svc.resource(MANAGER, REF)
    assert row["app_id"] == op.app_id and row["generation"] == op.generation and row["owner_epoch"] == op.owner_epoch
    assert row["purpose"] == "serve" and row["status_policy_revision"] == "v1"
    assert row["protected_since_creation"] is True and row["binding_policy_verified"] is True
    assert (await svc.resources(MANAGER, op.id))["resources"] == [row]
    for identity in (ADMISSION, ServiceIdentity("other", "node-b", ("manager",))):
        with pytest.raises(RuntimeConflict):
            await svc.resource(identity, REF)
        with pytest.raises(RuntimeConflict):
            await svc.resources(identity, op.id)


async def test_intermediate_phase_stop_does_not_release_the_whole_operation_reservation(control):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation
    from test.app_runtime.test_runtime_kubernetes_repository import evidence

    svc, repository, op = control
    await register(control)
    auth = {"holder_id": "controller-a", "controller_epoch": 1}
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "bind", "uid": UID, "node_name": "worker-a"})
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "stop", "operation_id": op.id})
    row = await repository.get(RuntimeExecutionResource, REF)
    proof = {**evidence(), "name": row.name, "namespace": row.namespace}
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "stopped", "evidence": proof})
    held = (await repository.find(RuntimeCapacityReservation, operation_id=op.id))[0]
    assert held.state != "released"


async def service_intent(control):
    svc, repository, op = control
    op.kind = "probe"
    await repository.save(op)
    await svc.register_resource(MANAGER, document(op, purpose="probe"))
    service_ref = "44444444-4444-4444-8444-444444444444"
    body = document(op, kind="Service", purpose="probe")
    body["resource_ref"] = service_ref
    body["template"]["metadata"]["labels"]["runtime.bisheng.io/resource"] = service_ref
    body["template"]["metadata"]["name"] = "svc-app-a"
    body["template"]["metadata"].pop("finalizers", None)
    body["template"]["spec"] = {
        "type": "ClusterIP",
        "selector": {"runtime.bisheng.io/resource": REF},
        "ports": [{"port": 8080, "targetPort": 8080, "protocol": "TCP"}],
    }
    await svc.register_resource(MANAGER, body)
    node = await repository.get(RuntimeNode, "node-a")
    node.capabilities = {**node.capabilities, "service_cidrs": ["10.96.0.0/12"]}
    await repository.save(node)
    return service_ref


async def test_service_observed_address_is_bound_once_for_the_route_proof(control):
    svc, repository, _ = control
    service_ref = await service_intent(control)
    auth = {
        "action": "bind",
        "holder_id": "controller-a",
        "controller_epoch": 1,
        "uid": "55555555-5555-4555-8555-555555555555",
        "runtime_state": {"cluster_ip": "10.96.0.10", "port": 8080},
    }
    result = await svc.observe_resource(MANAGER, service_ref, auth)
    assert result["observed_state"] == auth["runtime_state"]
    assert (await repository.get(RuntimeExecutionResource, service_ref)).observed_state == auth["runtime_state"]
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(
            MANAGER, service_ref, {**auth, "runtime_state": {"cluster_ip": "10.96.0.11", "port": 8080}}
        )


@pytest.mark.parametrize(
    "state",
    [
        {"cluster_ip": "192.168.1.10", "port": 8080},
        {"cluster_ip": "10.96.0.10", "port": 8081},
        {"cluster_ip": "10.96.0.10", "port": True},
        {"cluster_ip": "10.96.0.10", "port": 8080, "token": "private"},
    ],
)
async def test_observed_service_state_cannot_select_an_unregistered_address_or_port(control, state):
    svc, _, _ = control
    service_ref = await service_intent(control)
    with pytest.raises(RuntimeConflict):
        await svc.observe_resource(
            MANAGER,
            service_ref,
            {
                "action": "bind",
                "holder_id": "controller-a",
                "controller_epoch": 1,
                "uid": "55555555-5555-4555-8555-555555555555",
                "runtime_state": state,
            },
        )


async def test_new_controller_cleanup_updates_the_resource_admission_epoch(control):
    svc, repository, op = control
    await register(control)
    await svc.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1, "uid": UID, "node_name": "worker-a"},
    )
    svc.clock = lambda: NOW + timedelta(seconds=31)
    await svc.claim_controller(MANAGER, holder_id="controller-b", expected_epoch=1)
    await svc.observe_resource(
        MANAGER, REF, {"action": "stop", "holder_id": "controller-b", "controller_epoch": 2, "operation_id": op.id}
    )
    plan = await svc.admission_plan(ADMISSION, REF)
    assert plan["allow_delete"] is True
    assert (await repository.get(RuntimeExecutionResource, REF)).controller_epoch == 2


async def test_scratch_volume_deletion_requires_all_operation_writers_confirmed(control):
    svc, repository, op = control
    op.kind = "prepare"
    await repository.save(op)
    pod = document(op, purpose="prepare-download")
    await svc.register_resource(MANAGER, pod)
    auth = {"holder_id": "controller-a", "controller_epoch": 1}
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "bind", "uid": UID, "node_name": "worker-a"})
    volume_ref = "55555555-5555-4555-8555-555555555555"
    volume = document(op, kind="PersistentVolumeClaim", purpose="prepare-download")
    volume["resource_ref"] = volume_ref
    volume["template"]["metadata"]["name"] = "scratch-fixture"
    volume["template"]["metadata"]["labels"]["runtime.bisheng.io/resource"] = volume_ref
    volume["template"]["spec"] = {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "512Mi"}}}
    await svc.register_resource(MANAGER, volume)
    await svc.observe_resource(MANAGER, volume_ref, {**auth, "action": "bind", "uid": volume_ref})
    await svc.observe_resource(MANAGER, volume_ref, {**auth, "action": "stop", "operation_id": op.id})
    assert (await svc.admission_plan(ADMISSION, volume_ref))["allow_delete"] is False
    row = await repository.get(RuntimeExecutionResource, REF)
    row.stop_state = "confirmed"
    await repository.save(row)
    assert (await svc.admission_plan(ADMISSION, volume_ref))["allow_delete"] is True


async def test_normal_cleanup_never_authorizes_production_volume_deletion(control):
    svc, _, op = control
    volume = document(op, kind="PersistentVolumeClaim")
    volume["template"]["spec"] = {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "512Mi"}}}
    await svc.register_resource(MANAGER, volume)
    auth = {"holder_id": "controller-a", "controller_epoch": 1}
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "bind", "uid": UID})
    await svc.observe_resource(MANAGER, REF, {**auth, "action": "stop", "operation_id": op.id})
    assert (await svc.admission_plan(ADMISSION, REF))["allow_delete"] is False


@pytest.mark.parametrize("purpose", ["serve", "data", "migrate", "restore", "purge"])
def test_every_production_purpose_refuses_cross_application_volume(purpose):
    from types import SimpleNamespace

    from bisheng.app_runtime.domain.services.runtime_kubernetes_service import RuntimeKubernetesService

    operation = SimpleNamespace(app_id="app-a", id="operation-a", payload={"resolved_delivery": {"image_ref": IMAGE}})
    node = SimpleNamespace(platform="linux/amd64", capabilities={"helper_image": HELPER})
    pod = document(SimpleNamespace(app_id="app-a", id="operation-a", generation=1, owner_epoch=1, node_id="node-a"))[
        "template"
    ]
    pod["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] = "data-" + short_hash("app-b")
    with pytest.raises(RuntimeConflict, match="volume_scope"):
        RuntimeKubernetesService._validate_pod(pod, operation, node, purpose, REF)
