"""覆盖 AC: AC-04, AC-07, AC-08, AC-13, AC-14, AC-15。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.flow import PlatformKnowledgeExecutionError
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.domain.schemas.platform_knowledge import MISSING
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.platform_knowledge_retriever.platform_knowledge_retriever import (
    PlatformKnowledgeRetrieverNode,
)
from test.workflow.test_platform_knowledge_contract import node


def test_stopped_node_discards_tentative_outputs():
    state = GraphState()
    state.variables_pool["retrieve"] = {"retrieved_text": "old"}
    state.variables_pool["input"] = {"question": None}

    async def reject(*_):
        raise PlatformKnowledgeExecutionError()

    run = SimpleNamespace(
        assert_live=lambda: None,
        invoke=AsyncMock(return_value={"retrieved_text": "late"}),
        commit=reject,
        execution_id="fixture",
        service=SimpleNamespace(config=SimpleNamespace(mode="mock", retrieve_timeout_seconds=5)),
    )
    instance = PlatformKnowledgeRetrieverNode(
        BaseNodeData(**{**node(), "name": "Search"}),
        "flow",
        12,
        state,
        [],
        10,
        BaseCallback(),
        platform_knowledge_context=run,
    )
    assert instance.lookup("input.question") is None
    assert instance.lookup("input.missing") is MISSING
    with pytest.raises(PlatformKnowledgeExecutionError):
        instance.run({})
    assert "retrieve" not in state.variables_pool
