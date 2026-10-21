"""覆盖 AC: AC-31、AC-34、AC-35、AC-36、AC-37、AC-38、AC-49、AC-63。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeCapacityReservation,
    RuntimeCredentialBinding,
    RuntimeOperation,
    RuntimeRoute,
    RuntimeStorageBinding,
)
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.schemas.runtime_delivery import ExecutionFactInput, OperationInput
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.app_runtime.domain.services.runtime_projection_service import RuntimeProjectionService
from test.app_runtime.test_runtime_delivery_repository import operation
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


async def test_projection_switch_activates_candidate_handles_in_one_uow(runtime_repo):
    op = await runtime_repo.create_operation(operation())
    await runtime_repo.admit(op.id, memory_mb=128, cpu_millicores=100)
    await runtime_repo.claim(op.id, node_id=op.node_id, generation=op.generation, owner_epoch=op.owner_epoch)
    detail = {"exec_ref": "candidate", "target": {"host": "172.20.0.2", "port": 8080}}
    await runtime_repo.record_fact(
        op.id,
        sequence=1,
        node_id=op.node_id,
        generation=1,
        owner_epoch=1,
        phase="ready",
        exec_ref="candidate",
        detail=detail,
    )
    token = await runtime_repo.save(
        RuntimeCredentialBinding(
            tenant_id=1, app_id=op.app_id, operation_id=op.id, version_id=op.version_id, credential_id=10
        )
    )
    old = await runtime_repo.save(
        RuntimeStorageBinding(
            tenant_id=1,
            app_id=op.app_id,
            operation_id="old",
            version_id="old",
            namespace="production",
            object_prefix="test/",
            credential_hash="a" * 64,
            state="active",
        )
    )
    service = RuntimeProjectionService(runtime_repo)
    async with runtime_repo.transaction():
        await service.activate(op, {"result": detail})
    route = (await runtime_repo.find(RuntimeRoute, route_key=f"app:{op.app_id}"))[0]
    assert route.operation_id == op.id and route.status == "serving"
    assert (await runtime_repo.get(RuntimeCredentialBinding, token.id)).state == "active"
    assert (await runtime_repo.get(RuntimeStorageBinding, old.id)).state == "revoked"
    assert (await runtime_repo.find(RuntimeCapacityReservation, operation_id=op.id))[0].state == "active"


async def test_rollback_leaves_no_partially_active_route(runtime_repo):
    op = await runtime_repo.create_operation(operation())
    await runtime_repo.record_fact(
        op.id,
        sequence=1,
        node_id=op.node_id,
        generation=1,
        owner_epoch=1,
        phase="ready",
        exec_ref="candidate",
        detail={"target": {"host": "172.20.0.2", "port": 8080}},
    )
    with pytest.raises(RuntimeError):
        async with runtime_repo.transaction():
            await RuntimeProjectionService(runtime_repo).activate(
                op, {"result": {"exec_ref": "candidate", "target": {"host": "172.20.0.2", "port": 8080}}}
            )
            raise RuntimeError("commit failed")
    assert not await runtime_repo.find(RuntimeRoute, app_id=op.app_id)


async def test_environment_gate_prevents_early_node_execution(runtime_repo):
    app = SimpleNamespace(id="app-a", tenant_id=1, state="draft")

    async def load(app_id):
        return app

    svc = RuntimeOperationService(runtime_repo, app_loader=load)
    doc = await svc.create(
        OperationInput(
            app_id=app.id,
            idempotency_key="gate",
            kind="deploy",
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            payload={"environment_required": True, "tier": {"memory_mb": 128, "cpu_millicores": 100}},
        )
    )
    identity = SimpleNamespace(node_id="node-a", key_id="manager")
    op = await runtime_repo.get(RuntimeOperation, doc["operation_id"])
    assert (await svc.node_plan(identity))["operations"] == []
    with pytest.raises(RuntimeConflict, match="environment_not_ready"):
        await svc.claim(op, identity)


async def test_expired_operation_can_confirm_cleanup_and_release(runtime_repo):
    request = operation()
    request.kind = "prepare"
    op = await runtime_repo.create_operation(request)
    await runtime_repo.admit(op.id, memory_mb=128, cpu_millicores=100)
    op.deadline = datetime.utcnow() - timedelta(seconds=1)
    await runtime_repo.save(op)
    svc = RuntimeOperationService(runtime_repo)
    await svc.fact(
        op,
        SimpleNamespace(node_id="node-a"),
        ExecutionFactInput(
            sequence=1,
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            phase="timed_out",
            detail={"stopped": True, "cleanup_complete": True},
        ),
    )
    assert (await runtime_repo.find(RuntimeCapacityReservation, operation_id=op.id))[0].state == "released"


async def test_route_read_survives_manager_unavailability(runtime_repo):
    route = RuntimeRoute(
        tenant_id=1,
        app_id="app-a",
        route_key="app:app-a",
        operation_id="op",
        version_id="v",
        node_id="node-a",
        exec_ref="container",
        generation=1,
        owner_epoch=1,
        status="serving",
        target={"host": "172.20.0.2", "port": 8080},
    )
    await runtime_repo.save(route)
    answer = await RuntimeOperationService(runtime_repo).route("app:app-a")
    assert answer["decision"] == "allow" and answer["target"]["port"] == 8080


async def test_egress_retries_keep_credentials_and_cutover_fences_by_operation(runtime_repo, monkeypatch):
    """AC-50, AC-53: reusing a version never revives a retired operation's egress handle."""
    from cryptography.fernet import Fernet

    from bisheng.app_runtime.domain.services import runtime_egress_service as egress
    from bisheng.app_runtime.domain.services.runtime_egress_service import RuntimeEgressService
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    op = await runtime_repo.create_operation(operation())
    await runtime_repo.claim(op.id, node_id=op.node_id, generation=1, owner_epoch=1)
    service = RuntimeEgressService(runtime_repo)
    a = await service.issue(op, phase="runtime", declared=["example.com"])
    b = await service.issue(op, phase="runtime", declared=["example.com"])
    assert a == b
    assert egress.destination("https://user:password@mirror.example/simple", trusted=True)["host"] == "mirror.example"
    identity = SimpleNamespace(node_id=op.node_id)
    control = RuntimeOperationService(runtime_repo)
    assert (await control.policies(identity))["policies"]
    op.status = "completed"
    await runtime_repo.save(op)
    await runtime_repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id=op.app_id,
            route_key=f"app:{op.app_id}",
            operation_id="new-operation",
            version_id=op.version_id,
            node_id=op.node_id,
            generation=2,
            owner_epoch=1,
            exec_ref="new",
            target={},
        )
    )
    assert (await control.policies(identity))["policies"] == []


