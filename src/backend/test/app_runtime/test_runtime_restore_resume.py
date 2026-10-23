"""覆盖 AC: AC-05、AC-13、AC-15、AC-47、AC-48、AC-49、AC-50、AC-52.

Real SQLite service/intent transactions consume actual manager-generated safe
Pod, Service and material-Secret projections. No copied purpose whitelist.
"""

import copy
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeArtifact,
    RuntimeAssignment,
    RuntimeDelivery,
    RuntimeExecutionFact,
    RuntimeNode,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource, RuntimeMaterialDelegation
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_material_service import RuntimeMaterialService
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.database.models.app import App
from bisheng.database.models.app_instance import AppInstance
from bisheng.database.models.app_version import AppVersion
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import HELPER, IMAGE, MANAGER, REF, short_hash
from test.app_runtime.test_runtime_kubernetes_service import control as control

SNAPSHOT = "a" * 32
SERVICE_REF = "44444444-4444-4444-8444-444444444444"
SECRET_REF = "55555555-5555-4555-8555-555555555555"


def manager_templates():
    # This sibling project's real builder is the contract producer under test.
    location = Path(__file__).resolve().parents[3] / "runtime-manager"
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))
    from runtime_manager.k8s_admission import template_projection
    from runtime_manager.k8s_templates import PodPlan, pod_template, secret_template, service_template

    return SimpleNamespace(
        Plan=PodPlan, pod=pod_template, service=service_template, secret=secret_template, project=template_projection
    )


def body(case, kind="Pod", *, purpose="serve"):
    templates = manager_templates()
    plan = templates.Plan(
        namespace="namespace-a",
        app_id=case.op.app_id,
        operation_id=case.op.id,
        resource_ref=REF if purpose == "serve" else case.helper_ref,
        node_id=case.op.node_id,
        generation=case.op.generation,
        owner_epoch=case.op.owner_epoch,
        purpose=purpose,
        platform="linux/amd64",
        status_policy_revision="v1",
        image=IMAGE if purpose == "serve" else HELPER,
        helper_image=HELPER,
        command=("python", "app.py") if purpose == "serve" else (),
        memory_mb=512,
        cpu_millicores=100,
        mode="bundle" if purpose == "serve" else "image",
        runtime_language="python3.11",
        pvc_name="data-" + short_hash(case.op.app_id),
        material_secret="material-" + REF.replace("-", "") if purpose == "serve" else "",
        deadline_seconds=None if purpose == "serve" else 600,
    )
    if kind == "Service":
        template = templates.service(plan)
        # The executor keeps the selector on the Pod while freezing the Service's own ref.
        template["metadata"]["labels"]["runtime.bisheng.io/resource"] = SERVICE_REF
        reference = SERVICE_REF
    elif kind == "Secret":
        reference = SECRET_REF
        template = templates.secret(
            replace(plan, resource_ref=reference), name=plan.material_secret, data={"fixture": b"fixture-only"}
        )
    else:
        reference, template = plan.resource_ref, templates.pod(plan)
    return {
        "resource_ref": reference,
        "operation_id": case.op.id,
        "holder_id": "controller-a",
        "controller_epoch": 1,
        "cluster_id": "cluster-a",
        "namespace": "namespace-a",
        "purpose": purpose,
        "template": templates.project(template),
    }


