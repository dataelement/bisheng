"""覆盖 AC: AC-01, AC-02, AC-04, AC-05, AC-07, AC-08, AC-11, AC-12, AC-13, AC-16, AC-17。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import (
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgeNotReadyError,
    PlatformKnowledgePermissionError,
    PlatformKnowledgeTimeoutError,
)
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.config.settings import PlatformKnowledgeConf
from bisheng.workflow.domain.services import platform_knowledge_service as domain


@pytest.fixture
def knowledge_service(monkeypatch):
    repo = SimpleNamespace(get_workflow=lambda _: {"tenant_id": 7, "flow_type": 10})
    facts = {user: {"state": "active", "tenant_id": 7, "token_version": 2} for user in (12, 13)}
    auth = AsyncMock()
    monkeypatch.setattr(domain, "require_business_action", auth)
    service = domain.PlatformKnowledgeService(
        config=PlatformKnowledgeConf(mock_subjects={"7:12": "A", "7:13": "B"}),
        repository=repo,
        identity_reader=AsyncMock(return_value=facts),
    )
    return service, auth


def node(question=None, resource="mock:maintenance", top_k=5):
    return {
        "id": "retrieve",
        "type": "platform_knowledge_retriever",
        "group_params": [
            {
                "params": [
                    {"key": "knowledge", "value": {"resource_id": resource}},
                    {"key": "user_question", "value": question or {"source": "constant", "value": "轴承温度"}},
                    {"key": "top_k", "value": top_k},
                    {
                        "key": "retrieved_result",
                        "value": [
                            {"key": key} for key in ("retrieved_result", "retrieved_text", "citations", "hit_count")
                        ],
                    },
                ]
            }
        ],
    }


async def test_permission_and_source_are_bound_to_actual_actor(knowledge_service):
    service, auth = knowledge_service
    a = SimpleNamespace(user_id=12, tenant_id=7)
    b = SimpleNamespace(user_id=13, tenant_id=7)
    actor_a = await service.authorize(a, "flow", "publish")
    actor_b = await service.authorize(b, "flow", "use")
    result_a = await service.retrieve(actor_a, node(), lambda _: None)
    result_b = await service.retrieve(actor_b, node(), lambda _: None)
    assert result_a["hit_count"] > result_b["hit_count"] == 1
    assert result_b["citations"][0]["document_id"] == "mock:doc-001"
    assert auth.await_args.kwargs["action"] == "use"
    with pytest.raises(PlatformKnowledgePermissionError):
        await service.retrieve(actor_b, node(resource="mock:private"), lambda _: None)
    with pytest.raises(UnAuthorizedError):
        await service.authorize(SimpleNamespace(user_id=13, tenant_id=8), "flow")


async def test_blank_variable_skips_provider_retrieve(knowledge_service, monkeypatch):
    service, _ = knowledge_service
    actor = await service.authorize(SimpleNamespace(user_id=13, tenant_id=7), "flow")
    service._provider = service.provider
    retrieve = AsyncMock()
    monkeypatch.setattr(service._provider, "retrieve", retrieve)
    data = node({"source": "variable", "variable": "input.question"})
    assert (await service.retrieve(actor, data, lambda _: None))["retrieved_result"] == []
    retrieve.assert_not_awaited()
    with pytest.raises(PlatformKnowledgeConfigurationError):
        await service.retrieve(actor, data, lambda _: domain.MISSING)
    with pytest.raises(PlatformKnowledgeConfigurationError):
        await service.retrieve(actor, node(top_k=True), lambda _: None)


async def test_graph_validation_requires_upstream_question_source(knowledge_service, monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.config.settings import WorkflowConf

    monkeypatch.setattr(type(settings), "get_workflow_conf", lambda _: WorkflowConf())
    service, _ = knowledge_service
    user = SimpleNamespace(user_id=13, tenant_id=7)
    source = {
        "id": "input",
        "type": "input",
        "group_params": [{"params": [{"key": "question", "global": True}]}],
    }
    graph = {
        "nodes": [
            {"data": source},
            {"data": {"id": "middle"}},
            {"data": node({"source": "variable", "variable": "input.question"})},
        ],
        "edges": [{"source": "middle", "target": "retrieve"}],
    }
    result = await service.validate_graph(user, "flow", graph, action="publish")
    assert not result["valid"]
    assert result["issues"][0]["node_id"] == "retrieve"
    graph["edges"].append({"source": "input", "target": "middle"})
    assert (await service.validate_graph(user, "flow", graph, action="publish"))["valid"]


@pytest.mark.parametrize("mode", ["disabled", "real"])
async def test_unready_modes_never_offer_mock(mode, knowledge_service):
    service, _ = knowledge_service
    service.config = PlatformKnowledgeConf(mode=mode)
    with pytest.raises(PlatformKnowledgeNotReadyError):
        await service.list_knowledge(SimpleNamespace(user_id=13, tenant_id=7), "flow")


async def test_timeout_reaches_public_contract(knowledge_service):
    service, _ = knowledge_service
    service.config = service.config.model_copy(update={"retrieve_timeout_seconds": 0.01})
    actor = await service.authorize(SimpleNamespace(user_id=13, tenant_id=7), "flow")
    with pytest.raises(PlatformKnowledgeTimeoutError):
        await service.retrieve(actor, node(resource="mock:timeout"), lambda _: None)


async def test_no_hit_and_bad_source_are_different_outcomes(knowledge_service):
    from bisheng.common.errcode.flow import PlatformKnowledgeOutputError

    service, _ = knowledge_service
    actor = await service.authorize(SimpleNamespace(user_id=13, tenant_id=7), "flow")
    empty = await service.retrieve(actor, node({"source": "constant", "value": "unmatched"}), lambda _: None)
    assert empty == {"retrieved_result": [], "retrieved_text": "", "citations": [], "hit_count": 0}
    with pytest.raises(PlatformKnowledgeOutputError):
        await service.retrieve(actor, node(resource="mock:invalid"), lambda _: None)