async def test_egress_deadline_is_utc_under_customer_timezone(runtime_repo, monkeypatch):
    """AC-50: a TZ=Asia/Shanghai deployment must not return already-expired policy epochs."""
    import os
    import time

    from cryptography.fernet import Fernet

    from bisheng.app_runtime.domain.services.runtime_egress_service import RuntimeEgressService
    from bisheng.app_runtime.domain.services.runtime_payload import seal
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "runtime_payload_key", Fernet.generate_key().decode())
    op = operation()
    op.payload = {"sealed_env": seal({"OPENAI_BASE_URL": "https://model.platform.example/api/v2/models/v1"})}
    op = await runtime_repo.create_operation(op)
    await runtime_repo.claim(op.id, node_id=op.node_id, generation=1, owner_epoch=1)
    await RuntimeEgressService(runtime_repo).issue(op, phase="runtime")
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()
        answer = await RuntimeOperationService(runtime_repo).policies(SimpleNamespace(node_id=op.node_id))
        assert 0 < answer["not_after"] - time.time() <= 5
        assert answer["policies"][0]["destinations"][0]["host"] == "model.platform.example"
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def test_credential_guard_fences_candidates_same_version_restarts_and_maintenance():
    """AC-39, AC-51: only the active operation's key is admitted to production capabilities."""
    from bisheng.app_runtime.domain.repositories.runtime_credential_repository import allowed

    route = SimpleNamespace(status="serving", version_id="v", operation_id="current")
    old = SimpleNamespace(state="active", version_id="v", operation_id="retired")
    current = SimpleNamespace(state="active", version_id="v", operation_id="current")
    candidate = SimpleNamespace(state="staged", version_id="v", operation_id="current")
    assert allowed(None, None)
    assert not allowed(None, candidate)
    assert not allowed(route, None)
    assert not allowed(route, old)
    assert not allowed(route, candidate)
    assert allowed(route, current)
    route.status = "maintenance"
    assert not allowed(route, current)


