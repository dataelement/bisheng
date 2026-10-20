"""F086 T08: the End node returns results only when its return switch is on.

覆盖 AC: AC-19
"""

import pytest

from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.end.end import EndNode


class _RecordingCallback(BaseCallback):
    def __init__(self):
        super().__init__()
        self.ends = []

    def on_node_end(self, data):
        self.ends.append(data)


def _end_node(params: list[dict] | None, state: GraphState | None = None, callback=None) -> EndNode:
    group_params = None if params is None else [{"name": "", "params": params}]
    node_data = BaseNodeData(id="end_1", type="end", name="End", group_params=group_params, v=2)
    return EndNode(
        node_data=node_data,
        workflow_id="wf",
        user_id=1,
        graph_state=state or GraphState(),
        target_edges=[],
        max_steps=10,
        callback=callback or BaseCallback(),
    )


def _state() -> GraphState:
    state = GraphState()
    state.set_variable("llm_1", "output", "hello")
    state.set_variable("code_1", "items", [1, {"a": 2}])
    return state


def _return_params(enabled: bool) -> list[dict]:
    return [
        {"key": "return_enabled", "value": enabled},
        {
            "key": "return_results",
            "value": [
                {"key": "answer", "type": "ref", "value": "llm_1.output"},
                {"key": "items", "type": "ref", "value": "code_1.items"},
            ],
        },
    ]


def test_switch_off_returns_nothing_and_keeps_old_log():
    callback = _RecordingCallback()
    state = _state()
    node = _end_node(_return_params(False), state, callback)
    assert node._run("x") is None
    assert node.parse_log("x", None) == []

    node.run({})
    assert callback.ends[0].log_data == []
    assert callback.ends[0].input_data == {}
    assert "end_1" not in state.variables_pool


def test_legacy_end_node_without_params_behaves_as_switch_off():
    for params in (None, []):
        node = _end_node(params, _state())
        assert node._run("x") is None
        assert node.parse_log("x", None) == []


def test_switch_on_resolves_references_and_keeps_values_as_is():
    callback = _RecordingCallback()
    state = _state()
    node = _end_node(_return_params(True), state, callback)
    node.run({})

    assert state.variables_pool["end_1"] == {"answer": "hello", "items": [1, {"a": 2}]}
    end = callback.ends[0]
    assert end.reason is None
    assert end.log_data == [
        [{"key": "return_results", "value": {"answer": "hello", "items": [1, {"a": 2}]}, "type": "params"}]
    ]
    assert end.input_data == {"llm_1.output": "hello", "code_1.items": [1, {"a": 2}]}


def test_switch_on_with_missing_reference_returns_none_value():
    node = _end_node(
        [
            {"key": "return_enabled", "value": True},
            {"key": "return_results", "value": [{"key": "gone", "type": "ref", "value": "deleted_1.output"}]},
        ],
        _state(),
    )
    assert node._run("x") == {"gone": None}


def test_switch_on_with_empty_list_returns_empty_result():
    node = _end_node([{"key": "return_enabled", "value": True}, {"key": "return_results", "value": []}], _state())
    assert node._run("x") == {}


def test_reference_without_a_variable_fails_with_a_readable_reason():
    params = [
        {"key": "return_enabled", "value": True},
        {"key": "return_results", "value": [{"key": "answer", "type": "ref", "value": ""}]},
    ]
    node = _end_node(params, _state())
    with pytest.raises(IgnoreException, match="return result answer has no variable selected"):
        node._run("x")
