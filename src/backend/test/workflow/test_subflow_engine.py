"""F086 T12: engine pre-scan, context pass-through and the failed-log hook.

覆盖 AC: AC-14、AC-17
"""

import pytest

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.graph.graph_engine import GraphEngine, scan_referenced_outputs
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.graph.workflow import Workflow
from bisheng.workflow.nodes.base import BaseNode


def _node(node_id: str, node_type: str, params: list[dict] | None = None, v: int = 1) -> dict:
    return {
        "id": node_id,
        "data": {
            "id": node_id,
            "type": node_type,
            "name": node_id,
            "v": v,
            "group_params": [{"name": "", "params": params or []}],
        },
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "sourceHandle": "right_handle",
        "target": target,
        "targetHandle": "left_handle",
    }


def _start() -> dict:
    return _node(
        "start_1",
        "start",
        [
            {"key": "guide_word", "value": ""},
            {"key": "guide_question", "value": []},
            {"key": "preset_question", "value": []},
            {"key": "custom_variables", "value": []},
        ],
    )


class TestScanReferencedOutputs:
    def test_all_reference_shapes_are_found(self):
        nodes = [
            _node("subflow_ab", "subflow", [{"key": "subflow_outputs", "value": [{"key": "never_counted"}]}]),
            _node(
                "code_1",
                "code",
                [{"key": "code_input", "value": [{"key": "x", "type": "ref", "value": "subflow_ab.answer"}]}],
            ),
            _node(
                "code_2",
                "code",
                [{"key": "code_input", "value": [{"key": "y", "type": "ref", "value": "subflow_ab.items#0"}]}],
            ),
            _node(
                "output_1",
                "output",
                [{"key": "output_msg", "value": {"msg": "Hi {{#subflow_ab.summary#}} !", "files": []}}],
            ),
        ]
        assert scan_referenced_outputs(nodes) == {"subflow_ab": ["answer", "items", "summary"]}

    def test_ids_that_only_end_with_the_subflow_id_are_not_matched(self):
        nodes = [
            _node("subflow_ab", "subflow"),
            _node("xsubflow_ab", "code"),
            _node(
                "code_1",
                "code",
                [{"key": "code_input", "value": [{"key": "x", "type": "ref", "value": "xsubflow_ab.answer"}]}],
            ),
            _node(
                "code_2",
                "code",
                [{"key": "code_input", "value": [{"key": "x", "type": "ref", "value": "subflow_abc.answer"}]}],
            ),
        ]
        assert scan_referenced_outputs(nodes) == {"subflow_ab": []}

    def test_duplicates_are_listed_once_and_non_subflow_nodes_are_skipped(self):
        nodes = [
            _node("subflow_1", "subflow"),
            _node("subflow_2", "subflow"),
            _node(
                "llm_1",
                "llm",
                [{"key": "user_prompt", "value": "{{#subflow_1.a#}} {{#subflow_1.a#}} {{#subflow_2.b#}}"}],
            ),
        ]
        assert scan_referenced_outputs(nodes) == {"subflow_1": ["a"], "subflow_2": ["b"]}

    def test_no_subflow_nodes_gives_empty_map(self):
        assert scan_referenced_outputs([_start(), {}, {"data": None}]) == {}


class _Spy(BaseNode):
    """Node that records the kwargs the engine passed in."""

    seen: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _Spy.seen[self.id] = {
            "subflow_depth": self.subflow_depth,
            "start_node_id": self.start_node_id,
            "referenced_outputs": kwargs.get("referenced_outputs"),
        }

    def _run(self, unique_id: str):
        return None


@pytest.fixture
def spy_subflow(monkeypatch):
    from bisheng.workflow.nodes import node_manage

    _Spy.seen = {}
    monkeypatch.setitem(node_manage.NODE_CLASS_MAP, "subflow", _Spy)
    monkeypatch.setitem(node_manage.NODE_CLASS_MAP, "code", _Spy)
    yield _Spy.seen


def _flow() -> dict:
    return {
        "nodes": [
            _start(),
            _node("subflow_1", "subflow"),
            _node(
                "code_1",
                "code",
                [{"key": "code_input", "value": [{"key": "x", "type": "ref", "value": "subflow_1.answer"}]}],
            ),
            _node("end_1", "end"),
        ],
        "edges": [_edge("start_1", "subflow_1"), _edge("subflow_1", "code_1"), _edge("code_1", "end_1")],
    }


def test_engine_passes_depth_start_id_and_referenced_outputs(spy_subflow):
    engine = GraphEngine(
        user_id=0, workflow_id="wf", workflow_data=_flow(), max_steps=5, callback=BaseCallback(), subflow_depth=1
    )
    assert spy_subflow["subflow_1"] == {
        "subflow_depth": 1,
        "start_node_id": "start_1",
        "referenced_outputs": ["answer"],
    }
    assert spy_subflow["code_1"]["referenced_outputs"] is None
    assert engine.nodes_map["end_1"].subflow_depth == 1
    assert engine.start_node_id == "start_1"


def test_depth_defaults_to_zero_and_workflow_forwards_it(spy_subflow):
    GraphEngine(user_id=0, workflow_id="wf", workflow_data=_flow(), max_steps=5, callback=BaseCallback())
    assert spy_subflow["subflow_1"]["subflow_depth"] == 0

    workflow = Workflow("wf", user_id=0, workflow_data=_flow(), max_steps=5, callback=BaseCallback(), subflow_depth=1)
    assert workflow.graph_engine.subflow_depth == 1


class _Recorder(BaseCallback):
    def __init__(self):
        super().__init__()
        self.ends = []

    def on_node_end(self, data):
        self.ends.append(data)


class _Failing(BaseNode):
    def _run(self, unique_id: str):
        raise ValueError("boom")


class _FailingWithLog(_Failing):
    def parse_failed_log(self, unique_id: str):
        return [[{"key": "why", "value": unique_id, "type": "params"}]]


def _bare(cls, callback):
    return cls(
        node_data=BaseNodeData(id="n1", type="code", name="N"),
        workflow_id="wf",
        user_id=0,
        graph_state=GraphState(),
        target_edges=[],
        max_steps=5,
        callback=callback,
    )


def test_failed_run_uses_parse_failed_log_default_none():
    callback = _Recorder()
    with pytest.raises(ValueError):
        _bare(_Failing, callback).run({})
    assert callback.ends[0].reason == "boom"
    assert callback.ends[0].log_data is None


def test_failed_run_uses_overridden_parse_failed_log():
    callback = _Recorder()
    node = _bare(_FailingWithLog, callback)
    with pytest.raises(ValueError):
        node.run({})
    assert callback.ends[0].log_data == [[{"key": "why", "value": node.exec_unique_id, "type": "params"}]]
