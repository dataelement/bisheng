"""隔离 HTTP、消息投递和独立执行进程的 Mock 验收。"""

import json
import os
import subprocess
import sys
from asyncio import to_thread
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.permission import InvalidCatalogActionError, PermissionServiceUnavailableError
from bisheng.open_endpoints.api.endpoints import kunlian_workflow_runs as api
from bisheng.worker.workflow import kunlian_workflow_run as worker
from bisheng.workflow.application import kunlian_workflow_invocation as invocation
from bisheng.workflow.domain.models.kunlian_workflow_run import KunlianWorkflowRun
from bisheng.workflow.domain.repositories.kunlian_workflow_run import RunRepository
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject
from test.workflow.kunlian_interaction_worker import fake_node_services
from test.workflow.test_kunlian_workflow_invocation import publish
from test.workflow.test_kunlian_workflow_publication import FLOW_ID, SCOPE, seed

PATH = "/api/v2/kunlian/workflow-runs"
OWNER = RunSubject(7, "mock", 12)
BODY = {"workflow_id": FLOW_ID, "workflow_version_id": "1", "mode": "interactive"}
START_KEY = {"Idempotency-Key": "start"}
ANSWER_KEY = {"Idempotency-Key": "answer"}
ANSWER = {"input": {"question": "联调答案"}}


@pytest.fixture
def environment(invocation_registration_store, monkeypatch):
    from types import SimpleNamespace

    registration = invocation_registration_store
    seed(registration)
    publish(registration, 1, "V1 {{#start_example.user_info#}} | {{#input_example.question#}}", required=True)
    now = [1000]
    runs = RunRepository(registration, clock=lambda: now[0])
    state = SimpleNamespace(subject=OWNER, grant=True, ready=True, action_enabled=True, broker=True, dispatched=[])

    async def resolve(subject):
        return UserPayload(user_id=subject.user_id, tenant_id=subject.tenant_id, user_role=[])

    async def authorize(user, **kwargs):
        assert kwargs == {"resource_type": "workflow", "resource_id": FLOW_ID, "action": "use"}
        if not state.ready:
            raise PermissionServiceUnavailableError()
        if not state.action_enabled:
            raise InvalidCatalogActionError()
        if not state.grant or user.user_id != 12:
            raise UnAuthorizedError()

    def enqueue(*, args, headers, kwargs=None):
        if not state.broker:
            raise OSError("broker temporarily unavailable")
        state.dispatched.append({"args": args, "headers": headers, "kwargs": kwargs or {}})

    monkeypatch.setattr(invocation, "require_business_action", authorize)
    task = SimpleNamespace(apply_async=enqueue)
    service = invocation.WorkflowInvocationService(runs, resolve, lambda *args: worker.dispatch_task(task, *args))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v2")
    app.dependency_overrides[api.run_service] = lambda: service
    app.dependency_overrides[api.run_subject] = lambda: state.subject
    return app, service, registration, now, state


@pytest.fixture
def independent_worker(environment):
    _, _, registration, now, _ = environment
    with registration.transaction() as db:
        database = db.get_bind().url.database
    backend = Path(__file__).resolve().parents[2]

    async def run(envelope):
        completed = await to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "test.workflow.kunlian_interaction_worker",
                database,
                str(now[0]),
                json.dumps(envelope),
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr[-4000:]
        return json.loads(completed.stdout.splitlines()[-1])

    return run


async def _start(caller):
    accepted = await caller.post(PATH, json=BODY, headers=START_KEY)
    assert accepted.status_code == 202, accepted.text
    data = accepted.json()["data"]
    assert data["status"] == "QUEUED" and data["workflow_version_id"] == "1"
    return data["session_id"], f"{PATH}/{data['session_id']}"


def _submit_path(path, data):
    return f"{path}/interactions/{data['interaction_id']}/submit"


