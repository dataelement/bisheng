from asyncio import to_thread
from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.open_endpoints.api.endpoints import kunlian_workflow_runs as api
from bisheng.worker.main import bisheng_celery
from bisheng.worker.workflow import kunlian_workflow_run as worker
from bisheng.workflow.application import kunlian_workflow_invocation as invocation
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject
from bisheng.workflow.nodes.output import output
from bisheng.workflow.nodes.start import start
from test.workflow.test_kunlian_workflow_invocation import publish
from test.workflow.test_kunlian_workflow_invocation import run_store as run_store
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE

PATH = "/api/v2/kunlian/workflow-runs"


async def test_mock_invoke_to_actual_graph_result_across_version_replacement(run_store, monkeypatch):
    """AC-01、AC-02、AC-04、AC-05、AC-06:候选 HTTP、实际图和测试 Worker。"""
    runs, registration, now = run_store
    seen_users = []
    dispatched = []
    grants = {12}
    subject = RunSubject(7, "mock", 12)
    active_subject = [subject]
    permission_ready = True
    expire_on_authorization = False

    def user_read(user_id):
        seen_users.append(user_id)
        return SimpleNamespace(user_name="实际用户")

    monkeypatch.setattr(start.UserDao, "get_user", user_read)
    for dao, attr in (
        (start.UserGroupDao, "get_user_group"),
        (start.UserRoleDao, "get_user_roles"),
        (start.UserDepartmentDao, "get_user_primary_department"),
    ):
        monkeypatch.setattr(dao, attr, lambda *_: None)
    monkeypatch.setattr(output, "get_minio_storage_sync", lambda: None)
    monkeypatch.setattr(
        worker, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=20, timeout=2))
    )

    async def resolve(value):
        return UserPayload(user_id=value.user_id, tenant_id=value.tenant_id, user_role=[])

    async def authorize(user, **kwargs):
        if not permission_ready:
            raise PermissionServiceUnavailableError()
        if user.user_id not in grants:
            raise UnAuthorizedError()
        if expire_on_authorization:
            now[0] += runs.retain_seconds

    monkeypatch.setattr(invocation, "require_business_action", authorize)
    service = invocation.WorkflowInvocationService(runs, resolve, lambda *args: worker.dispatch_task(task, *args))
    task = worker.register_task(bisheng_celery, service)

    def enqueue(*, args, headers):
        assert len(args) == 1
        dispatched.append((headers["tenant_id"], args[0]))

    def deliver(tenant_id, session_id):
        monkeypatch.setattr(task, "request", SimpleNamespace(headers={"tenant_id": tenant_id}), raising=False)
        task.run(session_id)

    monkeypatch.setattr(task, "apply_async", enqueue)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v2")
    body = {"workflow_id": FLOW_ID, "workflow_version_id": "1", "input": {"question": "Mock 入参"}}
    headers = {"Idempotency-Key": "call-1"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        denied = await caller.post(PATH, json=body, headers=headers)
        assert denied.status_code == 401
        app.dependency_overrides[api.run_subject] = lambda: active_subject[0]
        app.dependency_overrides[api.run_service] = lambda: service
        rejected = await caller.post(PATH, json={**body, "user_id": "SENSITIVE"}, headers=headers)
        assert rejected.status_code == 422 and "SENSITIVE" not in rejected.text
        accepted = await caller.post(PATH, json=body, headers=headers)
        assert accepted.status_code == 202, accepted.text
        data = accepted.json()["data"]
        session_id = data["session_id"]
        assert data["status"] == "QUEUED" and data["workflow_version_id"] == "1"
        assert dispatched == [(7, session_id)]
        assert (await caller.get(f"{PATH}/{session_id}")).json()["data"] == data

    publish(registration, 2, "V2", with_input=False)
    await to_thread(task.run, session_id)
    assert runs.load(7, session_id).status == "QUEUED"
    await to_thread(deliver, *dispatched[0])
    await to_thread(deliver, *dispatched[0])
    assert seen_users == [12]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        result = await caller.get(f"{PATH}/{session_id}")
        assert result.headers["Cache-Control"] == "no-store"
        done = result.json()["data"]
        assert done == {**data, "status": "SUCCEEDED", "output": {"result": "V1 Mock 入参"}}
        permission_ready = False
        unavailable = await caller.get(f"{PATH}/{session_id}")
        assert unavailable.status_code == 503 and unavailable.json()["data"] is None
        permission_ready = True
        assert (await caller.get(f"{PATH}/{session_id}")).json()["data"] == done
        replay = await caller.post(PATH, json=body, headers=headers)
        assert replay.status_code == 200 and replay.json()["data"]["session_id"] == session_id
        stale = await caller.post(PATH, json=body, headers={"Idempotency-Key": "stale"})
        assert stale.status_code == 409 and stale.json()["status_message"] == "VERSION_UNAVAILABLE"
        next_body = {"workflow_id": FLOW_ID, "workflow_version_id": "2"}
        next_run = await caller.post(PATH, json=next_body, headers={"Idempotency-Key": "call-2"})
        assert next_run.status_code == 202
        failed_run = await caller.post(PATH, json=next_body, headers={"Idempotency-Key": "call-3"})
        assert failed_run.status_code == 202
        registration.unpublish(SCOPE, FLOW_ID, 2)
        await to_thread(deliver, *dispatched[-2])
        next_path = f"{PATH}/{next_run.json()['data']['session_id']}"
        assert (await caller.get(next_path)).json()["data"]["output"] == {"result": "V2"}

        def fail_user_read(_):
            raise RuntimeError("SENSITIVE")

        monkeypatch.setattr(start.UserDao, "get_user", fail_user_read)
        graph_logs = []
        sink = logger.add(graph_logs.append, filter="bisheng.workflow.graph.graph_engine", diagnose=False)
        try:
            await to_thread(deliver, *dispatched[-1])
        finally:
            logger.remove(sink)
        assert graph_logs and all("SENSITIVE" not in line for line in graph_logs)
        fail_path = f"{PATH}/{failed_run.json()['data']['session_id']}"
        failed = await caller.get(fail_path)
        failure = failed.json()["data"]
        assert failure["status"] == "FAILED" and failure["error"] == "EXECUTION_FAILED"
        assert "output" not in failure and "SENSITIVE" not in failed.text
        assert (await caller.get(fail_path)).json()["data"] == failure
        offline = await caller.post(PATH, json=next_body, headers={"Idempotency-Key": "offline"})
        assert offline.status_code == 409 and offline.json()["status_message"] == "VERSION_UNAVAILABLE"

        for other in (RunSubject(7, "mock", 11), RunSubject(7, "other", 12), RunSubject(8, "mock", 12)):
            active_subject[0] = other
            denied = await caller.get(f"{PATH}/{session_id}")
            assert denied.status_code == 404 and denied.json()["data"] is None
        active_subject[0] = subject
        grants.clear()
        assert (await caller.get(f"{PATH}/{session_id}")).status_code == 404
        assert (await caller.post(PATH, json=body, headers=headers)).status_code == 403
        grants.add(12)
        expire_on_authorization = True
        expired = await caller.get(f"{PATH}/{session_id}")
        assert expired.status_code == 404 and expired.json()["data"] is None
