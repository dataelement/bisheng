"""F086: decide from raw workflow data whether it can run as a subflow.

The candidate list, the online check, the save warning and the subflow node
all call ``inspect_flow_data`` so that they agree on one rule set. The
function reads only the JSON it is given and never touches the database.
"""

from dataclasses import dataclass, field
from typing import Any

from bisheng.workflow.common.node import NodeType

# Output node interaction types that pause the run for the user.
INTERACTIVE_OUTPUT_TYPES = ("input", "choose")

# GraphState.get_variable returns the chat history for this key, so an End
# node return value with this name could never be read back.
RESERVED_OUTPUT_NAMES = ("chat_history",)

REASON_INPUT_NODE = "input_node"
REASON_INTERACTIVE_OUTPUT_NODE = "interactive_output_node"
REASON_SUBFLOW_NODE = "subflow_node"
REASON_INVALID_OUTPUT_NAME = "invalid_output_name"


@dataclass
class FlowInspection:
    input_nodes: list[dict] = field(default_factory=list)
    interactive_output_nodes: list[dict] = field(default_factory=list)
    subflow_nodes: list[dict] = field(default_factory=list)
    # Workflows referenced by the subflow nodes, first occurrence order.
    subflow_ids: list[str] = field(default_factory=list)
    # Workflow name as stored in the node that references it, by workflow id.
    subflow_names: dict[str, str] = field(default_factory=dict)
    # Start node custom variables: [{name, value}].
    inputs: list[dict] = field(default_factory=list)
    # Return names of every End node whose return switch is on.
    outputs: list[str] = field(default_factory=list)
    invalid_output_names: list[str] = field(default_factory=list)

    @property
    def forbidden_nodes(self) -> list[dict]:
        return self.input_nodes + self.interactive_output_nodes + self.subflow_nodes

    @property
    def ineligible_reasons(self) -> list[str]:
        reasons = []
        if self.input_nodes:
            reasons.append(REASON_INPUT_NODE)
        if self.interactive_output_nodes:
            reasons.append(REASON_INTERACTIVE_OUTPUT_NODE)
        if self.subflow_nodes:
            reasons.append(REASON_SUBFLOW_NODE)
        if self.invalid_output_names:
            reasons.append(REASON_INVALID_OUTPUT_NAME)
        return reasons

    @property
    def eligible(self) -> bool:
        return not self.ineligible_reasons


def node_params(node_data: dict) -> dict[str, Any]:
    """Flatten ``group_params`` into ``{key: value}`` the way BaseNode.init_data does."""
    params = {}
    for group in node_data.get("group_params") or []:
        for param in (group or {}).get("params") or []:
            if isinstance(param, dict) and param.get("key"):
                params[param["key"]] = param.get("value")
    return params


def is_interactive_output(params: dict[str, Any]) -> bool:
    output_result = params.get("output_result")
    return isinstance(output_result, dict) and output_result.get("type") in INTERACTIVE_OUTPUT_TYPES


def end_node_return_names(params: dict[str, Any]) -> list[str]:
    """Return names configured on one End node; empty when the switch is off or absent."""
    if params.get("return_enabled") is not True:
        return []
    names = []
    for one in params.get("return_results") or []:
        if isinstance(one, dict) and one.get("key"):
            names.append(one["key"])
    return names


def inspect_flow_data(data: dict | None) -> FlowInspection:
    result = FlowInspection()
    if not isinstance(data, dict):
        return result

    for node in data.get("nodes") or []:
        node_data = (node or {}).get("data") or {}
        node_type = node_data.get("type")
        if not node_type or node_type == NodeType.NOTE.value:
            continue
        params = node_params(node_data)
        brief = {"id": node_data.get("id") or node.get("id"), "name": node_data.get("name") or "", "type": node_type}

        if node_type == NodeType.START.value:
            for one in params.get("custom_variables") or []:
                if isinstance(one, dict) and one.get("label"):
                    result.inputs.append({"name": one["label"], "value": one.get("value")})
        elif node_type == NodeType.INPUT.value:
            result.input_nodes.append(brief)
        elif node_type == NodeType.OUTPUT.value:
            if is_interactive_output(params):
                result.interactive_output_nodes.append(brief)
        elif node_type == NodeType.SUBFLOW.value:
            result.subflow_nodes.append(brief)
            subflow = params.get("subflow_id")
            flow_id = subflow.get("id") if isinstance(subflow, dict) else None
            if flow_id and flow_id not in result.subflow_ids:
                result.subflow_ids.append(flow_id)
                result.subflow_names[flow_id] = subflow.get("name") or brief["name"]
        elif node_type == NodeType.END.value:
            for name in end_node_return_names(params):
                if name in RESERVED_OUTPUT_NAMES:
                    if name not in result.invalid_output_names:
                        result.invalid_output_names.append(name)
                elif name not in result.outputs:
                    result.outputs.append(name)
    return result
