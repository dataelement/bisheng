"""覆盖 AC: AC-04, AC-09, AC-11, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.errcode.flow import PlatformAgentError
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.domain.schemas.platform_agent import VerifiedAgentActor
from bisheng.workflow.domain.services import platform_agent_service as domain
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.platform_agent.platform_agent import PlatformAgentNode


def node_data(version="v1"):
    return {
        "id": "platform_agent_1",
        "type": "platform_agent",
        "name": "fixture",
        "group_params": [
            {
                "name": "",
                "params": [
                    {
                        "key": "agent_ref",
                        "value": {
                            "agent_id": "mock:scenario" if version != "v1" else "mock:echo",
                            "version_id": version,
                        },
                    },
                    {
                        "key": "input_bindings",
                        "value": {
                            "query": {"source": "constant", "value": "hello"},
                            "value": {"source": "variable", "variable": "start.value"},
                        },
                    },
                ],
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "version,success",
    [
        ("v1", True),
        ("bad-output", False),
        ("running", False),
        ("version-mismatch", False),
        ("timeout", False),
        ("upstream-error", False),
    ],
)
async def test_node_outputs_only_after_a_valid_synchronous_result(agent_store, monkeypatch, version, success):
    repo, _, _, _ = agent_store
    # 节点预算使用实际墙钟。仓储其他测试使用确定性时钟。
    import time

    repo.clock = time.time
    config = PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"}, invoke_timeout_seconds=0.05)
    service = domain.PlatformAgentService(config=config, repository=repo)
    provider = service.provider
    invoke = AsyncMock(wraps=provider.invoke)
    monkeypatch.setattr(provider, "invoke", invoke)
    service._provider = provider
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    graph = {"nodes": [{"data": node_data(version)}], "edges": []}
    execution, dispatch_id = repo.prepare_execution(
        "f" * 32, "node-session", VerifiedAgentActor(12, 7), graph, config, "DEBUG"
    )
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    state = GraphState(variables_pool={"start": {"value": False}})
    callback = Mock()
    node = PlatformAgentNode(
        node_data=BaseNodeData(**node_data(version)),
        workflow_id="f" * 32,
        user_id=12,
        graph_state=state,
        target_edges=[],
        max_steps=10,
        callback=callback,
        tenant_id=7,
        platform_agent_context={
            "service": service,
            "login_user": SimpleNamespace(user_id=12, tenant_id=7),
            "dispatch": dispatch,
        },
    )
    assert repo.get_execution(dispatch.execution_id)["calls"] == {}
    if success:
        await node.arun({})
        assert state.variables_pool[node.id]["result"] == {"answer": "hello", "viewer": "B", "value": False}
        assert repo.get_execution(dispatch.execution_id)["calls"][f"{node.id}:0"]["state"] == "SUCCEEDED"
    else:
        with pytest.raises(PlatformAgentError):
            await node.arun({})
        assert node.id not in state.variables_pool
    assert callback.on_node_start.call_count == callback.on_node_end.call_count == 1
    assert "secret-probe" not in str(callback.mock_calls)
    assert invoke.await_count == 1
    if not success:
        with pytest.raises(PlatformAgentError):
            await node.arun({})
        assert invoke.await_count == 1


@pytest.mark.asyncio
async def test_late_result_after_stop_never_enters_variables_or_success_log(agent_store, monkeypatch):
    import time

    repo, _, _, _ = agent_store
    repo.clock = time.time
    config = PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"})
    service = domain.PlatformAgentService(config=config, repository=repo)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    graph = {"nodes": [{"data": node_data()}], "edges": []}
    execution, dispatch_id = repo.prepare_execution("f" * 32, "late", VerifiedAgentActor(12, 7), graph, config, "DEBUG")
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    provider = service.provider
    invoke = provider.invoke

    async def stopped_result(*args):
        output = await invoke(*args)
        repo.request_stop(dispatch.execution_id)
        return output

    monkeypatch.setattr(provider, "invoke", stopped_result)
    service._provider = provider
    callback = Mock()
    state = GraphState(variables_pool={"start": {"value": None}})
    node = PlatformAgentNode(
        node_data=BaseNodeData(**node_data()),
        workflow_id="f" * 32,
        user_id=12,
        graph_state=state,
        target_edges=[],
        max_steps=10,
        callback=callback,
        platform_agent_context={
            "service": service,
            "login_user": SimpleNamespace(user_id=12, tenant_id=7),
            "dispatch": dispatch,
        },
    )
    with pytest.raises(PlatformAgentError):
        await node.arun({})
    assert node.id not in state.variables_pool
    log = callback.on_node_end.call_args.kwargs["data"].log_data
    assert not any(item["key"] == "result" for batch in log for item in batch)
    assert any(item["key"] == "agent_run_id" for batch in log for item in batch)


def test_missing_and_null_variable_have_distinct_results():
    from bisheng.workflow.domain.schemas.platform_agent import MISSING

    node = object.__new__(PlatformAgentNode)
    node.graph_state = GraphState(variables_pool={"start": {"value": None, "object": {"zero": 0}}})
    assert node.lookup("start.value") is None
    assert node.lookup("start.object#zero") == 0
    assert node.lookup("start.missing") is MISSING


@pytest.mark.asyncio
async def test_example_graph_runs_through_the_real_graph_engine(agent_store, monkeypatch):
    import asyncio
    import json
    import time
    from pathlib import Path

    from bisheng.workflow.graph.workflow import Workflow
    from bisheng.workflow.nodes.output import output
    from bisheng.workflow.nodes.start import start

    repo, _, _, _ = agent_store
    repo.clock = time.time
    graph = json.loads(
        (
            Path(__file__).parents[4] / "features/v3.0.0/119-kunlian-platform-agent/mock-workflow.example.json"
        ).read_text()
    )
    monkeypatch.setattr(start.UserDao, "get_user", lambda _: None)
    monkeypatch.setattr(start.UserGroupDao, "get_user_group", lambda _: [])
    monkeypatch.setattr(start.UserRoleDao, "get_user_roles", lambda _: [])
    monkeypatch.setattr(start.UserDepartmentDao, "get_user_primary_department", lambda _: None)
    monkeypatch.setattr(output, "get_minio_storage_sync", lambda: Mock())
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    service = domain.PlatformAgentService(config=PlatformAgentConf(), repository=repo)
    execution, dispatch_id = await service.admit(
        SimpleNamespace(user_id=12, tenant_id=7), "f" * 32, "example", graph, "DEBUG"
    )
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    context = {"service": service, "login_user": SimpleNamespace(user_id=12, tenant_id=7), "dispatch": dispatch}
    callback = Mock()
    workflow = Workflow(
        "f" * 32, "example", 12, graph, max_steps=10, callback=callback, tenant_id=7, platform_agent_context=context
    )
    status, reason = await asyncio.to_thread(workflow.run)
    assert status == "SUCCESS", reason
    assert callback.on_output_msg.call_args.args[0].msg == "F119 Mock / B"
    assert (
        workflow.graph_engine.graph_state.get_variable("platform_agent_example", "result")["value"]["enabled"] is False
    )


@pytest.mark.asyncio
async def test_sql_commit_failure_restores_memory_and_redacts_driver_details(agent_store, monkeypatch):
    import time

    from sqlalchemy.exc import OperationalError

    from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution

    repo, _, _, _ = agent_store
    repo.clock = time.time
    config = PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"})
    service = domain.PlatformAgentService(config=config, repository=repo)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    graph = {"nodes": [{"data": node_data()}], "edges": []}
    execution, dispatch_id = repo.prepare_execution(
        "f" * 32, "commit-fault", VerifiedAgentActor(12, 7), graph, config, "DEBUG"
    )
    dispatch = repo.claim_dispatch(execution["execution_id"], dispatch_id)
    real_commit = repo.sessions.class_.commit

    def reject_output_commit(session):
        if any(
            isinstance(row, PlatformAgentExecution) and any(call["state"] == "SUCCEEDED" for call in row.calls.values())
            for row in session.dirty
        ):
            raise OperationalError("secret-probe", {}, Exception("driver-secret-probe"))
        return real_commit(session)

    monkeypatch.setattr(repo.sessions.class_, "commit", reject_output_commit)
    callback = Mock()
    state = GraphState(variables_pool={"start": {"value": 0}, "platform_agent_1": {"before": True}})
    node = PlatformAgentNode(
        node_data=BaseNodeData(**node_data()),
        workflow_id="f" * 32,
        user_id=12,
        graph_state=state,
        target_edges=[],
        max_steps=10,
        callback=callback,
        platform_agent_context={
            "service": service,
            "login_user": SimpleNamespace(user_id=12, tenant_id=7),
            "dispatch": dispatch,
        },
    )
    with pytest.raises(PlatformAgentError) as failure:
        await node.arun({})
    assert state.variables_pool[node.id] == {"before": True}
    assert repo.get_execution(dispatch.execution_id)["calls"][f"{node.id}:0"]["state"] == "DISPATCHING"
    assert "secret-probe" not in str(failure.value) + str(callback.mock_calls)
