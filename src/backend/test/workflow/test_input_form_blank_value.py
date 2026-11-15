"""A blank form field must not pass its display name downstream."""

from unittest.mock import MagicMock

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeGroupParams, NodeParams
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.input.input import InputNode


def _form_node() -> InputNode:
    node_data = BaseNodeData(
        id="input_1",
        type="input",
        name="输入",
        v=2,
        tab={"value": "form_input"},
        group_params=[
            NodeGroupParams(
                params=[
                    NodeParams(
                        key="form_input",
                        value=[
                            {"key": "category", "type": "select", "value": "姓名"},
                            {"key": "category2", "type": "select", "value": "性别"},
                            {"key": "text_input", "type": "text", "value": "年级"},
                            {
                                "key": "upload",
                                "type": "file",
                                "value": "附件",
                                "file_type": "file",
                                "file_parse_mode": ["keep_raw"],
                                "file_path": "file_path",
                                "file_content": "file_content",
                                "image_file": "image_file",
                            },
                        ],
                    )
                ]
            )
        ],
    )
    return InputNode(
        node_data=node_data,
        workflow_id="wf",
        user_id=1,
        graph_state=GraphState(),
        target_edges=[],
        max_steps=10,
        callback=BaseCallback(),
    )


def test_unfilled_form_fields_start_empty():
    node = _form_node()

    assert node.node_params["category"] == ""
    assert node.node_params["category2"] == ""
    assert node.node_params["text_input"] == ""
    assert node._file_key_map["upload"]["value"] == "附件"
    assert list(node.node_params.values()).count([]) == 1


def test_partial_submit_keeps_blank_fields_empty():
    node = _form_node()
    node.graph_state = MagicMock()
    node.handle_input({"category": "张三"})

    result = node._run("run-1")

    assert result["category"] == "张三"
    assert result["category2"] == ""
    assert result["text_input"] == ""
    assert result["file_path"] == []
