import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from redis import Redis
from redis.exceptions import RedisError
from sqlmodel import select

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow import Flow
from bisheng.database.models.flow_version import FlowVersion
from bisheng.database.models.message import ChatMessage
from bisheng.workflow.application import platform_agent
from bisheng.workflow.domain.schemas.platform_agent import AgentReference, VerifiedAgentActor
from test.workflow.platform_agent_interaction_worker import FileLedger
from test.workflow.platform_agent_long_task_resume_worker import QUEUE, RECONCILE_TASK, RESUME_TASK, TASK_NAME
from test.workflow.test_platform_agent_interaction_wait import FLOW_ID, SESSION, prepare
from test.workflow.test_platform_agent_long_task_resume_wait import CALL, resume_graph
from test.workflow.test_platform_agent_long_task_resume_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_long_task_resume_wait import long_remote as long_remote

PROBE_FLOW = "e" * 32
PRODUCER = """
import json
import sys
from celery import Celery

broker, name, queue, args, kwargs = sys.argv[1:]
app = Celery('f126_producer', broker=broker, backend=broker, set_as_current=False)
try:
    task = app.send_task(name, args=json.loads(args), kwargs=json.loads(kwargs), queue=queue, headers={'tenant_id': 7})
    print(json.dumps(task.get(timeout=12), ensure_ascii=False))
finally:
    app.close()
"""


def wait_for(check, process, log, *, timeout=20):
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.05)
    pytest.fail(f"隔离进程未就绪。退出状态 {process.poll()}\n{log.read_text()[-4500:]}")


def stop_process(process):
    if process.stdin:
        process.stdin.close()
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def isolated_broker(tmp_path):
    redis_server = os.getenv("F126_REDIS_SERVER") or shutil.which("redis-server")
    if not redis_server:
        pytest.skip("需要本地 redis-server。可通过 F126_REDIS_SERVER 指定二进制")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log = tmp_path / "redis.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [redis_server, "--bind", "127.0.0.1", "--port", str(port), "--save", "", "--appendonly", "no"],
            cwd=tmp_path,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    client = Redis(host="127.0.0.1", port=port, socket_timeout=0.5)

    def started():
        try:
            return client.info("server")["process_id"] == process.pid
        except RedisError:
            return False

    try:
        wait_for(started, process, log)
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        client.close()
        stop_process(process)


async def test_single_slot_worker_completes_another_workflow_while_original_agent_waits(
    interaction_runtime, isolated_broker, tmp_path, monkeypatch
):
    runtime = interaction_runtime
    monkeypatch.setattr(runtime.service, "enable_long_task_resume", True, raising=False)
    probe = resume_graph()
    del probe["nodes"][1]
    probe["edges"][0]["target"] = "output_example"
    del probe["edges"][1]
    params = probe["nodes"][1]["data"]["group_params"][0]["params"]
    next(p for p in params if p["key"] == "message")["value"]["msg"] = "单执行槽探针"
    with tenant_execution_scope(7):
        execution, dispatch = await prepare(runtime, resume_graph())
        with runtime.repo.transaction() as db:
            db.add(Flow(id=PROBE_FLOW, name="并发探针", user_id=11, tenant_id=7, data=probe))
            database = db.get_bind().url.database
    ledger = tmp_path / "agent-ledger.sqlite3"
    ready = tmp_path / "worker.ready"
    log = tmp_path / "worker.log"
    backend = Path(__file__).resolve().parents[2]
    with log.open("w") as output:
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "test.workflow.platform_agent_long_task_resume_worker",
                database,
                str(ledger),
                isolated_broker,
                str(ready),
            ],
            cwd=backend,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.STDOUT,
        )

    async def execute(args, **kwargs):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", PRODUCER, isolated_broker, TASK_NAME, QUEUE, json.dumps(args), json.dumps(kwargs)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, (result.stderr[-2200:], log.read_text()[-4500:])
        return json.loads(result.stdout.splitlines()[-1])

    try:
        await asyncio.to_thread(wait_for, ready.exists, worker, log)
        first = await execute(
            [SESSION, FLOW_ID, "interaction", 12],
            platform_agent_execution={"execution_id": execution["execution_id"], "dispatch_id": dispatch},
        )
        with tenant_execution_scope(7):
            saved = runtime.repo.get_execution(execution["execution_id"])
        assert saved["state"] == "WAITING" and saved["dispatches"][dispatch]["state"] == "DONE"
        original = saved["calls"][CALL]
        remote = runtime.service.provider
        remote.ledger = FileLedger(ledger)
        actor = VerifiedAgentActor(12, 7)
        ref = AgentReference.model_validate(original["ref"])
        assert (await remote.get_status(actor, ref, original["agent_run_id"])).status == "RUNNING"

        second = await execute(["slot_probe", PROBE_FLOW, "probe", 12])
        with tenant_execution_scope(7):
            after = runtime.repo.get_execution(execution["execution_id"])
        assert after["state"] == "WAITING" and after["calls"][CALL] == original
        assert (await remote.get_status(actor, ref, original["agent_run_id"])).status == "RUNNING"
        assert first["pid"] == second["pid"] == worker.pid and first["worker"] == second["worker"]
        assert first["slots"] == second["slots"] == 1
        assert first["queue"] == second["queue"] == QUEUE and first["tenant_id"] == second["tenant_id"] == 7
        assert first["nodes"] == ["start_example"] and not first["outputs"]
        assert second["statuses"][-1] == "SUCCESS" and second["outputs"] == ["单执行槽探针"]
        print(
            f"F126 V-01 pid={worker.pid} slots={first['slots']} queue={QUEUE} "
            f"first={first['task_id']} second={second['task_id']} "
            f"execution={execution['execution_id']} run={original['agent_run_id']} "
            f"phase={original['long_task']['resume']['phase']} deadline={original['deadline']} "
            f"remote=RUNNING first_outputs=0 second_outputs=1"
        )
    finally:
        await asyncio.to_thread(stop_process, worker)


