import asyncio
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import (
    PlatformAgentConfigurationError,
    PlatformAgentExecutionError,
    PlatformAgentPublicationError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.worker.workflow import tasks
from bisheng.workflow.application import platform_agent
from test.workflow.test_platform_agent_interaction_wait import (
    AGENT_ID,
    FLOW_ID,
    SESSION,
    prepare,
    run_worker,
)
from test.workflow.test_platform_agent_interaction_wait import interaction_runtime as interaction_runtime
from test.workflow.test_platform_agent_interaction_wait import long_remote as long_remote

CALL = f"{AGENT_ID}:0"


def resume_graph():
    path = (
        Path(__file__).resolve().parents[4] / "features/v3.0.0/124-kunlian-agent-long-task/mock-workflow.example.json"
    )
    return json.loads(path.read_text())


@pytest.mark.parametrize("lost_response", [False, True])
async def test_start_persists_wait_and_releases_graph(interaction_runtime, monkeypatch, lost_response):
    runtime = interaction_runtime
    monkeypatch.setattr(runtime.service, "enable_long_task_resume", True, raising=False)
    provider = runtime.service.provider
    start = provider.start

    async def accept(*args):
        with tenant_execution_scope(7):
            record = runtime.repo.get_execution(execution["execution_id"])
        assert record["calls"][CALL]["long_task"]["resume"]["snapshot"]["steps"] == {"start_example": 1}
        observation = await start(*args)
        if lost_response:
            raise TimeoutError
        return observation

    monkeypatch.setattr(provider, "start", AsyncMock(side_effect=accept))
    with tenant_execution_scope(7):
        execution, dispatch = await prepare(runtime, resume_graph())
    await asyncio.to_thread(run_worker, execution, dispatch)
    await asyncio.to_thread(run_worker, execution, dispatch)

    with tenant_execution_scope(7):
        saved = runtime.repo.get_execution(execution["execution_id"])
        with pytest.raises(PlatformAgentExecutionError):
            await platform_agent.BrowserPlatformAgentRuntime(runtime.repo).resume(
                runtime.user, FLOW_ID, saved["execution_id"], published=True
            )
    call = saved["calls"][CALL]
    waiting = call["long_task"]["resume"]
    assert saved["state"] == "WAITING"
    assert saved["dispatches"][dispatch]["state"] == "DONE"
    assert saved["dispatches"][dispatch]["workflow_version_id"] == 1
    assert waiting["phase"] == ("START_CHECK" if lost_response else "POLL_WAIT")
    assert bool(call.get("agent_run_id")) is not lost_response
    assert call["deadline"] == 1030 and runtime.now[0] == 1000
    snapshot = waiting["snapshot"]
    assert snapshot["execution_id"] == saved["execution_id"]
    assert snapshot["graph_digest"] == saved["graph_digest"]
    assert snapshot["agent_node"] == AGENT_ID
    assert snapshot["steps"] == {"start_example": 1} and snapshot["variables"]["start_example"]["current_time"]
    assert provider.start.await_count == 1
    assert runtime.starts == ["start_example"] and not runtime.outputs
    assert SESSION not in tasks._global_workflow
    assert "INPUT" not in runtime.statuses
    assert runtime.events[-1]["local_state"] == "WAITING_RESULT"
    assert "snapshot" not in runtime.events[-1]


async def test_wait_persistence_failure_never_starts_downstream(interaction_runtime, monkeypatch):
    runtime = interaction_runtime
    monkeypatch.setattr(runtime.service, "enable_long_task_resume", True, raising=False)
    provider = runtime.service.provider
    monkeypatch.setattr(provider, "start", AsyncMock(wraps=provider.start))

    def fail_wait(*_args):
        raise PlatformAgentExecutionError()

    monkeypatch.setattr(runtime.repo, "save_long_task_resume_wait", fail_wait, raising=False)
    with tenant_execution_scope(7):
        execution, dispatch = await prepare(runtime, resume_graph())
    with pytest.raises(PlatformAgentExecutionError):
        await asyncio.to_thread(run_worker, execution, dispatch)
    with tenant_execution_scope(7):
        saved = runtime.repo.get_execution(execution["execution_id"])
    assert saved["state"] == "FAILED"
    assert provider.start.await_count == 1
    assert runtime.starts == ["start_example"] and not runtime.outputs
    assert not any(event["local_state"] == "WAITING_RESULT" for event in runtime.events)


@pytest.mark.parametrize("invalid", ["topology", "attachment", "publication_changed"])
async def test_resume_admission_refuses_invalid_graph_or_version(interaction_runtime, monkeypatch, invalid):
    runtime = interaction_runtime
    monkeypatch.setattr(runtime.service, "enable_long_task_resume", True, raising=False)
    graph = resume_graph()
    if invalid == "topology":
        graph["edges"].pop()
    elif invalid == "attachment":
        next(p for p in graph["nodes"][2]["data"]["group_params"][0]["params"] if p["key"] == "message")["value"][
            "files"
        ] = [{"path": "test-file"}]
    with tenant_execution_scope(7):
        runtime.repo.save_version(1, data=graph)
        published = await runtime.service.publish(runtime.publisher, FLOW_ID, 1)
        if invalid == "publication_changed":
            changed = deepcopy(graph)
            changed["nodes"][0]["data"]["name"] = "V2"
            runtime.repo.save_version(1, data=changed, allow_online=True)
        error = PlatformAgentPublicationError if invalid == "publication_changed" else PlatformAgentConfigurationError
        with pytest.raises(error):
            await platform_agent.BrowserPlatformAgentRuntime(runtime.repo).prepare(
                runtime.user, FLOW_ID, SESSION, published, published=True
            )


async def test_existing_async_path_runs_through_when_4d_is_disabled(interaction_runtime):
    runtime = interaction_runtime
    with tenant_execution_scope(7):
        execution, dispatch = await prepare(runtime, resume_graph())
    await asyncio.to_thread(run_worker, execution, dispatch)
    with tenant_execution_scope(7):
        saved = runtime.repo.get_execution(execution["execution_id"])
    assert saved["state"] == "SUCCEEDED"
    assert "resume" not in saved["calls"][CALL]["long_task"]
    assert runtime.starts.count(AGENT_ID) == len(runtime.outputs) == 1
