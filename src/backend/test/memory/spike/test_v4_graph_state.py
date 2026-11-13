"""F132 V4 spike (T005): can a workflow node read ``chat_id`` and a read-only
memory switch from ``graph_state``?

Experimental code. Delete after Wave 10 (see tasks.md T005).

Findings encoded here:
1. ``GraphState`` is a pydantic model without ``extra='allow'``; an undeclared
   attribute cannot be attached at runtime, so the fields must be declared.
2. Declared fields with ``frozen=True`` are read-only after construction.
3. ``GraphEngine`` builds ``GraphState()`` in ``__init__`` *before*
   ``build_nodes``; every node gets the same object, so a value set at
   construction is visible from ``_run``.
4. ``BaseNodeData.get_variable_info`` already reads a start-node param out of
   ``flow_version.data``.
"""

from typing import Any

import pytest
from pydantic import Field, ValidationError

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.graph import graph_engine as graph_engine_module
from bisheng.workflow.graph.graph_engine import GraphEngine
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes import node_manage
from bisheng.workflow.nodes.base import BaseNode

FAKE_TYPE = "memory_spike_fake"


class SpikeGraphState(GraphState):
    """What the real change would add to GraphState."""

    chat_id: str = Field(default="", frozen=True)
    memory_enabled: bool = Field(default=False, frozen=True)


class FakeMemoryNode(BaseNode):
    seen: dict[str, Any] = {}

    def _run(self, unique_id: str) -> dict[str, Any]:
        FakeMemoryNode.seen = {
            "chat_id": self.graph_state.chat_id,
            "memory_enabled": self.graph_state.memory_enabled,
        }
        return {"retrieved_result": []}


def _start_node(memory_enabled: bool | None) -> dict:
    params = [
        {"key": "guide_word", "value": ""},
        {"key": "guide_question", "value": []},
    ]
    global_params = [
        {"key": "chat_history", "value": 10},
        {"key": "preset_question", "value": []},
        {"key": "custom_variables", "value": []},
    ]
    if memory_enabled is not None:
        global_params.append({"key": "memory_enabled", "value": memory_enabled, "type": "switch"})
    return {
        "id": "start_1",
        "data": {
            "id": "start_1",
            "type": "start",
            "name": "start",
            "v": "3",
            "group_params": [
                {"name": "guide", "params": params},
                {"name": "global", "params": global_params},
            ],
        },
    }


def _workflow_data(memory_enabled: bool | None = True) -> dict:
    return {
        "nodes": [
            _start_node(memory_enabled),
            {"id": "fake_1", "data": {"id": "fake_1", "type": FAKE_TYPE, "name": "fake", "group_params": []}},
            {"id": "end_1", "data": {"id": "end_1", "type": "end", "name": "end", "group_params": []}},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "start_1",
                "sourceHandle": "right_handle",
                "target": "fake_1",
                "targetHandle": "left_handle",
            },
            {
                "id": "e2",
                "source": "fake_1",
                "sourceHandle": "right_handle",
                "target": "end_1",
                "targetHandle": "left_handle",
            },
        ],
    }


def read_start_param(flow_data: dict, key: str) -> Any:
    """Existing-method path: flow_version.data -> start node -> param value."""
    for node in flow_data.get("nodes", []):
        node_data = BaseNodeData(**node.get("data", {}))
        if node_data.type != "start" or not node_data.group_params:
            continue
        info = node_data.get_variable_info(key)
        return info.value if info else None
    return None


@pytest.fixture
def fake_node_registered(monkeypatch):
    monkeypatch.setitem(node_manage.NODE_CLASS_MAP, FAKE_TYPE, FakeMemoryNode)
    FakeMemoryNode.seen = {}


def test_graph_state_rejects_undeclared_attribute():
    state = GraphState()
    with pytest.raises(ValueError):
        state.chat_id = "c1"  # type: ignore[attr-defined]


def test_frozen_field_is_read_only():
    state = SpikeGraphState(chat_id="c1", memory_enabled=True)
    with pytest.raises(ValidationError):
        state.chat_id = "other"


@pytest.mark.parametrize(
    ("chat_id", "memory_enabled"),
    [("chat-abc", True), ("", False)],  # second row = evaluation / canvas debug run
)
def test_node_reads_chat_id_and_switch_from_graph_state(fake_node_registered, monkeypatch, chat_id, memory_enabled):
    # Simulates GraphEngine.__init__(chat_id=..., memory_enabled=...) building
    # GraphState(chat_id=..., memory_enabled=...) at graph_engine.py:69.
    monkeypatch.setattr(
        graph_engine_module,
        "GraphState",
        lambda: SpikeGraphState(chat_id=chat_id, memory_enabled=memory_enabled),
    )
    engine = GraphEngine(
        user_id=None,
        workflow_id="flow-1",
        workflow_name="spike",
        workflow_data=_workflow_data(),
        async_mode=False,
        max_steps=10,
        callback=BaseCallback(),
    )
    engine.run()

    assert engine.status == "SUCCESS", engine.reason
    assert FakeMemoryNode.seen == {"chat_id": chat_id, "memory_enabled": memory_enabled}
    # every node shares the same GraphState object
    assert engine.nodes_map["fake_1"].graph_state is engine.graph_state


def test_read_start_param_from_flow_version_data():
    assert read_start_param(_workflow_data(True), "memory_enabled") is True
    assert read_start_param(_workflow_data(False), "memory_enabled") is False
    # old flows without the param -> None -> treated as off
    assert read_start_param(_workflow_data(None), "memory_enabled") is None
