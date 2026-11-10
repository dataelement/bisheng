"""覆盖 AC: AC-03, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-22。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.workflow import WorkFlowService
from bisheng.core.config.settings import PlatformAgentConf
from bisheng.workflow.application import platform_agent
from bisheng.workflow.domain.services import platform_agent_service as domain
from test.workflow.test_platform_agent_node import node_data


@pytest.mark.asyncio
async def test_run_once_commits_result_and_records_actual_user(agent_store, monkeypatch):
    import time

    from bisheng.api.services import workflow as bridge

    repo, _, _, _ = agent_store
    repo.clock = time.time
    config = PlatformAgentConf(mode="mock", mock_subjects={"7:12": "B"})
    service = domain.PlatformAgentService(config=config, repository=repo)
    monkeypatch.setattr(platform_agent, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    monkeypatch.setattr(bridge, "require_business_action", AsyncMock())
    monkeypatch.setattr(
        bridge.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(id="f" * 32, name="fixture", tenant_id=7)
    )
    log = await WorkFlowService.run_once(
        SimpleNamespace(user_id=12, tenant_id=7), {"start.value": 0}, {"data": node_data()}, "f" * 32
    )
    result = next(item["value"] for batch in log for item in batch if item["key"] == "result")
    assert result == {"answer": "hello", "viewer": "B", "value": 0}
    from sqlmodel import select

    from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution

    with repo.sessions() as session:
        execution = session.exec(select(PlatformAgentExecution)).one()
        assert execution.state == "SUCCEEDED" and execution.user_id == 12


@pytest.mark.asyncio
async def test_publish_uses_atomic_repository_instead_of_legacy_dao(agent_store, monkeypatch):
    from bisheng.api.services import workflow as bridge

    repo, sessions, _, _ = agent_store
    from bisheng.database.models.flow_version import FlowVersion

    graph = {"nodes": [{"data": node_data()}], "edges": []}
    graph["nodes"][0]["data"]["group_params"][0]["params"][1]["value"]["value"] = {"source": "constant", "value": None}
    with sessions() as session:
        version = session.get(FlowVersion, 1)
        version.data = graph
        session.add(version)
        session.commit()
    service = domain.PlatformAgentService(
        config=PlatformAgentConf(mode="mock", mock_subjects={"7:11": "A"}), repository=repo
    )
    monkeypatch.setattr(platform_agent, "get_service", lambda: service)
    monkeypatch.setattr(domain, "require_business_action", AsyncMock())
    monkeypatch.setattr(bridge, "require_business_action", AsyncMock())
    monkeypatch.setattr(
        bridge.FlowDao,
        "aget_flow_by_id",
        AsyncMock(return_value=SimpleNamespace(id="f" * 32, name="fixture", data=None)),
    )
    monkeypatch.setattr(
        bridge.FlowVersionDao,
        "aget_version_by_id",
        AsyncMock(return_value=SimpleNamespace(id=1, flow_id="f" * 32, data=graph)),
    )
    monkeypatch.setattr(bridge, "Workflow", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge.telemetry_service, "log_event", AsyncMock())
    legacy = AsyncMock(side_effect=AssertionError("must publish atomically"))
    monkeypatch.setattr(bridge.FlowVersionDao, "change_current_version", legacy)
    await WorkFlowService.update_flow_status(SimpleNamespace(user_id=11, tenant_id=7), "f" * 32, 1, 2)
    assert repo.get_workflow("f" * 32)["data"]["_platform_agent_publication"]["provider_mode"] == "mock"
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_version_save_switch_and_delete_keep_the_last_published_graph(agent_store, monkeypatch):
    from bisheng.api.services import flow as bridge
    from bisheng.api.v1.schemas import FlowVersionCreate
    from bisheng.database.models.flow import Flow
    from bisheng.database.models.flow_version import FlowVersion

    repo, sessions, graph, _ = agent_store
    published = {**graph, "_platform_agent_publication": {"nodes": {"old": {}}}}
    with sessions() as session:
        flow = session.get(Flow, "f" * 32)
        flow.data = published
        session.add(flow)
        session.add(FlowVersion(id=2, flow_id="f" * 32, name="v2", user_id=11, tenant_id=7, data=graph))
        session.commit()
    service = domain.PlatformAgentService(config=PlatformAgentConf(mode="mock"), repository=repo)
    monkeypatch.setattr(platform_agent, "get_service", lambda: service)
    monkeypatch.setattr(bridge.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(bridge.telemetry_service, "log_event_sync", lambda **kwargs: None)
    monkeypatch.setattr(
        bridge.FlowService,
        "judge_flow_write_permission",
        AsyncMock(side_effect=lambda *args: SimpleNamespace(**repo.get_workflow("f" * 32))),
    )
    monkeypatch.setattr(bridge.FlowService, "update_flow_hook", AsyncMock())
    monkeypatch.setattr(bridge, "require_business_action", AsyncMock())
    monkeypatch.setattr(bridge.FlowDao, "get_flow_by_id", lambda ident: SimpleNamespace(**repo.get_workflow(ident)))
    monkeypatch.setattr(
        bridge.FlowVersionDao,
        "aget_version_by_id",
        AsyncMock(side_effect=lambda ident, **kwargs: SimpleNamespace(**repo.get_version(ident))),
    )
    monkeypatch.setattr(
        bridge.FlowVersionDao, "get_version_by_id", lambda ident: SimpleNamespace(**repo.get_version(ident))
    )
    user = SimpleNamespace(user_id=11, tenant_id=7)
    await bridge.FlowService.update_version_info(None, user, 1, FlowVersionCreate(data={**graph, "draft": True}))
    assert repo.get_version(1)["data"]["draft"] is True
    assert repo.get_workflow("f" * 32)["data"] == published
    await bridge.FlowService.change_current_version(None, user, "f" * 32, 2)
    assert repo.get_version(2)["is_current"] == 1
    await bridge.FlowService.delete_version(user, 1)
    assert repo.get_workflow("f" * 32)["data"] == published