async def test_replacement_worker_recovers_v1_and_one_output_when_notification_is_lost(
    interaction_runtime, isolated_broker, tmp_path, monkeypatch
):
    run = interaction_runtime
    monkeypatch.setattr(run.service, "enable_long_task_resume", True)
    graph = resume_graph()
    params = graph["nodes"][2]["data"]["group_params"][0]["params"]
    next(p for p in params if p["key"] == "message")["value"]["msg"] += " {{#start_example.user_info#}}"
    with tenant_execution_scope(7):
        execution, initial = await prepare(run, graph)
        with run.repo.transaction() as db:
            database = db.get_bind().url.database
            ChatMessage.__table__.create(db.get_bind())

    execution_id = execution["execution_id"]
    ledger_path = tmp_path / "agent-ledger.sqlite3"
    run.service.provider.ledger = FileLedger(ledger_path)
    backend = Path(__file__).resolve().parents[2]

    def launch(name, now, notification="normal"):
        ready = tmp_path / f"{name}.ready"
        log = tmp_path / f"{name}.log"
        with log.open("w") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "test.workflow.platform_agent_long_task_resume_worker",
                    database,
                    str(ledger_path),
                    isolated_broker,
                    str(ready),
                    str(now),
                    notification,
                ],
                cwd=backend,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        return process, ready, log

    async def submit(name, args, log, **kwargs):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", PRODUCER, isolated_broker, name, QUEUE, json.dumps(args), json.dumps(kwargs)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, (result.stderr[-2200:], log.read_text()[-4500:])
        return json.loads(result.stdout.splitlines()[-1])

    original, ready, log = launch("worker-a", 1000)
    try:
        await asyncio.to_thread(wait_for, ready.exists, original, log)
        first = await submit(
            TASK_NAME,
            [SESSION, FLOW_ID, "interaction", 12],
            log,
            platform_agent_execution={"execution_id": execution_id, "dispatch_id": initial},
        )
        assert first["nodes"] == ["start_example"] and not first["outputs"]
    finally:
        await asyncio.to_thread(stop_process, original)
    assert original.returncode == 0

    with tenant_execution_scope(7):
        frozen = run.repo.get_execution(execution_id)
        call = frozen["calls"][CALL]
        remote_id = call["agent_run_id"]
        assert frozen["state"] == "WAITING" and frozen["dispatches"][initial]["workflow_version_id"] == 1
        assert [json.loads(line) for line in ready.with_suffix(".events").read_text().splitlines()] == [
            {"event": "start", "pid": original.pid, "run_id": remote_id}
        ]
        v2 = resume_graph()
        next(p for p in v2["nodes"][2]["data"]["group_params"][0]["params"] if p["key"] == "message")["value"][
            "msg"
        ] = "V2 不应执行"
        with run.repo.transaction() as db:
            db.add(FlowVersion(id=2, flow_id=FLOW_ID, name="v2", tenant_id=7, user_id=11, data=v2))
        await run.service.publish(run.publisher, FLOW_ID, 2)
        assert run.repo.get_version(2)["is_current"]
        for tick in (1003, 1004):
            run.now[0] = tick
            await run.service.reconcile_long(7, execution_id, CALL)
        record = run.repo.get_execution(execution_id)
        recovery = record["calls"][CALL]["long_task"]["resume"]["dispatch_id"]
        expired = await platform_agent.claim_long_task_resume(execution_id, CALL, recovery)
        lease_until = run.repo.get_execution(execution_id)["dispatches"][recovery]["lease_until"]

    replacement, ready, log = launch("worker-b", lease_until, "lost")
    events_path = ready.with_suffix(".events")
    try:
        await asyncio.to_thread(wait_for, ready.exists, replacement, log)
        await submit(RECONCILE_TASK, [execution_id, CALL], log)
        await asyncio.to_thread(
            wait_for, lambda: events_path.exists() and '"event": "notify"' in events_path.read_text(), replacement, log
        )
        await submit(RESUME_TASK, [execution_id, CALL, recovery], log)
        with tenant_execution_scope(7):
            finished = run.repo.get_execution(execution_id)
            receipt = await platform_agent.BrowserPlatformAgentRuntime(run.repo).read_long_task_resume_output(
                run.user,
                FLOW_ID,
                SESSION,
                execution_id,
            )
            with run.repo.transaction() as db:
                messages = db.exec(select(ChatMessage)).all()
        assert finished["state"] == "SUCCEEDED" and finished["calls"][CALL]["agent_run_id"] == remote_id
        assert finished["dispatches"][recovery]["owner"] != expired["dispatch"].owner
        assert len(messages) == 1 and messages[0].id == receipt["message_id"]
        assert f"prefix-{original.pid}" in receipt["message"]["msg"]
        assert "V2 不应执行" not in receipt["message"]["msg"]
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        assert all(event["pid"] == replacement.pid for event in events)
        assert not any(event["event"] == "start" for event in events)
        assert {event["node"] for event in events if event["event"] == "node"} == {
            "platform_agent_example",
            "output_example",
            "end_example",
        }
        assert [event["message_id"] for event in events if event["event"] == "notify"] == [receipt["message_id"]]
        assert original.pid != replacement.pid
        print(
            f"F126 V-02 worker_a={original.pid} worker_b={replacement.pid} execution={execution_id} "
            f"run={remote_id} dispatch={recovery} message={receipt['message_id']} versions=1,2 outputs=1 notify=lost"
        )
    finally:
        await asyncio.to_thread(stop_process, replacement)
