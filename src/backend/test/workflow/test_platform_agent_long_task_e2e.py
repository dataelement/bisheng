import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.application import platform_agent
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.graph.workflow import Workflow
from test.workflow.kunlian_interaction_worker import fake_node_services
from test.workflow.test_platform_agent_long_task_contract import long_remote as long_remote
from test.workflow.test_platform_agent_long_task_run import long_run as long_run


@pytest.mark.parametrize("stop_after_commit", [False, True])
async def test_published_session_runs_original_fixed_graph_and_reports_one_result(
    long_run, monkeypatch, stop_after_commit
):
    run = long_run
    flow_id = "f" * 32
    sample = (
        Path(__file__).resolve().parents[4] / "features/v3.0.0/124-kunlian-agent-long-task/mock-workflow.example.json"
    )
    graph = json.loads(sample.read_text())
    run.repo.save_version(1, data=graph)
    author = SimpleNamespace(user_id=11, tenant_id=7)
    await run.service.publish(author, flow_id, 1)
    monkeypatch.setattr(platform_agent, "get_service", lambda: run.service)
    runtime = platform_agent.BrowserPlatformAgentRuntime(run.repo)
    frozen, reference = await runtime.prepare(run.user, flow_id, "published-chat_async_task_id", graph, published=True)
    with tenant_execution_scope(7):
        context = await platform_agent.claim_queued_execution(reference, flow_id, "published-chat_async_task_id", 12)
    assert frozen["_platform_agent_publication"]["nodes"]["platform_agent_example"]["execution_mode"] == "async"
    version_two = json.loads(
        sample.read_text().replace('"v1"', '"v2"').replace('"query"', '"question"').replace("#answer", "#reply")
    )
    with run.repo.transaction() as session:
        session.add(FlowVersion(id=2, flow_id=flow_id, name="v2", tenant_id=7, user_id=11, data=version_two))
    start = run.provider.start

    async def start_then_publish(*args):
        accepted = await start(*args)
        await run.service.publish(author, flow_id, 2)
        return accepted

    monkeypatch.setattr(run.provider, "start", start_then_publish)

    outputs = []
    states = []
    callback = BaseCallback()
    callback.on_output_msg = lambda data: outputs.append(data.msg)
    callback.on_agent_long_task = states.append
    if stop_after_commit:

        def stop_after_agent(data):
            if data.node_id == "platform_agent_example":
                run.repo.request_stop(reference["execution_id"], cancel_long=True)

        callback.on_node_end = stop_after_agent
    fake_node_services(monkeypatch.setattr)
    workflow = Workflow(
        workflow_id=flow_id,
        user_id=12,
        tenant_id=7,
        workflow_data=frozen,
        max_steps=12,
        callback=callback,
        platform_agent_context=context,
        redact_errors=True,
    )
    with tenant_execution_scope(7):
        status, _ = await asyncio.to_thread(workflow.run)
    if stop_after_commit:
        assert status == "FAILED" and outputs == []
    else:
        assert status == "SUCCESS"
        assert len(outputs) == 1 and "B" in outputs[0]
    assert states and states[0]["remote_state"] == "RUNNING"
    summary = await runtime.long_status(run.user, flow_id, "published-chat_async_task_id", reference["execution_id"])
    assert summary["local_state"] == "SUCCEEDED"
    assert summary["agent_run_id"] == states[0]["agent_run_id"]
    assert (
        run.repo.get_workflow(flow_id)["data"]["_platform_agent_publication"]["nodes"]["platform_agent_example"]["ref"][
            "version_id"
        ]
        == "v2"
    )
    assert run.repo.long_snapshot(reference["execution_id"], "platform_agent_example:0")["ref"]["version_id"] == "v1"


async def test_sweep_task_reconciles_after_failed_wake_with_independent_service(long_run):
    from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile
    from bisheng.workflow.domain.repositories.platform_agent import PlatformAgentRepository
    from bisheng.workflow.domain.schemas.platform_agent import AgentReference
    from bisheng.workflow.domain.services.platform_agent_service import PlatformAgentService

    run = long_run
    execution_id = run.dispatch.execution_id
    key = f"{run.node['id']}:0"
    ref = AgentReference(agent_id="mock:echo", version_id="v1")
    run.repo.reserve_long_call(run.dispatch, key, "digest", ref.model_dump(), 1000, 1005, 1030)
    run.repo.permit_long_start(run.dispatch, key)
    actor = await run.service._long_actor(run.user, run.repo.get_execution(execution_id))
    accepted = await run.provider.start(actor, ref, {"query": "sample"}, f"{execution_id}:{key}")
    run.repo.request_stop(execution_id, cancel_long=True)
    other_repo = PlatformAgentRepository(run.repo.sessions, clock=run.repo.clock)
    provider = type(run.provider)(run.provider.config, ledger=run.ledger, clock=run.repo.clock)
    recovery = PlatformAgentService(config=run.service.config, repository=other_repo, provider=provider)

    def task(**_opts):
        def decorate(function):
            function.request = SimpleNamespace(headers={"tenant_id": 7})
            function.apply_async = Mock()
            return function

        return decorate

    sweep, _ = register_long_task_reconcile(SimpleNamespace(task=task), lambda: recovery)
    await asyncio.to_thread(sweep)
    assert other_repo.long_snapshot(execution_id, key)["cancel_state"] == "ACCEPTED"
    run.now[0] += 1
    await asyncio.to_thread(sweep)
    state = other_repo.long_snapshot(execution_id, key)
    assert state["run_id"] == accepted.run_id and state["cancel_state"] == "CONFIRMED"


def test_periodic_reconcile_requires_an_explicit_isolated_tenant():
    from bisheng.worker.workflow.platform_agent_long_task import register_long_task_reconcile

    signature = Mock()
    task = Mock()
    task.s.return_value = signature
    app = SimpleNamespace(task=Mock(return_value=lambda _: task), add_periodic_task=Mock())
    register_long_task_reconcile(app, lambda: None, tenant_ids=(7,))
    signature.set.assert_called_once_with(headers={"tenant_id": 7})
    app.add_periodic_task.assert_called_once_with(1.0, signature.set.return_value, name="f124-mock-reconcile-7")