@pytest.fixture
async def restoring(control):
    service, repository, op = control
    # Extend only this test's private SQLite database with the real App table.
    async with repository._factory() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: App.__table__.create(c, checkfirst=True))
        await session.commit()
    app = await repository.save(
        App(
            id=op.app_id,
            tenant_id=1,
            owner_user_id=2,
            slug="e2e-f059-restore-resume",
            name="e2e-f059-restore-resume",
            state="online",
            current_version_id="version-a",
        )
    )
    op.kind, op.version_id, op.stage = "restore", "version-a", "maintenance"
    op.deadline = NOW + timedelta(minutes=10)
    delivery = copy.deepcopy(op.payload["resolved_delivery"])
    for kind in ("compiled", "dependencies"):
        artifact = await repository.save(
            RuntimeArtifact(
                tenant_id=1,
                app_id=op.app_id,
                scope_key="1/" + op.app_id,
                kind=kind,
                sha256=content_digest({"kind": kind}),
                size_bytes=0,
                state="verified",
                confirmed_at=NOW,
                object_key="fixture/" + kind,
            )
        )
        delivery["dependency_artifact_id" if kind == "dependencies" else "compiled_artifact_id"] = artifact.id
    await repository.save(
        RuntimeDelivery(
            tenant_id=1,
            app_id=op.app_id,
            version_id=op.version_id,
            execution_mode="bundle",
            resolved_platform="linux/amd64",
            delivery_digest=content_digest(delivery),
            content=delivery,
        )
    )
    op.payload = {
        "resolved_delivery": delivery,
        "snapshot_id": SNAPSHOT,
        "resume_after_restore": True,
        "expected_app_state": "online",
        "expected_current_version_id": "version-a",
        "expected_pending_version_id": None,
    }
    await repository.save(op)
    case = SimpleNamespace(
        service=service,
        repo=repository,
        op=op,
        app=app,
        delivery=delivery,
        helper_ref=str(uuid5(NAMESPACE_URL, "bisheng-maintenance:" + op.id + ":restore")),
    )
    helper = body(case, purpose="restore")
    await service.register_resource(MANAGER, helper)
    scope = {"holder_id": "controller-a", "controller_epoch": 1}
    await service.observe_resource(
        MANAGER, case.helper_ref, dict(action="create_begin", create_attempt_id=str(uuid4()), **scope)
    )
    await service.observe_resource(
        MANAGER, case.helper_ref, dict(action="bind", uid=UID, node_name="worker-a", **scope)
    )
    await service.observe_resource(MANAGER, case.helper_ref, dict(action="stop", operation_id=op.id, **scope))
    evidence = {
        "uid": UID,
        "namespace": "namespace-a",
        "name": helper["template"]["metadata"]["name"],
        "resource_version": "17",
        "node_name": "worker-a",
        "evidence_kind": "kubelet_terminal",
        "policy_revision": "v1",
        "status_digest": "c" * 64,
        "observed_at": NOW.isoformat() + "Z",
        "deletion_timestamp": NOW.isoformat() + "Z",
    }
    await service.observe_resource(MANAGER, case.helper_ref, dict(action="stopped", evidence=evidence, **scope))
    await service.observe_resource(MANAGER, case.helper_ref, dict(action="cleanup", uid=UID, **scope))
    progress = {
        "exec_ref": case.helper_ref,
        "parameters_digest": content_digest({"snapshot_id": SNAPSHOT}),
        "result": {
            "restored_snapshot_id": SNAPSHOT,
            "protected_snapshot": {
                "artifact_id": "b" * 32,
                "state": "verified",
                "confirmed_at": NOW.isoformat() + "Z",
                "sha256": "d" * 64,
                "size_bytes": 16384,
            },
        },
    }
    await repository.save(
        RuntimeExecutionFact(
            tenant_id=1,
            app_id=op.app_id,
            operation_id=op.id,
            node_id=op.node_id,
            generation=op.generation,
            owner_epoch=op.owner_epoch,
            sequence=1,
            phase="maintenance",
            exec_ref=case.helper_ref,
            detail={"maintenance_progress": {"restore": progress}},
        )
    )
    op.stage = "starting"
    await repository.save(op)
    case.progress = progress
    return case


@pytest.mark.parametrize("stage", ["starting", "ready", "serving"])
@pytest.mark.parametrize("kind", ["Pod", "Service", "Secret"])
async def test_restored_resume_registers_actual_frozen_serving_resources(restoring, stage, kind):
    case = restoring
    case.op.stage = stage
    await case.repo.save(case.op)
    document = body(case, kind)
    result = await case.service.register_resource(MANAGER, document)
    row = await case.repo.get(RuntimeExecutionResource, document["resource_ref"])
    assert row is not None and result["purpose"] == row.purpose == "serve"
    assert row.operation_id == case.op.id and (row.generation, row.owner_epoch) == (
        case.op.generation,
        case.op.owner_epoch,
    )
    assert row.approved_template == document["template"] and row.spec_digest == content_digest(document["template"])
    if kind == "Secret":
        assert "data" not in row.approved_template and "stringData" not in row.approved_template
    if kind == "Pod":
        helper = await case.repo.get(RuntimeExecutionResource, case.helper_ref)
        assert helper.uid == UID and helper.stop_state == "confirmed" and helper.cleanup_state == "complete"


