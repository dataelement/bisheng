"""覆盖 AC: AC-03、AC-07、AC-08、AC-13、AC-14、AC-30、AC-31、AC-48、AC-49、AC-52."""

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation, RuntimeNode, RuntimeOperation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, signed_headers
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import ADMISSION, HELPER, MANAGER, REF, document
from test.app_runtime.test_runtime_kubernetes_service import control as control

P = "/api/v1/internal/app-runtime/v2"


def heartbeat(**changes):
    from bisheng.app_runtime.api.endpoints.runtime_delivery import Heartbeat

    document = {
        "engine_id": "cluster-a/namespace-a",
        "executor_kind": "kubernetes",
        "platform": "linux/amd64",
        "memory_budget_mb": 4096,
        "cpu_budget_millicores": 4000,
        "capabilities": {
            "cluster_id": "cluster-a",
            "namespace": "namespace-a",
            "status_protection": True,
            "binding_protection": True,
            "mandatory_isolation": True,
            "status_policy_revision": "v1",
            "helper_image": HELPER,
            "service_cidrs": ["10.96.0.0/12"],
        },
        "probe_report": {
            "ready": True,
            "observed_at": NOW.isoformat(),
            "checks": [{"name": "mandatory-isolation", "ok": True, "reason": "verified"}],
        },
    }
    return Heartbeat(**{**document, **changes})


@pytest.fixture
async def coordination(control):
    from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService

    ctrl, repository, op = control
    op.kind = "prepare"
    await repository.save(op)
    svc = RuntimeOperationService(repository, clock=lambda: NOW)
    return SimpleNamespace(svc=svc, control=ctrl, repo=repository, op=op)


async def fact(c, *, phase="preparing", detail=None, sequence=1):
    return await c.svc.fact(
        c.op,
        MANAGER,
        ExecutionFactInput(
            sequence=sequence,
            node_id=c.op.node_id,
            generation=c.op.generation,
            owner_epoch=c.op.owner_epoch,
            phase=phase,
            detail=detail
            if detail is not None
            else {"controller": {"holder_id": "controller-a", "controller_epoch": 1}},
        ),
    )


async def test_heartbeat_freezes_executor_domain_and_publishes_controller_state(coordination):
    c = coordination
    response = await c.svc.heartbeat(MANAGER, heartbeat())
    node = await c.repo.get(RuntimeNode, "node-a")
    assert node.executor_kind == "kubernetes" and node.status == "ready" and node.probe_report["ready"] is True
    assert response["controller_epoch"] == 1 and response["controller_holder"] == "controller-a"
    plan = await c.svc.node_plan(MANAGER)
    assert plan["node"]["controller_epoch"] == 1 and plan["node"]["executor_kind"] == "kubernetes"


async def test_old_docker_heartbeat_without_new_fields_remains_compatible(coordination):
    from bisheng.app_runtime.api.endpoints.runtime_delivery import Heartbeat
    from bisheng.app_runtime.domain.services.runtime_protocol import ServiceIdentity

    c = coordination
    body = Heartbeat(
        engine_id="docker-engine", platform="linux/amd64", memory_budget_mb=1024, cpu_budget_millicores=1000
    )
    await c.svc.heartbeat(ServiceIdentity("docker", "docker-node", ("manager",)), body)
    node = await c.repo.get(RuntimeNode, "docker-node")
    assert node.executor_kind == "docker" and node.status == "ready"


@pytest.mark.parametrize("change", ["engine", "kind", "platform", "domain"])
async def test_heartbeat_cannot_reassign_a_configured_execution_domain(coordination, change):
    c = coordination
    body = heartbeat()
    if change == "engine":
        body.engine_id = "other/namespace-a"
    elif change == "kind":
        body.executor_kind = "docker"
    elif change == "platform":
        body.platform = "linux/arm64"
    else:
        body.capabilities = {**body.capabilities, "namespace": "other-namespace"}
    with pytest.raises(RuntimeConflict):
        await c.svc.heartbeat(MANAGER, body)
    assert (await c.repo.get(RuntimeNode, "node-a")).engine_id == "cluster-a/namespace-a"


