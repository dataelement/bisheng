import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentExecutionError,
    PlatformAgentPublicationError,
)
from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.database.models.session import MessageSessionDao
from bisheng.worker.workflow import tasks
from bisheng.workflow.application import platform_agent
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.domain.services import platform_agent_service as domain
from bisheng.workflow.graph.platform_agent_interaction import restore_agent_wait
from bisheng.workflow.graph.workflow import Workflow
from test.workflow.kunlian_interaction_worker import fake_node_services
from test.workflow.test_platform_agent_interaction_contract import interactive_provider
from test.workflow.test_platform_agent_interaction_contract import long_remote as long_remote

FLOW_ID = "f" * 32
SESSION = "interaction_async_task_id"
AGENT_ID = "platform_agent_example"


def sample_graph(version_id="v1"):
    path = (
        Path(__file__).resolve().parents[4] / "features/v3.0.0/124-kunlian-agent-long-task/mock-workflow.example.json"
    )
    graph = json.loads(path.read_text())
    params = graph["nodes"][1]["data"]["group_params"][0]["params"]
    next(param for param in params if param["key"] == "agent_ref")["value"] = {
        "agent_id": "mock:interaction",
        "version_id": version_id,
    }
    params.append({"key": "allow_interaction", "value": True})
    return graph


@pytest.fixture
def interaction_runtime(long_agent_store, long_remote, monkeypatch):
    repo, _, _, now = long_agent_store
    provider = interactive_provider(long_remote, clock=repo.clock)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    monkeypatch.setattr(MessageSessionDao, "async_get_one", AsyncMock(return_value=None))

    async def advance(delay):
        now[0] += delay

    service = domain.PlatformAgentService(
        config=provider.config,
        repository=repo,
        provider=provider,
        long_pause=advance,
        enable_long_tasks=True,
        enable_interactions=True,
    )
    monkeypatch.setattr(platform_agent, "get_service", lambda: service)
    fake_node_services(monkeypatch.setattr)
    outputs, statuses, events, starts = [], [], [], []

    class Callback(BaseCallback):
        def __init__(self, unique_id, *_args, **_kwargs):
            self.unique_id = unique_id

        def get_platform_knowledge_reference(self):
            return None

        def bind_platform_agent_execution(self, execution_id):
            self.execution_id = execution_id

        def set_workflow_status(self, status, reason=None):
            statuses.append(status)

        def on_node_start(self, data):
            assert get_current_tenant_id() == 7
            starts.append(data.node_id)

        def on_agent_long_task(self, summary):
            if summary.get("interaction_pending"):
                assert repo.get_execution(self.execution_id)["state"] == "WAITING"
            events.append(summary)

        def on_output_msg(self, data):
            outputs.append(data.msg)

    monkeypatch.setattr(tasks, "RedisCallback", Callback)
    monkeypatch.setattr(tasks.execute_workflow, "request", SimpleNamespace(headers={"tenant_id": 7}), raising=False)
    monkeypatch.setattr(
        tasks, "settings", SimpleNamespace(get_workflow_conf=lambda: SimpleNamespace(max_steps=12, timeout=2))
    )
    monkeypatch.setattr(
        tasks.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(tenant_id=7, user_id=11, name="test")
    )
    monkeypatch.setattr(tasks, "_log_workflow_telemetry", lambda *_: None)
    return SimpleNamespace(
        repo=repo,
        now=now,
        service=service,
        outputs=outputs,
        statuses=statuses,
        events=events,
        starts=starts,
        publisher=SimpleNamespace(user_id=11, tenant_id=7),
        user=SimpleNamespace(user_id=12, tenant_id=7),
    )


async def prepare(runtime, graph):
    runtime.repo.save_version(1, data=graph)
    published = await runtime.service.publish(runtime.publisher, FLOW_ID, 1)
    browser = platform_agent.BrowserPlatformAgentRuntime(runtime.repo)
    _, reference = await browser.prepare(runtime.user, FLOW_ID, SESSION, published, published=True)
    return runtime.repo.get_execution(reference["execution_id"]), reference["dispatch_id"]


def run_worker(execution, dispatch_id):
    tasks.execute_workflow.run(
        SESSION,
        FLOW_ID,
        "interaction",
        12,
        platform_agent_execution={"execution_id": execution["execution_id"], "dispatch_id": dispatch_id},
    )