@pytest.mark.parametrize("value", [False, 1, "true", None, "missing"])
async def test_restore_only_or_nonboolean_resume_never_registers_serve(restoring, value):
    case = restoring
    case.op.payload = {**case.op.payload, "resume_after_restore": value}
    if value == "missing":
        case.op.payload.pop("resume_after_restore")
    await case.repo.save(case.op)
    with pytest.raises(RuntimeConflict):
        await case.service.register_resource(MANAGER, body(case))
    assert await case.repo.get(RuntimeExecutionResource, REF) is None


@pytest.mark.parametrize("change", ["missing", "wrong-snapshot", "wrong-digest", "wrong-exec-ref", "empty-result"])
async def test_latest_durable_restore_result_must_match_snapshot_and_parameters(restoring, change):
    case = restoring
    progress = copy.deepcopy(case.progress)
    if change == "wrong-snapshot":
        progress["result"]["restored_snapshot_id"] = "c" * 32
    elif change == "wrong-digest":
        progress["parameters_digest"] = "e" * 64
    elif change == "wrong-exec-ref":
        progress["exec_ref"] = str(uuid4())
    elif change == "empty-result":
        progress["result"] = {}
    if change == "missing":
        case.op.payload = {**case.op.payload, "maintenance_progress": {"restore": copy.deepcopy(case.progress)}}
        await case.repo.save(case.op)
    detail = {} if change == "missing" else {"maintenance_progress": {"restore": progress}}
    await case.repo.save(
        RuntimeExecutionFact(
            tenant_id=1,
            app_id=case.op.app_id,
            operation_id=case.op.id,
            node_id=case.op.node_id,
            generation=case.op.generation,
            owner_epoch=case.op.owner_epoch,
            sequence=2,
            phase="maintenance",
            detail=detail,
        )
    )
    with pytest.raises(RuntimeConflict):
        await case.service.register_resource(MANAGER, body(case))
    assert await case.repo.get(RuntimeExecutionResource, REF) is None


@pytest.mark.parametrize("stage", ["admitted", "maintenance", "migrating", "failed"])
async def test_restore_resume_cannot_launch_before_the_starting_phase(restoring, stage):
    restoring.op.stage = stage
    await restoring.repo.save(restoring.op)
    with pytest.raises(RuntimeConflict):
        await restoring.service.register_resource(MANAGER, body(restoring))
    assert await restoring.repo.get(RuntimeExecutionResource, REF) is None


@pytest.mark.parametrize(
    "change", ["generation", "owner-epoch", "version", "deadline", "cancel", "lease", "namespace", "image", "pvc"]
)
async def test_restore_resume_preserves_existing_scope_and_frozen_template_guards(restoring, change):
    case, document = restoring, body(restoring)
    if change in {"generation", "owner-epoch"}:
        assignment = (await case.repo.find(RuntimeAssignment, app_id=case.op.app_id))[0]
        setattr(assignment, change.replace("-", "_"), getattr(assignment, change.replace("-", "_")) + 1)
        await case.repo.save(assignment)
    elif change == "version":
        case.app.current_version_id = "different-version"
        await case.repo.save(case.app)
    elif change == "deadline":
        case.op.deadline = NOW - timedelta(seconds=1)
        await case.repo.save(case.op)
    elif change == "cancel":
        case.op.payload = {**case.op.payload, "cancel_requested": True}
        await case.repo.save(case.op)
    elif change == "lease":
        document["controller_epoch"] = 2
    elif change == "namespace":
        document["template"]["metadata"]["namespace"] = "other"
    elif change == "image":
        document["template"]["spec"]["containers"][0]["image"] = "example.invalid/foreign@sha256:" + "f" * 64
    elif change == "pvc":
        next(v for v in document["template"]["spec"]["volumes"] if "persistentVolumeClaim" in v)[
            "persistentVolumeClaim"
        ]["claimName"] = "other-app"
    with pytest.raises(RuntimeConflict):
        await case.service.register_resource(MANAGER, document)
    assert await case.repo.get(RuntimeExecutionResource, REF) is None