async def test_legacy_build_marker_survives_operation_reads(runtime_repo):
    """AC-63: recovery must use durable build-start evidence, not an in-process flag."""
    op = operation("legacy-build")
    op.kind = "prepare"
    op.payload = {"delivery": {"mode": "source-image"}}
    op = await runtime_repo.create_operation(op)
    await runtime_repo.admit(op.id, memory_mb=128, cpu_millicores=100)
    service = RuntimeOperationService(runtime_repo)
    await service.fact(
        op,
        SimpleNamespace(node_id=op.node_id),
        ExecutionFactInput(
            sequence=1,
            node_id=op.node_id,
            generation=1,
            owner_epoch=1,
            phase="preparing",
            detail={"legacy_build_state": "started"},
        ),
    )
    saved = await runtime_repo.get(RuntimeOperation, op.id)
    assert (await service.describe(saved))["payload"]["legacy_build_state"] == "started"


async def test_failure_diagnostic_is_durable_bounded_and_expires_without_losing_control_facts(runtime_repo):
    """AC-29, AC-63: a missing dependency remains diagnosable after container cleanup."""
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeExecutionFact

    op = operation("diagnostics")
    op.kind = "prepare"
    op.diagnostics_until = datetime.utcnow() - timedelta(seconds=1)
    op = await runtime_repo.create_operation(op)
    await runtime_repo.admit(op.id, memory_mb=128, cpu_millicores=100)
    service = RuntimeOperationService(runtime_repo)
    await service.fact(
        op,
        SimpleNamespace(node_id=op.node_id),
        ExecutionFactInput(
            sequence=1,
            node_id=op.node_id,
            generation=1,
            owner_epoch=1,
            phase="failed",
            detail={
                "reason": "preparation_process_failed",
                "stopped": True,
                "cleanup_complete": True,
                "diagnostic_tail": "x" * 20000 + " missing package test-wheel",
            },
        ),
    )
    stored = await runtime_repo.get(RuntimeOperation, op.id)
    assert len(stored.failure["diagnostic_tail"]) == 16384
    assert "test-wheel" in stored.failure["diagnostic_tail"]
    await runtime_repo.purge_diagnostics(op.node_id, datetime.utcnow())
    stored = await runtime_repo.get(RuntimeOperation, op.id)
    assert stored.failure["reason"] == "preparation_process_failed"
    assert "diagnostic_tail" not in stored.failure
    facts = await runtime_repo.find(RuntimeExecutionFact, operation_id=op.id)
    assert len(facts) == 1 and "diagnostic_tail" not in facts[0].detail


async def test_stale_runtime_node_has_a_stable_business_error(runtime_repo, monkeypatch):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.app_runtime, "runtime_default_node_id", "node-a")
    node = await runtime_repo.get(RuntimeNode, "node-a")
    node.heartbeat_at = datetime.utcnow() - timedelta(minutes=5)
    await runtime_repo.save(node)
    with pytest.raises(AppOrchestratorUnavailableError) as error:
        await RuntimeDeliveryCoordinator(runtime_repo).node(SimpleNamespace(id="app-a"))
    assert error.value.code == 16121


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
async def test_execution_failure_keeps_publish_stage_and_machine_readable_reason(runtime_repo, status):
    """AC-17, AC-29, AC-63: a cleaned probe failure remains actionable to the publisher."""
    from bisheng.app_publish.domain.schemas.failure import failure_from_error
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.common.errcode.app_factory import AppProbeFailedError

    op = await runtime_repo.create_operation(operation("probe-failure-" + status))
    op.status = status
    op.stage = status
    op.failure = {"reason": "readiness_timeout", "failed_stage": "starting", "maintenance": False}
    await runtime_repo.save(op)
    with pytest.raises(AppProbeFailedError) as error:
        await RuntimeDeliveryCoordinator(runtime_repo).wait(op)
    failure = failure_from_error(error.value, stage="precheck_probe")
    assert failure["stage"] == "precheck_probe"
    assert failure["code"] == 16124
    assert failure["details"]["operation_id"] == op.id
    assert failure["details"]["reason"] == "readiness_timeout"
    assert failure["details"]["runtime_stage"] == "starting"