@pytest.mark.parametrize("version_id", ["v1", "immediate"])
async def test_worker_ends_at_persisted_wait_or_delivers_output_once(interaction_runtime, version_id):
    runtime = interaction_runtime
    with tenant_execution_scope(7):
        execution, dispatch_id = await prepare(runtime, sample_graph(version_id))
    await asyncio.to_thread(run_worker, execution, dispatch_id)
    with tenant_execution_scope(7):
        saved = runtime.repo.get_execution(execution["execution_id"])
    call = saved["calls"][f"{AGENT_ID}:0"]
    assert saved["dispatches"][dispatch_id]["state"] == "DONE"
    assert saved["dispatches"][dispatch_id]["workflow_version_id"] == 1
    assert SESSION not in tasks._global_workflow
    if version_id == "v1":
        wait = call["long_task"]["interaction"]
        assert saved["state"] == "WAITING" and wait["phase"] == "WAITING_INPUT"
        assert call["agent_run_id"] and wait["snapshot"]["agent_node"] == AGENT_ID
        assert wait["snapshot"]["steps"] == {"start_example": 1}
        assert wait["snapshot"]["execution_id"] == saved["execution_id"]
        assert runtime.starts == ["start_example"] and not runtime.outputs
        assert runtime.statuses[-1] == "INPUT" and runtime.events[-1]["interaction_pending"]
        assert "form" not in runtime.events[-1] and "snapshot" not in runtime.events[-1]
        with tenant_execution_scope(7), pytest.raises(PlatformAgentExecutionError):
            await platform_agent.BrowserPlatformAgentRuntime(runtime.repo).resume(
                runtime.user, FLOW_ID, saved["execution_id"], published=True
            )
        restored = Workflow(
            workflow_id=FLOW_ID,
            user_id=12,
            tenant_id=7,
            workflow_data=saved["graph_snapshot"],
            callback=BaseCallback(),
            platform_agent_context={"interaction_node": AGENT_ID},
        )
        invalid = deepcopy(wait["snapshot"])
        invalid["checkpoint"]["channel_values"]["branch:to:end_example"] = None
        with pytest.raises(PlatformAgentExecutionError):
            restore_agent_wait(restored, saved, invalid)
        restore_agent_wait(restored, saved, wait["snapshot"])
        assert restored.graph_engine.nodes_map["start_example"].current_step == 1
        assert restored.graph_engine.graph.get_state(restored.graph_engine.graph_config).next == (AGENT_ID,)
    else:
        assert saved["state"] == "SUCCEEDED" and call["state"] == "SUCCEEDED"
        assert runtime.starts.count(AGENT_ID) == len(runtime.outputs) == 1
    await asyncio.to_thread(run_worker, execution, dispatch_id)
    assert len(runtime.outputs) == (version_id == "immediate")


@pytest.mark.parametrize("invalid", ["topology", "version"])
async def test_publication_refuses_unsupported_interaction(interaction_runtime, invalid):
    runtime = interaction_runtime
    graph = sample_graph()
    if invalid == "topology":
        graph["edges"].pop()
    else:
        params = graph["nodes"][1]["data"]["group_params"][0]["params"]
        next(param for param in params if param["key"] == "agent_ref")["value"]["agent_id"] = "mock:echo"
    with tenant_execution_scope(7):
        runtime.repo.save_version(1, data=graph)
        with pytest.raises(PlatformAgentConfigurationError):
            await runtime.service.publish(runtime.publisher, FLOW_ID, 1)


async def test_wait_commit_failure_never_notifies_or_runs_downstream(interaction_runtime, monkeypatch):
    runtime = interaction_runtime

    def fail_wait(*_args):
        raise PlatformAgentExecutionError()

    monkeypatch.setattr(runtime.repo, "save_long_wait", fail_wait, raising=False)
    with tenant_execution_scope(7):
        execution, dispatch_id = await prepare(runtime, sample_graph())
    with pytest.raises(PlatformAgentExecutionError):
        await asyncio.to_thread(run_worker, execution, dispatch_id)
    with tenant_execution_scope(7):
        saved = runtime.repo.get_execution(execution["execution_id"])
    assert saved["state"] == "FAILED"
    assert not any(event.get("interaction_pending") for event in runtime.events)
    assert not runtime.outputs and SESSION not in tasks._global_workflow


async def test_4c_admission_requires_browser_context_and_current_publication(interaction_runtime):
    runtime = interaction_runtime
    with tenant_execution_scope(7):
        runtime.repo.save_version(1, data=sample_graph())
        published = await runtime.service.publish(runtime.publisher, FLOW_ID, 1)
        with pytest.raises(PlatformAgentConfigurationError):
            await runtime.service.admit(runtime.user, FLOW_ID, SESSION, published, "PUBLISHED")
        runtime.repo.save_version(1, data=sample_graph("v2"), allow_online=True)
        with pytest.raises(PlatformAgentPublicationError):
            await runtime.service.admit(
                runtime.user, FLOW_ID, SESSION, published, "PUBLISHED", interaction_session=True
            )