@pytest.mark.parametrize("kind", ["migrate", "destroy", "data", "probe", "prepare"])
async def test_restore_result_does_not_enable_other_operation_kinds(restoring, kind):
    restoring.op.kind = kind
    await restoring.repo.save(restoring.op)
    with pytest.raises(RuntimeConflict):
        await restoring.service.register_resource(MANAGER, body(restoring))
    assert await restoring.repo.get(RuntimeExecutionResource, REF) is None


@pytest.mark.parametrize("field,value", [("stop_state", "requested"), ("cleanup_state", "pending")])
async def test_restore_resume_waits_for_same_uid_helper_stop_and_cleanup(restoring, field, value):
    helper = await restoring.repo.get(RuntimeExecutionResource, restoring.helper_ref)
    setattr(helper, field, value)
    await restoring.repo.save(helper)
    with pytest.raises(RuntimeConflict):
        await restoring.service.register_resource(MANAGER, body(restoring))
    assert await restoring.repo.get(RuntimeExecutionResource, REF) is None
    assert (await restoring.repo.get(RuntimeExecutionResource, restoring.helper_ref)).uid == UID


async def test_restored_serving_pod_retains_existing_material_lifetime_and_frozen_artifacts(restoring):
    case = restoring
    await case.service.register_resource(MANAGER, body(case))
    service = RuntimeMaterialService(case.repo, clock=lambda: NOW, proxy_key=b"restore-resume-fixture-key-32bytes")
    signer = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    grant = await service.create_delegation(
        MANAGER,
        {
            "operation_id": case.op.id,
            "exec_ref": REF,
            "key_id": "restore-serve-key",
            "public_key": signer.public_key().public_bytes_raw().hex(),
        },
    )
    row = await case.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
    assert row.scope_kind == "deployment-init" and row.expires_at is None
    assert row.operation_id == case.op.id and row.exec_ref == REF and row.version_id == case.op.version_id
    assert sorted(row.allowed_artifacts) == sorted(
        [case.delivery["compiled_artifact_id"], case.delivery["dependency_artifact_id"]]
    )
    assert row.allowed_actions == ["download"]


async def test_external_body_cannot_supply_the_internal_restore_serve_allowance(restoring):
    document = body(restoring)
    document["restore_serve"] = True
    with pytest.raises(RuntimeConflict, match="resource_request_invalid"):
        await restoring.service.register_resource(MANAGER, document)
    assert await restoring.repo.get(RuntimeExecutionResource, REF) is None


async def test_direct_template_validation_keeps_default_restore_serve_refusal(restoring):
    node = await restoring.repo.get(RuntimeNode, restoring.op.node_id)
    with pytest.raises(RuntimeConflict, match="resource_kind_or_purpose_refused"):
        restoring.service._validate_template(body(restoring), restoring.op, node, ["cluster-a", "namespace-a"])


