"""覆盖 AC: AC-04, AC-07, AC-08, AC-12, AC-18。"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import PlatformKnowledgeConfigurationError, PlatformKnowledgeExecutionError
from bisheng.workflow.application import platform_knowledge
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest
from bisheng.workflow.graph.workflow import Workflow
from test.workflow import test_platform_knowledge_contract as contract

knowledge_service = contract.knowledge_service

EXAMPLE = Path(__file__).parents[4] / "features/v3.0.0/120-kunlian-knowledge-retrieval/mock-workflow.example.json"


def test_mock_example_runs_through_graph_engine(knowledge_service, monkeypatch):
    from bisheng.workflow.nodes.output import output
    from bisheng.workflow.nodes.start import start

    monkeypatch.setattr(output, "get_minio_storage_sync", lambda: None)

    service, _ = knowledge_service
    for owner, name in [
        (start.UserDao, "get_user"),
        (start.UserGroupDao, "get_user_group"),
        (start.UserRoleDao, "get_user_roles"),
        (start.UserDepartmentDao, "get_user_primary_department"),
    ]:
        monkeypatch.setattr(owner, name, lambda *_: None)
    store = SimpleNamespace(check=lambda *_: None, commit=lambda *_: None)
    run = platform_knowledge.KnowledgeRun(
        service,
        store,
        {
            "execution_id": "test-run",
            "workflow_id": "flow",
            "action": "edit",
            "token_version": 2,
            "environment": canonical_digest(service.config.model_dump()),
        },
        "owner",
        SimpleNamespace(user_id=13, tenant_id=7),
    )
    graph = json.loads(EXAMPLE.read_text())
    flow = Workflow("flow", "Mock", 13, graph, False, 10, 10, BaseCallback(), platform_knowledge_context=run)
    assert flow.run()[0] == "INPUT"
    assert flow.run({"input_example": {"question": "轴承温度异常如何处理?"}})[0] == "SUCCESS"
    results = flow.graph_engine.graph_state.variables_pool["platform_knowledge_example"]
    assert results["hit_count"] == 1
    assert "润滑" in results["retrieved_text"]
    assert "润滑" in flow.graph_engine.graph_state.variables_pool["output_example"]["message"]
    assert results["retrieved_result"][0]["metadata"]["document_id"] == "mock:doc-001"


async def test_run_once_uses_node_lifecycle_and_rejects_extra_input(knowledge_service, monkeypatch):
    from bisheng.api.services import workflow as api

    service, _ = knowledge_service
    user = SimpleNamespace(user_id=13, tenant_id=7)
    monkeypatch.setattr(api.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(id="flow", name="Mock", tenant_id=7))
    monkeypatch.setattr(api, "require_business_action", AsyncMock())
    run = platform_knowledge.KnowledgeRun(
        service,
        SimpleNamespace(check=lambda *_: None, commit=lambda *_: None, status=lambda *_: True),
        {
            "execution_id": "test-run",
            "workflow_id": "flow",
            "action": "edit",
            "token_version": 2,
            "environment": canonical_digest(service.config.model_dump()),
        },
        "owner",
        user,
    )
    prepare = AsyncMock(return_value=({}, {}))
    monkeypatch.setattr(platform_knowledge, "prepare_execution", prepare)
    monkeypatch.setattr(platform_knowledge, "claim_execution", lambda *_: run)
    data = {"data": {**contract.node(), "name": "Mock search"}}
    with pytest.raises(PlatformKnowledgeConfigurationError):
        await api.WorkFlowService.run_once(user, {"user_id": 12}, data, "flow")
    prepare.assert_not_awaited()
    logs = await api.WorkFlowService.run_once(user, {}, data, "flow")
    assert any(item["key"].endswith("retrieved_text") and "润滑" in item["value"] for batch in logs for item in batch)
    run.store.status = lambda *_: False
    with pytest.raises(PlatformKnowledgeExecutionError):
        await api.WorkFlowService.run_once(user, {}, data, "flow")
