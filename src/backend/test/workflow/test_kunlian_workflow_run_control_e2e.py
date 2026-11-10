"""隔离候选 HTTP、真实本地队列和不同 Worker 进程。"""

import json
import subprocess
import sys
from asyncio import sleep, to_thread
from asyncio import wait_for as wait_for_async
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from test.workflow.kunlian_workflow_run_control_worker import QUEUE, RECONCILE_TASK, RUN_TASK
from test.workflow.test_kunlian_workflow_interaction_e2e import (
    ANSWER,
    ANSWER_KEY,
    BODY,
    OWNER,
    PATH,
    _start,
)
from test.workflow.test_kunlian_workflow_interaction_e2e import environment as environment
from test.workflow.test_kunlian_workflow_invocation import publish
from test.workflow.test_kunlian_workflow_run_control_api import control_api as control_api
from test.workflow.test_kunlian_workflow_run_control_cancel import kinds
from test.workflow.test_platform_agent_long_task_resume_e2e import isolated_broker as isolated_broker
from test.workflow.test_platform_agent_long_task_resume_e2e import stop_process, wait_for

PRODUCER = """
import json
import sys
from celery import Celery

broker, queue, name, tenant, wait, args, kwargs = sys.argv[1:]
app = Celery('f127_producer', broker=broker, backend=broker, set_as_current=False)
try:
    task = app.send_task(name, args=json.loads(args), kwargs=json.loads(kwargs), queue=queue,
                         headers={'tenant_id': int(tenant)})
    print(json.dumps(task.get(timeout=8) if wait == 'yes' else task.id))
finally:
    app.close()
"""


@pytest.fixture
def worker_queue(control_api, isolated_broker, tmp_path, monkeypatch):
    _, _, service, now, _ = control_api
    with service.repository.registration.transaction() as session:
        database = session.get_bind().url.database
    clock = tmp_path / "clock"
    clock.write_text(str(now[0]))
    backend = Path(__file__).resolve().parents[2]
    workers = []

    def send(name, *args, tenant_id=7, wait=True, **kwargs):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                PRODUCER,
                isolated_broker,
                QUEUE,
                name,
                str(tenant_id),
                "yes" if wait else "no",
                json.dumps(args),
                json.dumps(kwargs),
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=12,
        )
        assert completed.returncode == 0, completed.stderr[-2200:]
        return json.loads(completed.stdout.splitlines()[-1])

    def dispatch(tenant_id, session_id, interaction_id=None):
        if interaction_id is None:
            return send(RUN_TASK, session_id, tenant_id=tenant_id, wait=False)
        return send(RUN_TASK, session_id, interaction_id, tenant_id=tenant_id, wait=False, phase="resume")

    async def launch(name, *, hold=False):
        ready, log = tmp_path / f"{name}.ready", tmp_path / f"{name}.log"
        with log.open("w") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "test.workflow.kunlian_workflow_run_control_worker",
                    database,
                    isolated_broker,
                    str(ready),
                    str(clock),
                    "hold" if hold else "normal",
                ],
                cwd=backend,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        workers.append(process)
        await to_thread(wait_for, ready.exists, process, log)
        assert int(ready.read_text()) == process.pid
        return process, ready.with_suffix(".events"), log

    monkeypatch.setattr(service, "dispatch", dispatch)
    try:
        yield launch, send, clock
    finally:
        for process in reversed(workers):
            stop_process(process)