async def test_interaction_http_authorization_deadline_and_delivery_compensation(environment, monkeypatch):
    app, service, _, now, state = environment
    fake_node_services(monkeypatch.setattr)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        ident, path = await _start(caller)
        await worker.execute_run(service, 7, ident)
        waiting_response = await caller.get(path)
        assert waiting_response.headers["Cache-Control"] == "no-store"
        waiting = waiting_response.json()["data"]
        assert waiting["status"] == "WAITING_INPUT" and waiting["form"]["required"] == ["question"]
        assert waiting["form"]["properties"]["question"] == {"type": "string", "pattern": r"\S"}
        assert (await caller.get(path)).json()["data"] == waiting
        submit_path = _submit_path(path, waiting)

        for subject in (RunSubject(7, "mock", 11), RunSubject(7, "other", 12), RunSubject(8, "mock", 12)):
            state.subject = subject
            assert (await caller.get(path)).status_code == 404
            assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 404
        state.subject = OWNER
        state.ready = False
        assert (await caller.get(path)).status_code == 503
        assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 503
        state.ready = True
        state.grant = False
        assert (await caller.get(path)).status_code == 404
        assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 404
        state.grant = True

        for body in (
            {"input": {}},
            {"input": {"question": " \t\n"}},
            {"input": {"question": ["SECRET"]}},
            {**ANSWER, "user_id": 99},
        ):
            invalid = await caller.post(submit_path, json=body, headers=ANSWER_KEY)
            assert invalid.status_code == 422 and "SECRET" not in invalid.text
        wrong_id = f"{path}/interactions/{'0' * 32}/submit"
        assert (await caller.post(wrong_id, json=ANSWER, headers=ANSWER_KEY)).status_code == 404

        state.broker = False
        accepted = await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)
        assert accepted.status_code == 202 and len(state.dispatched) == 1
        pending = (await caller.get(path)).json()["data"]
        assert pending["status"] == "RESUME_QUEUED" and "form" not in pending
        state.broker = True
        await service.reconcile(SCOPE)
        assert state.dispatched[-1] == {
            "args": [ident, waiting["interaction_id"]],
            "headers": {"tenant_id": 7},
            "kwargs": {"phase": "resume"},
        }

        state.grant = False
        await worker.execute_run(service, 7, *state.dispatched[-1]["args"])
        assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 404
        assert (await caller.get(path)).status_code == 404
        state.grant = True
        failure = (await caller.get(path)).json()["data"]
        assert failure["status"] == "FAILED" and failure["error"] == "FORBIDDEN"
        replay = await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)
        assert replay.status_code == 200 and replay.json()["data"] == accepted.json()["data"]

        next_run = await caller.post(PATH, json=BODY, headers={"Idempotency-Key": "timeout"})
        next_ident = next_run.json()["data"]["session_id"]
        next_path = f"{PATH}/{next_ident}"
        await worker.execute_run(service, 7, next_ident)
        next_waiting = (await caller.get(next_path)).json()["data"]
        now[0] = next_waiting["expires_at"]
        expired = (await caller.get(next_path)).json()["data"]
        assert expired["status"] == "FAILED" and expired["error"] == "INPUT_TIMEOUT"
        assert "form" not in expired
        late = await caller.post(_submit_path(next_path, next_waiting), json=ANSWER, headers=ANSWER_KEY)
        assert late.status_code == 409 and late.json()["status_message"] == "INPUT_TIMEOUT"


async def test_disabled_use_action_is_denied_during_pending_resume(environment, monkeypatch):
    app, service, _, _, state = environment
    fake_node_services(monkeypatch.setattr)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://fixture"
    ) as caller:
        ident, path = await _start(caller)
        await worker.execute_run(service, 7, ident)
        waiting = (await caller.get(path)).json()["data"]
        submit_path = _submit_path(path, waiting)
        accepted = await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)
        assert accepted.status_code == 202
        state.action_enabled = False
        assert (await caller.get(path)).status_code == 404
        assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 404
        await worker.execute_run(service, 7, ident, waiting["interaction_id"])
        state.action_enabled = True
        failed = (await caller.get(path)).json()["data"]
        assert failed["status"] == "FAILED" and failed["error"] == "FORBIDDEN"


async def test_original_run_crosses_independent_worker_processes(environment, independent_worker):
    app, service, registration, now, state = environment
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        ident, path = await _start(caller)
        prefix = await independent_worker(state.dispatched[0])
        assert prefix["starts"] == [12] and prefix["status"] == "WAITING_INPUT"
        assert prefix["pid"] != os.getpid()

    # 模拟昆联用新的 HTTP 客户端轮询,且等待期间发布了新版本并下线。
    publish(registration, 2, "V2", with_input=False)
    registration.unpublish(SCOPE, FLOW_ID, 2)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        waiting = (await caller.get(path)).json()["data"]
        assert waiting["session_id"] == ident and waiting["workflow_version_id"] == "1"
        assert waiting["status"] == "WAITING_INPUT"
        stale = await caller.post(PATH, json=BODY, headers={"Idempotency-Key": "stale-version"})
        assert stale.status_code == 409 and stale.json()["status_message"] == "VERSION_UNAVAILABLE"
        submit_path = _submit_path(path, waiting)
        accepted = await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)
        receipt = {"session_id": ident, "interaction_id": waiting["interaction_id"], "status": "ACCEPTED"}
        assert accepted.status_code == 202 and accepted.json()["data"] == receipt
        pending = (await caller.get(path)).json()["data"]
        assert pending["status"] == "RESUME_QUEUED" and "interaction_id" not in pending
        assert len(state.dispatched) == 2

    restored = await independent_worker(state.dispatched[1])
    assert restored["pid"] not in (prefix["pid"], os.getpid())
    assert restored["starts"] == [] and restored["status"] == "SUCCEEDED"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as caller:
        result = (await caller.get(path)).json()["data"]
        assert result["status"] == "SUCCEEDED" and result["session_id"] == ident
        assert result["workflow_version_id"] == "1"
        output = result["output"]["result"]
        assert output.startswith("V1 ") and output.endswith(" | 联调答案")
        assert f"prefix-{prefix['pid']}" in output and f"prefix-{restored['pid']}" not in output
        replay = await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)
        assert replay.status_code == 200 and replay.json()["data"] == receipt and len(state.dispatched) == 2

        terminal = service.repository.load(7, ident)
        assert set(terminal.material) == {"interaction_id", "receipt"}
        now[0] = terminal.expires_at
        await service.reconcile(SCOPE)
        assert (await caller.get(path)).status_code == 404
        assert (await caller.post(submit_path, json=ANSWER, headers=ANSWER_KEY)).status_code == 404
        with registration.transaction() as db:
            stored = db.get(KunlianWorkflowRun, ident)
            assert stored.output is None and stored.material is None and stored.request_digest