@pytest.mark.parametrize("change", ["success", "restore-only", "pending-drift"])
async def test_restore_ready_fact_auto_commit_preserves_v1_and_activates_exact_route(restoring, change):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeOperation
    from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    case = restoring
    async with case.repo._factory() as session:
        connection = await session.connection()
        for model in (AppInstance, AppVersion):
            await connection.run_sync(lambda c, model=model: model.__table__.create(c, checkfirst=True))
        await session.commit()
    for number in (1, 2):
        await case.repo.save(
            AppVersion(
                id="version-a" if number == 1 else "version-b",
                app_id=case.op.app_id,
                version_no=number,
                kind="initial" if number == 1 else "iteration",
                tier_id="small",
                runtime="python3.11",
                code_object_key="fixture/source/" + str(number),
                terminal_state="online" if number == 1 else None,
            )
        )
    case.app.pending_version_id = "version-b"
    await case.repo.save(case.app)
    case.op.deadline = datetime.utcnow() + timedelta(minutes=10)
    case.op.payload = {
        **case.op.payload,
        "expected_pending_version_id": "version-b",
        "auto_commit": change != "restore-only",
        "resume_after_restore": change != "restore-only",
    }
    await case.repo.save(case.op)
    node = await case.repo.get(RuntimeNode, case.op.node_id)
    node.capabilities = {**node.capabilities, "service_cidrs": ["10.96.0.0/12"]}
    await case.repo.save(node)
    if change == "restore-only":
        with pytest.raises(RuntimeConflict):
            await case.service.register_resource(MANAGER, body(case))
        assert await case.repo.find(RuntimeRoute, app_id=case.op.app_id) == []
        assert await case.repo.find(RuntimeExecutionResource, operation_id=case.op.id, purpose="serve") == []
        return
    await case.service.register_resource(MANAGER, body(case))
    await case.service.register_resource(MANAGER, body(case, "Service"))
    scope = {"holder_id": "controller-a", "controller_epoch": 1}
    pod_uid = "88888888-8888-4888-8888-888888888888"
    service_uid = "99999999-9999-4999-8999-999999999999"
    await case.service.observe_resource(
        MANAGER, REF, {"action": "create_begin", "create_attempt_id": str(uuid4()), **scope}
    )
    await case.service.observe_resource(
        MANAGER, REF, {"action": "bind", "uid": pod_uid, "node_name": "worker-a", **scope}
    )
    await case.service.observe_resource(
        MANAGER,
        SERVICE_REF,
        {"action": "bind", "uid": service_uid, "runtime_state": {"cluster_ip": "10.96.0.10", "port": 8080}, **scope},
    )
    operation_service = RuntimeOperationService(case.repo, clock=lambda: NOW)
    ready = ExecutionFactInput(
        sequence=2,
        node_id=case.op.node_id,
        generation=case.op.generation,
        owner_epoch=case.op.owner_epoch,
        phase="ready",
        exec_ref=REF,
        detail={
            "controller": scope,
            "exec_ref": REF,
            "service_ref": SERVICE_REF,
            "pod_uid": pod_uid,
            "service_uid": service_uid,
            "target": {"host": "10.96.0.10", "port": 8080},
            "writers_stopped": True,
            "maintenance_progress": {"restore": copy.deepcopy(case.progress)},
        },
    )
    if change == "pending-drift":
        case.app.pending_version_id = "version-c"
        await case.repo.save(case.app)
        with pytest.raises(RuntimeConflict, match="application_state_changed"):
            await operation_service.fact(case.op, MANAGER, ready)
        app = await case.repo.get(App, case.app.id)
        assert app.current_version_id == "version-a" and app.pending_version_id == "version-c"
        assert await case.repo.find(RuntimeRoute, app_id=case.op.app_id) == []
        assert await case.repo.find(AppInstance, app_id=case.op.app_id) == []
        return
    await operation_service.fact(case.op, MANAGER, ready)
    app = await case.repo.get(App, case.app.id)
    routes = await case.repo.find(RuntimeRoute, app_id=case.op.app_id)
    operation = await case.repo.get(RuntimeOperation, case.op.id)
    instances = await case.repo.find(AppInstance, app_id=case.op.app_id)
    assert app.state == "online" and app.current_version_id == "version-a" and app.pending_version_id is None
    assert len(routes) == 1
    route = routes[0]
    assert (
        route.operation_id,
        route.exec_ref,
        route.version_id,
        route.generation,
        route.owner_epoch,
        route.status,
    ) == (case.op.id, REF, "version-a", case.op.generation, case.op.owner_epoch, "serving")
    assert operation.stage == "serving" and len(instances) == 1 and instances[0].exec_ref == REF
    assert (await case.repo.get(AppVersion, "version-a")).terminal_state == "online"
    assert (await case.repo.get(AppVersion, "version-b")).terminal_state is None