@pytest.mark.parametrize("missing", ["mandatory_isolation", "status_protection", "binding_protection"])
async def test_failed_mandatory_probe_blocks_new_work_and_invalidates_continuous_protection(coordination, missing):
    c = coordination
    await c.control.register_resource(MANAGER, document(c.op, purpose="prepare-download"))
    await c.control.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "uid": UID, "node_name": "worker-a", "holder_id": "controller-a", "controller_epoch": 1},
    )
    body = heartbeat()
    body.capabilities = {**body.capabilities, missing: False}
    body.probe_report = {**body.probe_report, "ready": False}
    await c.svc.heartbeat(MANAGER, body)
    node = await c.repo.get(RuntimeNode, "node-a")
    assert node.status == "blocked"
    # Cleanup control still works, even though creation is blocked.
    await c.control.renew_controller(MANAGER, holder_id="controller-a", controller_epoch=1)
    row = await c.repo.get(RuntimeExecutionResource, REF)
    if missing in {"status_protection", "binding_protection"}:
        assert row.protected_since_creation is False or row.binding_policy_verified is False
    plan = await c.control.admission_plan(ADMISSION, REF)
    assert plan["allow_create"] is False


async def test_restoring_probe_does_not_retroactively_claim_continuous_status_protection(coordination):
    c = coordination
    await c.control.register_resource(MANAGER, document(c.op, purpose="prepare-download"))
    await c.control.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "uid": UID, "node_name": "worker-a", "holder_id": "controller-a", "controller_epoch": 1},
    )
    broken = heartbeat()
    broken.capabilities["status_protection"] = False
    broken.probe_report["ready"] = False
    await c.svc.heartbeat(MANAGER, broken)
    await c.svc.heartbeat(MANAGER, heartbeat())
    assert (await c.repo.get(RuntimeNode, "node-a")).status == "ready"
    assert (await c.repo.get(RuntimeExecutionResource, REF)).protected_since_creation is False


@pytest.mark.parametrize(
    "controller",
    [
        None,
        {"holder_id": "other", "controller_epoch": 1},
        {"holder_id": "controller-a", "controller_epoch": 0},
        {"holder_id": "controller-a", "controller_epoch": True},
    ],
)
async def test_k8s_facts_require_the_current_controller_holder_and_epoch(coordination, controller):
    c = coordination
    with pytest.raises(RuntimeConflict):
        await fact(c, detail={"controller": controller})
    assert (await c.repo.get(RuntimeOperation, c.op.id)).stage == c.op.stage


async def test_a_current_controller_fact_is_accepted_but_expired_lease_is_not(coordination):
    c = coordination
    assert (await fact(c))["phase"] == "preparing"
    node = await c.repo.get(RuntimeNode, "node-a")
    node.lease_until = NOW - timedelta(seconds=1)
    await c.repo.save(node)
    with pytest.raises(RuntimeConflict):
        await fact(c, sequence=2)


async def test_terminal_stopped_claim_cannot_bypass_resource_stop_evidence(coordination):
    c = coordination
    await c.control.register_resource(MANAGER, document(c.op, purpose="prepare-download"))
    with pytest.raises(RuntimeConflict):
        await fact(
            c,
            phase="failed",
            detail={
                "controller": {"holder_id": "controller-a", "controller_epoch": 1},
                "stopped": True,
                "cleanup_complete": True,
            },
        )
    row = (await c.repo.find(RuntimeCapacityReservation, operation_id=c.op.id))[0]
    assert row.state != "released" and (await c.repo.get(RuntimeOperation, c.op.id)).status == "running"


