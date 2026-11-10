"""平台 Agent 的内部契约。独立于尚待确认的昆联 HTTP 报文。"""

import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.errcode.flow import PlatformAgentConfigurationError, PlatformAgentOutputError

MISSING = object()
PUBLICATION_KEY = "_platform_agent_publication"


class AgentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class AgentReference(AgentContract):
    agent_id: str = Field(min_length=1, max_length=256)
    version_id: str = Field(min_length=1, max_length=256)


class AgentVersion(AgentContract):
    ref: AgentReference
    name: str
    input_schema: dict
    output_schema: dict
    available: bool = True
    can_use: bool = True
    supports_async: bool = False
    supports_interaction: bool = False


class AgentInputBinding(AgentContract):
    source: Literal["constant", "variable"]
    value: Any = None
    variable: str | None = None


class AgentNodeConfiguration(AgentContract):
    agent_ref: AgentReference | None = None
    input_bindings: dict[str, AgentInputBinding] = Field(default_factory=dict)
    execution_mode: Literal["sync", "async"] = "sync"
    allow_interaction: bool = False


class AgentInteractionReference(AgentContract):
    interaction_id: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=128)


class AgentInteraction(AgentInteractionReference):
    label: str = Field(min_length=1, max_length=256)
    required: Literal[True] = True
    max_length: int = Field(default=2000, ge=1, le=2000)


class AgentSubmissionReceipt(AgentContract):
    run_id: str
    ref: AgentReference
    interaction_id: str
    revision: str
    submission_key: str
    status: Literal["ACCEPTED", "REJECTED"]


class AgentRunObservation(AgentContract):
    run_id: str = Field(min_length=1, max_length=256)
    ref: AgentReference
    status: Literal["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELLED"]
    progress: int | None = Field(default=None, ge=0, le=100)
    interaction: AgentInteraction | None = None


class AgentInvokeResult(AgentContract):
    status: Literal["SUCCEEDED", "FAILED", "RUNNING", "INPUT"]
    ref: AgentReference
    output: Any = None
    agent_run_id: str | None = Field(default=None, max_length=256)


@dataclass(frozen=True)
class VerifiedAgentActor:
    """仅由通过本地业务授权的应用入口构造。不解析请求中的身份字段。"""

    user_id: int
    tenant_id: int
    token_version: int = 0


@dataclass(frozen=True)
class AgentDispatch:
    execution_id: str
    dispatch_id: str
    owner: str


def canonical_digest(value: Any) -> str:
    try:
        serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError):
        raise PlatformAgentConfigurationError() from None
    return hashlib.sha256(serialized.encode()).hexdigest()


def validate_schema(schema: dict, *, root_object: bool = False) -> None:
    allowed = {
        "$schema",
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "additionalProperties",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "title",
        "description",
        "default",
    }
    pending = [(schema, 0)]
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, dict) or depth > 32 or set(current) - allowed:
            raise PlatformAgentConfigurationError()
        if "$schema" in current and current["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise PlatformAgentConfigurationError()
        properties = current.get("properties", {})
        if not isinstance(properties, dict):
            raise PlatformAgentConfigurationError()
        pending.extend((child, depth + 1) for child in properties.values())
        for key in ("items", "additionalProperties"):
            child = current.get(key)
            if isinstance(child, dict):
                pending.append((child, depth + 1))
    try:
        Draft202012Validator.check_schema(schema)
        canonical_digest(schema)
    except (SchemaError, TypeError):
        raise PlatformAgentConfigurationError() from None
    if root_object and schema.get("type") != "object":
        raise PlatformAgentConfigurationError()


def validate_value(value: Any, schema: dict, *, output: bool = False) -> None:
    error_class = PlatformAgentOutputError if output else PlatformAgentConfigurationError
    try:
        canonical_digest(value)
        Draft202012Validator(schema).validate(value)
    except (ValidationError, PlatformAgentConfigurationError):
        raise error_class() from None


def resolve_inputs(bindings: dict[str, AgentInputBinding], schema: dict, lookup) -> dict:
    validate_schema(schema, root_object=True)
    values = {}
    for key, binding in bindings.items():
        if binding.source == "constant":
            value = binding.value if "value" in binding.model_fields_set else MISSING
        else:
            value = lookup(binding.variable) if binding.variable else MISSING
        if value is MISSING:
            raise PlatformAgentConfigurationError()
        values[key] = value
    validate_value(values, schema)
    return values


def platform_nodes(graph: dict) -> list[dict]:
    return [node["data"] for node in graph.get("nodes", []) if node.get("data", {}).get("type") == "platform_agent"]


def uses_platform_agent(graph: dict | None) -> bool:
    return bool(graph and (platform_nodes(graph) or PUBLICATION_KEY in graph))


def uses_long_platform_agent(graph: dict | None) -> bool:
    return any(node_configuration(node).execution_mode == "async" for node in platform_nodes(graph or {}))


def uses_agent_interaction(graph: dict) -> bool:
    return any(
        node_configuration(node).allow_interaction
        for node in platform_nodes(graph)
        if any(
            param.get("key") == "allow_interaction"
            for group in node.get("group_params", [])
            for param in group.get("params", [])
        )
    )


def linear_agent_node_ids(graph: dict) -> tuple[str, str]:
    """只允许开始、平台 Agent、纯文本输出、结束组成的线性图。"""
    try:
        nodes = [item for item in graph["nodes"] if item["data"]["type"] != "note"]
        by_type = {item["data"]["type"]: item for item in nodes}
        order = ("start", "platform_agent", "output", "end")
        if len(nodes) != len(order) or set(by_type) != set(order):
            raise PlatformAgentConfigurationError()
        ids = [by_type[kind]["id"] for kind in order]
        edges = graph["edges"]
        if (
            any(not isinstance(item["id"], str) or not item["id"] or item["id"] != item["data"]["id"] for item in nodes)
            or len(set(ids)) != len(ids)
            or len(edges) != len(ids) - 1
            or {(edge["source"], edge["target"]) for edge in edges} != set(pairwise(ids))
        ):
            raise PlatformAgentConfigurationError()
        params = {
            item["key"]: item["value"]
            for group in by_type["output"]["data"]["group_params"]
            for item in group["params"]
        }
        message = params["output_msg"] if "output_msg" in params else params["message"]
        if params["output_result"]["type"] not in ("", "text") or message["files"]:
            raise PlatformAgentConfigurationError()
        return ids[0], ids[1]
    except (KeyError, TypeError):
        raise PlatformAgentConfigurationError() from None


def interaction_node_ids(graph: dict) -> tuple[str, str]:
    return linear_agent_node_ids(graph)


def long_task_resume_node_ids(graph: dict) -> tuple[str, str]:
    start, agent = linear_agent_node_ids(graph)
    config = node_configuration(platform_nodes(graph)[0])
    if config.execution_mode != "async" or config.allow_interaction:
        raise PlatformAgentConfigurationError()
    return start, agent


def node_configuration(node: dict) -> AgentNodeConfiguration:
    params = {
        param["key"]: param.get("value") for group in node.get("group_params", []) for param in group.get("params", [])
    }
    if set(params) - {"agent_ref", "input_bindings", "result", "execution_mode", "allow_interaction"}:
        raise PlatformAgentConfigurationError()
    try:
        return AgentNodeConfiguration.model_validate(
            {
                "agent_ref": params.get("agent_ref"),
                "input_bindings": params.get("input_bindings") or {},
                "execution_mode": params.get("execution_mode", "sync"),
                "allow_interaction": params.get("allow_interaction", False),
            }
        )
    except ValueError:
        raise PlatformAgentConfigurationError() from None
