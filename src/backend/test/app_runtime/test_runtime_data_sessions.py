"""覆盖 AC: AC-15、AC-35、AC-36、AC-37、AC-43、AC-48、AC-49、AC-50."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeExecutionFact,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.common.errcode.app_factory import AppDataBusyError, AppDataForbiddenError, AppDataNotReadyError
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo

IMAGE = "example.invalid/helper@sha256:" + "a" * 64
UID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
async def session(repo):
    from bisheng.app_runtime.domain.services.runtime_data_session_service import RuntimeDataSessionService

    node = await repo.get(RuntimeNode, "node-a")
    node.heartbeat_at = datetime.utcnow()
    node.capabilities = {**node.capabilities, "helper_image": IMAGE}
    await repo.save(node)
    serving = await repo.save(
        RuntimeOperation(
            tenant_id=1,
            app_id="app-a",
            scope_key="1/app-a",
            idempotency_key="serve",
            request_digest="a" * 64,
            kind="deploy",
            node_id=node.id,
            generation=3,
            owner_epoch=1,
            deadline=datetime.utcnow() + timedelta(hours=1),
            status="completed",
            stage="completed",
            cleanup_status="complete",
        )
    )
    owner = await repo.save(
        RuntimeAssignment(
            tenant_id=1, app_id="app-a", node_id=node.id, generation=3, owner_epoch=1, active_operation_id=serving.id
        )
    )
    volume = await repo.save(
        RuntimeExecutionResource(
            tenant_id=1,
            app_id="app-a",
            operation_id=serving.id,
            node_id=node.id,
            cluster_id="cluster-a",
            namespace="namespace-a",
            name="data-fixture",
            kind="PersistentVolumeClaim",
            purpose="serve",
            generation=3,
            owner_epoch=1,
            controller_epoch=1,
            spec_digest="b" * 64,
            status_policy_revision="v1",
            uid=str(uuid4()),
        )
    )
    app = SimpleNamespace(id="app-a", tenant_id=1, owner_user_id=1, state="offline", current_version_id=None)
    actor = SimpleNamespace(user_id=1, tenant_id=1)
    events = []

    class Control:
        async def wakeup(self, operation_id):
            assert repo._active.get() is None, "I/O must follow SQL commit"
            op = await repo.get(RuntimeOperation, operation_id)
            events.append(("wakeup", operation_id))
            if op.payload.get("data_action_finished"):
                if op.payload["data_action_finished"] == "unknown":
                    return
                op.status, op.stage, op.cleanup_status = "completed", "completed", "complete"
                await repo.save(op)
                await repo.release(op.id, stopped=True)
                return
            op.status, op.stage = "running", "ready"
            await repo.save(op)
            await repo.save(
                RuntimeExecutionFact(
                    tenant_id=1,
                    app_id=op.app_id,
                    operation_id=op.id,
                    node_id=node.id,
                    generation=op.generation,
                    owner_epoch=op.owner_epoch,
                    sequence=1,
                    phase="ready",
                    exec_ref=str(uuid4()),
                    detail={"data_target": {"exec_ref": str(uuid4()), "pod_uid": UID, "online": False}},
                )
            )

    class Issuer:
        async def issue(self, app, actor, operation, target, action, parameters):
            assert repo._active.get() is None
            events.append(("issue", actor.user_id, action))
            return {"claims": {"operation_id": operation.id, "request_id": operation.payload["request_id"]}}

    class Transport:
        failure = None
        calls = 0

        async def call(self, app_id, action, parameters, ticket, *, timeout):
            assert repo._active.get() is None and 0 < timeout <= 60
            self.calls += 1
            events.append(("call", action, parameters))
            if self.failure:
                raise self.failure
            return {"rows": [{"name": "fixture"}]} if action == "rows" else {"tables": []}

    transport = Transport()
    svc = RuntimeDataSessionService(repo, control=Control(), issuer=Issuer(), transport=transport)
    return SimpleNamespace(
        svc=svc,
        repo=repo,
        app=app,
        actor=actor,
        owner=owner,
        serving=serving,
        volume=volume,
        events=events,
        transport=transport,
    )


async def test_owner_data_session_commits_before_io_without_changing_serving_state(session):
    c = session
    result = await c.svc.execute(c.app, c.actor, "rows", {"table": "items", "page": None, "size": None, "order": None})
    assert result["rows"][0]["name"] == "fixture"
    owner = await c.repo.get(RuntimeAssignment, c.owner.id)
    assert (owner.generation, owner.owner_epoch, owner.active_operation_id, owner.data_operation_id) == (
        3,
        1,
        c.serving.id,
        "",
    )
    assert c.app.state == "offline"
    assert [event[0] for event in c.events] == ["wakeup", "issue", "call", "wakeup"]
    assert c.events[2][2]["page"] == 1 and c.events[2][2]["size"] == 50


async def test_non_owner_and_super_admin_do_not_create_a_data_operation(session):
    c = session
    for actor in (SimpleNamespace(user_id=2), SimpleNamespace(user_id=3, is_global_super=True)):
        with pytest.raises(AppDataForbiddenError):
            await c.svc.execute(c.app, actor, "tables", {})
    assert not await c.repo.find(RuntimeOperation, kind="data") and not c.events


async def test_missing_persistent_volume_does_not_start_an_application(session):
    c = session
    c.volume.cleanup_state = "complete"
    await c.repo.save(c.volume)
    with pytest.raises(AppDataNotReadyError):
        await c.svc.execute(c.app, c.actor, "tables", {})
    assert not c.events


async def test_unknown_http_result_is_never_automatically_replayed_or_released(session):
    c = session
    c.transport.failure = httpx.ReadTimeout("lost response")
    with pytest.raises(AppDataBusyError):
        await c.svc.execute(c.app, c.actor, "update", {"table": "items", "key": "1", "values": {"name": "new"}})
    assert c.transport.calls == 1
    owner = await c.repo.get(RuntimeAssignment, c.owner.id)
    op = await c.repo.get(RuntimeOperation, owner.data_operation_id)
    assert op.payload["data_action_finished"] == "unknown" and owner.generation == 3


async def test_expiry_including_cold_start_prevents_ticket_issuance(session, monkeypatch):
    c = session

    async def expire(operation_id):
        op = await c.repo.get(RuntimeOperation, operation_id)
        op.deadline = datetime.utcnow() - timedelta(seconds=1)
        await c.repo.save(op)

    monkeypatch.setattr(c.svc.control, "wakeup", expire)
    with pytest.raises(AppDataBusyError):
        await c.svc.execute(c.app, c.actor, "tables", {})
    assert not any(event[0] in {"issue", "call"} for event in c.events)
    assert (await c.repo.get(RuntimeAssignment, c.owner.id)).data_operation_id


async def test_online_data_uses_existing_execution_instead_of_a_second_volume_writer(session):
    c = session
    c.app.state = "online"
    pod = await c.repo.save(
        RuntimeExecutionResource(
            tenant_id=1,
            app_id=c.app.id,
            operation_id=c.serving.id,
            node_id="node-a",
            cluster_id="cluster-a",
            namespace="namespace-a",
            name="app-fixture",
            kind="Pod",
            purpose="serve",
            generation=3,
            owner_epoch=1,
            controller_epoch=1,
            spec_digest="c" * 64,
            status_policy_revision="v1",
            uid=UID,
        )
    )
    await c.repo.save(
        RuntimeRoute(
            tenant_id=1,
            app_id=c.app.id,
            operation_id=c.serving.id,
            route_key="app:" + c.app.id,
            node_id="node-a",
            version_id="version-a",
            status="serving",
            exec_ref=pod.id,
            generation=3,
            owner_epoch=1,
            target={"host": "10.96.0.10", "port": 8080},
        )
    )
    await c.svc.execute(c.app, c.actor, "tables", {})
    op = (await c.repo.find(RuntimeOperation, kind="data"))[0]
    assert op.payload["target_exec_ref"] == pod.id and op.payload["target_pod_uid"] == UID
    assert op.payload["online"] is True


async def test_docker_detection_preserves_legacy_dispatch(session):
    c = session
    node = await c.repo.get(RuntimeNode, "node-a")
    node.executor_kind = "docker"
    await c.repo.save(node)
    assert await c.svc.supports(c.app) is False


async def test_existing_owner_api_dispatches_kubernetes_through_the_data_session(session, monkeypatch):
    import bisheng.app_runtime.domain.services.runtime_data_session_service as sessions
    from bisheng.app_runtime.domain.services import app_data_service as module

    c = session

    async def load(*args, **kwargs):
        return c.app

    class Runtime:
        async def supports(self, app):
            return True

        async def execute(self, app, actor, action, parameters):
            assert actor is c.actor and action == "tables" and parameters == {}
            return {"tables": [{"name": "via-session"}]}

    monkeypatch.setattr(sessions, "RuntimeDataSessionService", Runtime)
    monkeypatch.setattr(module.AppDataService, "_load_owned", load)
    monkeypatch.setattr(
        module, "settings", SimpleNamespace(app_runtime=SimpleNamespace(runtime_protocol_version=2)), raising=False
    )
    result = await module.AppDataService.list_tables(c.app.id, actor=c.actor)
    assert result["tables"][0]["name"] == "via-session"


async def test_lost_wakeup_response_uses_committed_state_without_replaying_data(session, monkeypatch):
    from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError

    c = session
    wake = c.svc.control.wakeup

    async def lost(operation_id):
        await wake(operation_id)
        raise AppOrchestratorUnavailableError()

    monkeypatch.setattr(c.svc.control, "wakeup", lost)
    assert await c.svc.execute(c.app, c.actor, "tables", {}) == {"tables": []}
    assert c.transport.calls == 1


@pytest.mark.parametrize("ready", [False, True])
async def test_cancelled_data_session_is_refused_before_waiting_or_issuing(session, monkeypatch, ready):
    """覆盖 AC: AC-33、AC-36、AC-43、AC-48、AC-49、AC-55."""
    c = session
    wake = c.svc.control.wakeup

    async def cancel_before_delivery(operation_id):
        op = await c.repo.get(RuntimeOperation, operation_id)
        if op.payload.get("data_action_finished"):
            return  # Actual manager cleanup/stop evidence is still outstanding.
        if ready:
            await wake(operation_id)
            op = await c.repo.get(RuntimeOperation, operation_id)
        op.payload = {**op.payload, "cancel_requested": True}
        await c.repo.save(op)

    async def unexpected_issue(*args, **kwargs):
        pytest.fail("cancelled data session reached grant issuance")

    async def unexpected_wait(*args):
        pytest.fail("cancelled data session waited for readiness")

    monkeypatch.setattr(c.svc.control, "wakeup", cancel_before_delivery)
    monkeypatch.setattr(c.svc.issuer, "issue", unexpected_issue)
    monkeypatch.setattr(c.svc, "sleep", unexpected_wait)
    with pytest.raises(AppDataBusyError) as rejected:
        await c.svc.execute(c.app, c.actor, "tables", {})
    assert rejected.value.kwargs["reason"] == "data_session_cancelled"
    owner = await c.repo.get(RuntimeAssignment, c.owner.id)
    current = await c.repo.get(RuntimeOperation, owner.data_operation_id)
    assert current.payload["cancel_requested"] is True
    assert current.cleanup_status == "pending" and current.status not in {"completed", "cancelled"}
    assert not c.transport.calls and not any(event[0] in {"issue", "call"} for event in c.events)