async def test_ready_target_must_match_a_bound_service_and_pod_before_route_can_switch(coordination):
    c = coordination
    c.op.kind = "preview"
    c.op.payload = {
        **c.op.payload,
        "session_id": "preview-a",
        "preview_expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }
    await c.repo.save(c.op)
    with pytest.raises(RuntimeConflict):
        await fact(
            c,
            phase="ready",
            detail={
                "controller": {"holder_id": "controller-a", "controller_epoch": 1},
                "target": {"host": "10.96.0.10", "port": 8080},
            },
        )


async def test_legacy_docker_facts_do_not_require_a_controller_receipt(coordination):
    c = coordination
    node = await c.repo.get(RuntimeNode, "node-a")
    node.executor_kind = "docker"
    await c.repo.save(node)
    assert (await fact(c, detail={}))["phase"] == "preparing"


async def test_runtime_route_masks_unknown_errors_before_the_global_business_handler(monkeypatch):
    from bisheng.app_runtime.api.endpoints import runtime_delivery as api

    settings = SimpleNamespace(
        enabled=True,
        runtime_service_keys={"manager": {"secret": "fixture-control-key", "roles": ["manager"], "node_id": "node-a"}},
    )
    monkeypatch.setattr(api, "settings", SimpleNamespace(app_runtime=settings))

    async def unavailable(*args):
        raise RuntimeError("fixture-private-redis-connection-detail")

    monkeypatch.setattr(api, "consume_runtime_nonce", unavailable)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    @app.exception_handler(Exception)
    async def global_handler(request, exc):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    body = canonical_json(
        {"engine_id": "engine", "platform": "linux/amd64", "memory_budget_mb": 1024, "cpu_budget_millicores": 1000}
    )
    path = P + "/nodes/heartbeat"
    headers = signed_headers("POST", path, body, key_id="manager", secret="fixture-control-key")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post(path, content=body, headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 503 and "fixture-private" not in response.text


async def test_ready_fact_requires_and_accepts_the_registered_service_address(coordination):
    from test.app_runtime.test_runtime_kubernetes_service import service_intent

    c = coordination
    service_ref = await service_intent((c.control, c.repo, c.op))
    auth = {"action": "bind", "holder_id": "controller-a", "controller_epoch": 1}
    await c.control.observe_resource(MANAGER, REF, {**auth, "uid": UID, "node_name": "worker-a"})
    service_uid = "55555555-5555-4555-8555-555555555555"
    await c.control.observe_resource(
        MANAGER, service_ref, {**auth, "uid": service_uid, "runtime_state": {"cluster_ip": "10.96.0.10", "port": 8080}}
    )
    body = ExecutionFactInput(
        sequence=1,
        node_id=c.op.node_id,
        generation=c.op.generation,
        owner_epoch=c.op.owner_epoch,
        phase="ready",
        exec_ref=REF,
        detail={
            "controller": {"holder_id": "controller-a", "controller_epoch": 1},
            "pod_uid": UID,
            "service_ref": service_ref,
            "service_uid": service_uid,
            "target": {"host": "10.96.0.10", "port": 8080},
        },
    )
    assert (await c.svc.fact(c.op, MANAGER, body))["phase"] == "ready"
    body.sequence = 2
    body.detail = {**body.detail, "target": {"host": "10.96.0.11", "port": 8080}}
    with pytest.raises(RuntimeConflict):
        await c.svc.fact(c.op, MANAGER, body)


async def test_failed_prerequisites_are_not_reported_as_a_capacity_wait(coordination):
    from bisheng.app_runtime.domain.schemas.runtime_delivery import OperationInput
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

    c = coordination
    node = await c.repo.get(RuntimeNode, "node-a")
    node.status = "blocked"
    await c.repo.save(node)

    async def app_loader(app_id):
        return SimpleNamespace(id=app_id, tenant_id=1, state="draft")

    c.svc.app_loader = app_loader
    with pytest.raises(AppOrchestratorUnavailableError):
        await c.svc.create(
            OperationInput(
                idempotency_key="blocked",
                app_id=c.op.app_id,
                kind="prepare",
                node_id="node-a",
                generation=1,
                owner_epoch=1,
            )
        )
    assert len(await c.repo.find(RuntimeOperation, app_id=c.op.app_id)) == 1


async def test_entry_route_stops_allowing_a_node_with_failed_mandatory_probes(coordination):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeRoute

    c = coordination
    await c.repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id=c.op.app_id,
            operation_id=c.op.id,
            route_key="app:" + c.op.app_id,
            version_id="version-a",
            node_id="node-a",
            exec_ref=REF,
            generation=1,
            owner_epoch=1,
            status="serving",
            target={"host": "10.96.0.10", "port": 8080},
        )
    )
    node = await c.repo.get(RuntimeNode, "node-a")
    node.status = "blocked"
    await c.repo.save(node)
    response = await c.svc.route("app:" + c.op.app_id)
    assert response["decision"] == "transition" and "target" not in response
