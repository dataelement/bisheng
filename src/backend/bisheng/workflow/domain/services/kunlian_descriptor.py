import re

from pydantic import ValidationError

from bisheng.workflow.domain.schemas.kunlian_registration import Descriptor
from bisheng.workflow.domain.schemas.platform_agent import canonical_digest


def _parameters(node):
    return {param["key"]: param.get("value") for group in node.get("group_params", []) for param in group["params"]}


def prepare_descriptor(flow, version, graph, agent_binding, knowledge_binding):
    # TODO [F121][EXT-03] 本地仅定义单文本输出和单文本表单的模拟合同。
    nodes = [item["data"] for item in graph["nodes"]]
    inputs = [node for node in nodes if node.get("type") == "input"]
    outputs = [node for node in nodes if node.get("type") == "output"]
    if len(inputs) > 1 or len(outputs) != 1:
        return None
    params = _parameters(outputs[0])
    message = params.get("message") or {}
    if (
        (params.get("output_result") or {}).get("type")
        or message.get("files")
        or not isinstance(message.get("msg"), str)
    ):
        return None
    properties, required = {}, []
    if inputs:
        node = inputs[0]
        if (node.get("tab") or {}).get("value") != "form_input":
            return None
        for field in _parameters(node).get("form_input") or []:
            key = field.get("key")
            if (
                field.get("type") != "text"
                or not isinstance(key, str)
                or not re.fullmatch(r"[A-Za-z_][\w]{0,49}", key)
                or key in properties
            ):
                return None
            properties[key] = {"type": "string"}
            if field.get("required"):
                required.append(key)
    dependencies = []
    for item in agent_binding.get("nodes", {}).values():
        ref = item["ref"]
        dependencies.append(
            {"resource_type": "agent", "resource_id": ref.get("agent_id"), "resource_version_id": ref.get("version_id")}
        )
    for item in knowledge_binding.get("nodes", {}).values():
        dependencies.append({"resource_type": "knowledge", "resource_id": item["knowledge"]["resource_id"]})
    try:
        descriptor = Descriptor(
            workflow_id=flow.id,
            workflow_version_id=str(version.id),
            name=flow.name,
            description=version.description or flow.description or "",
            input_schema={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
            dependencies=dependencies,
        ).model_dump(exclude_none=True)
    except ValidationError:
        return None
    return {**descriptor, "descriptor_digest": canonical_digest(descriptor)}