async def test_worker_exit_is_reconciled_after_original_deadline(control_api, worker_queue):
    """AC-02. 原进程退出后由另一进程收敛。旧队列消息不再执行。"""
    app, _, service, now, _ = control_api
    launch, send, clock = worker_queue
    first, first_events, first_log = await launch("worker_a", hold=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        await to_thread(wait_for, first_events.exists, first, first_log)
        running = service.repository.load(7, session_id)
        assert running.status == "RUNNING"
        pending = await client.post(path + "/cancel")
        assert pending.status_code == 202 and pending.json()["data"]["status"] == "CANCEL_REQUESTED"
        first.terminate()
        await to_thread(first.wait, 5)

        second, second_events, _ = await launch("worker_b")
        assert first.pid != second.pid
        for tenant in (7, 8):
            assert await to_thread(send, RECONCILE_TASK, tenant_id=tenant) == second.pid
        assert (await client.get(path, params={"view": "status"})).json()["data"]["status"] == "CANCEL_REQUESTED"

        now[0] = running.deadline_at
        clock.write_text(str(now[0]))
        assert await to_thread(send, RECONCILE_TASK, tenant_id=8) == second.pid
        assert service.repository.load(7, session_id).status == "CANCEL_REQUESTED"
        for _ in range(2):
            assert await to_thread(send, RECONCILE_TASK) == second.pid
        await to_thread(send, RUN_TASK, session_id)

        final = service.repository.load(7, session_id)
        status = (await client.get(path, params={"view": "status"})).json()["data"]
        assert (status["session_id"], status["workflow_version_id"], status["status"]) == (session_id, "1", "CANCELLED")
        assert final.deadline_at == running.deadline_at and final.output is None
        assert kinds(final) == ["ACCEPTED", "STARTED", "CANCEL_ACCEPTED", "CANCELLED"]
        assert [json.loads(line)["event"] for line in first_events.read_text().splitlines()] == ["start"]
        assert not second_events.exists()
        print(f"补偿证据 {first.pid=} {second.pid=} {session_id=} deadline={running.deadline_at} output_count=0")


async def wait_for_status(client, path, expected):
    async def poll():
        while True:
            response = await client.get(path)
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            if data["status"] == expected:
                return data
            assert data["status"] not in {"FAILED", "CANCELLED", "SUCCEEDED"}, data
            await sleep(0.03)

    return await wait_for_async(poll(), 8)


async def test_fixed_version_cancel_reconnect_and_legacy_resume(control_api, worker_queue):
    """AC-01/04/06/08. 验证取消续读及未取消运行的固定版本与答复查回。"""
    app, _, service, _, state = control_api
    launch, send, _ = worker_queue
    first, first_events, _ = await launch("worker_a")
    key = {"Idempotency-Key": "v1-resume"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        waiting = await wait_for_status(client, path, "WAITING_INPUT")
        before = await client.get(path + "/events")
        assert before.status_code == 200 and before.json()["status_code"] == 200
        cursor = before.json()["data"]["next_after"]
        assert cursor == 3 and waiting["workflow_version_id"] == "1"

        accepted = await client.post(PATH, json=BODY, headers=key)
        assert accepted.status_code == 202
        second_id = accepted.json()["data"]["session_id"]
        second_path = f"{PATH}/{second_id}"
        resume = await wait_for_status(client, second_path, "WAITING_INPUT")

    publish(service.repository.registration, 2, "V2", with_input=False)
    await to_thread(stop_process, first)
    second, second_events, _ = await launch("worker_b")
    assert first.pid != second.pid
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        cancelled = await client.post(path + "/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["data"]["cancel_state"] == "CONFIRMED"
        seen = []
        for _ in range(2):
            page = await client.get(path + "/events", params={"after": cursor, "limit": 1})
            assert page.status_code == 200
            data = page.json()["data"]
            seen.extend(event["kind"] for event in data["events"])
            cursor = data["next_after"]
        assert seen == ["CANCEL_ACCEPTED", "CANCELLED"] and not data["has_more"]
        terminal = await wait_for_status(client, path, "CANCELLED")
        assert terminal["session_id"] == session_id and "output" not in terminal
        state.subject = type(OWNER)(8, OWNER.connection_id, OWNER.user_id)
        denied = await client.get(path + "/events", params={"after": cursor})
        assert denied.status_code == 404 and denied.json()["status_message"] == "SESSION_NOT_FOUND"
        state.subject = OWNER

        replay = await client.post(PATH, json=BODY, headers=key)
        assert replay.status_code == 200 and replay.json()["data"]["session_id"] == second_id
        answer_path = f"{second_path}/interactions/{resume['interaction_id']}/submit"
        answer = await client.post(answer_path, json=ANSWER, headers=ANSWER_KEY)
        assert answer.status_code == 202
        completed = await wait_for_status(client, second_path, "SUCCEEDED")
        result = (await client.get(second_path + "?view=result")).json()["data"]
        assert completed["workflow_version_id"] == result["workflow_version_id"] == "1"
        prefix, text = result["output"]["result"].split(" | ", 1)
        assert prefix.startswith("V1 ") and json.loads(prefix[3:])["user_name"] == f"prefix-{first.pid}"
        assert text == ANSWER["input"]["question"]
        answer_replay = await client.post(answer_path, json=ANSWER, headers=ANSWER_KEY)
        assert answer_replay.status_code == 200 and answer_replay.json()["data"] == answer.json()["data"]
        await to_thread(send, RUN_TASK, second_id, resume["interaction_id"], phase="resume")

    assert [json.loads(line)["event"] for line in first_events.read_text().splitlines()] == ["start", "start"]
    assert [json.loads(line)["event"] for line in second_events.read_text().splitlines()] == ["output"]
    print(f"闭环证据 {first.pid=} {second.pid=} cancelled={session_id} resumed={second_id} version=1 output_count=1")
