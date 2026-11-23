"""Agent-node KB tools require the same checked author/runtime policy as RAG."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("toggle,identity", [(False, 22), (True, 7)])
def test_agent_only_initializes_authorized_ordinary_kbs(monkeypatch, toggle, identity):
    from bisheng.knowledge.domain.services import workflow_knowledge_authorization as auth
    from bisheng.workflow.nodes.agent.agent import AgentNode

    node = object.__new__(AgentNode)
    node.user_id = 7
    node.flow_user_id = 22
    node.tenant_id = 1
    node._knowledge_type = "knowledge"
    node._knowledge_ids = [11, 99]
    node._knowledge_auth = toggle
    node._llm = object()
    authorizer = Mock(return_value=[11])
    build = Mock(return_value=SimpleNamespace(name="kb11"))
    monkeypatch.setattr(auth, "authorized_knowledge_ids", authorizer)
    monkeypatch.setattr("bisheng.workflow.nodes.agent.agent.ToolExecutor.init_knowledge_tool_sync", build)
    result = node._init_knowledge_tools({})
    authorizer.assert_called_once_with(identity_user_id=identity, tenant_id=1, knowledge_ids=[11, 99])
    assert len(result) == 1
    assert build.call_args.args[1] == 11
    authorizer.return_value = []
    build.reset_mock()
    assert node._init_knowledge_tools({}) == []
    build.assert_not_called()
