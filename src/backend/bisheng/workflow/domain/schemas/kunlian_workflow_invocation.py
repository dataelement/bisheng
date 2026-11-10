"""反向运行候选合同。"""

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from bisheng.workflow.domain.schemas.kunlian_registration import RegistrationContract


class RunError(Exception):
    """只携带预定义错误分类。"""


class TextInput(RegistrationContract):
    input: dict[str, str]

    @field_validator("input")
    @classmethod
    def validate_unicode(cls, value):
        for key, text in value.items():
            key.encode()
            text.encode()
        return value


class RunRequest(TextInput):
    workflow_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    workflow_version_id: int = Field(gt=0, le=2**63 - 1)
    input: dict[str, str] = Field(default_factory=dict)
    mode: Literal["interactive"] | None = None

    @field_validator("workflow_version_id", mode="before")
    @classmethod
    def parse_registered_version(cls, value):
        if isinstance(value, str) and 0 < len(value) <= 19 and value.isascii() and value.isdecimal():
            return int(value)
        return value


class InteractionAnswer(TextInput):
    """待填写表单的文本答案。"""


class RunOutput(RegistrationContract):
    result: str


@dataclass(frozen=True)
class RunSubject:
    tenant_id: int
    connection_id: str
    user_id: int


RUN_EVENT_LIMIT = 32
RUN_EVENT_SECONDS = 900


class RunEvent(RegistrationContract):
    seq: int = Field(gt=0)
    kind: Literal[
        "ACCEPTED",
        "STARTED",
        "WAITING_INPUT",
        "RESUME_QUEUED",
        "RESUMED",
        "CANCEL_ACCEPTED",
        "CANCELLED",
        "SUCCEEDED",
        "FAILED",
    ]
    status: Literal[
        "QUEUED",
        "RUNNING",
        "WAITING_INPUT",
        "RESUME_QUEUED",
        "RESUMING",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "SUCCEEDED",
        "FAILED",
    ]
    occurred_at: int


class RunControl(RegistrationContract):
    format: Literal[1] = 1
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    last_seq: int = Field(default=0, ge=0)
    pruned_through: int = Field(default=0, ge=0)
    cancel_accepted_at: int | None = None
    events: list[RunEvent] = Field(default_factory=list, max_length=RUN_EVENT_LIMIT)

    @model_validator(mode="after")
    def validate_sequence(self):
        if (
            self.last_seq != self.pruned_through + len(self.events)
            or any(event.seq != seq for seq, event in enumerate(self.events, start=self.pruned_through + 1))
            or any(previous.occurred_at > current.occurred_at for previous, current in pairwise(self.events))
        ):
            raise ValueError("运行事件顺序无效")
        return self

    def append(self, now, kind, status):
        occurred_at = max(now, self.events[-1].occurred_at) if self.events else now
        self.last_seq += 1
        self.events.append(RunEvent(seq=self.last_seq, kind=kind, status=status, occurred_at=occurred_at))
        if kind == "CANCEL_ACCEPTED":
            self.cancel_accepted_at = occurred_at
        if len(self.events) > RUN_EVENT_LIMIT:
            self.pruned_through = self.events.pop(0).seq


def read_run_control(material):
    if not isinstance(material, dict) or "run_control" not in material:
        return None
    control = material["run_control"]
    if not isinstance(control, dict) or type(control.get("format")) is not int or control["format"] != 1:
        raise RunError("CONTROL_UNAVAILABLE")
    try:
        result = RunControl.model_validate(control)
    except ValidationError as exc:
        raise RunError("CONTROL_UNAVAILABLE") from exc
    if not result.events:
        raise RunError("CONTROL_UNAVAILABLE")
    return result


def _params(node):
    return {param["key"]: param["value"] for group in node["data"]["group_params"] for param in group["params"]}


def _validate_text_contract(nodes, input_schema, output_schema):
    output = _params(nodes["output"])
    message = output.get("output_msg", output["message"])
    if (
        output["output_result"]["type"]
        or message["files"] != []
        or not isinstance(message["msg"], str)
        or output_schema != {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]}
    ):
        raise RunError("VERSION_UNAVAILABLE")

    fields = []
    if "input" in nodes:
        node = nodes["input"]
        if node["data"]["tab"]["value"] != "form_input":
            raise RunError("VERSION_UNAVAILABLE")
        fields = _params(node)["form_input"]
    properties = {field["key"]: {"type": "string"} for field in fields}
    required = {field["key"] for field in fields if field.get("required")}
    if (
        len(properties) != len(fields)
        or any(field["type"] != "text" for field in fields)
        or input_schema["type"] != "object"
        or input_schema["additionalProperties"] is not False
        or input_schema["properties"] != properties
        or set(input_schema["required"]) != required
    ):
        raise RunError("VERSION_UNAVAILABLE")


def validate_text_input(schema, inputs):
    if set(inputs) - schema["properties"].keys() or set(schema["required"]) - inputs.keys():
        raise RunError("INVALID_INPUT")


def validate_interaction_input(schema, inputs):
    if not isinstance(inputs, dict) or any(not isinstance(value, str) for value in inputs.values()):
        raise RunError("INVALID_INPUT")
    validate_text_input(schema, inputs)
    if any(not inputs[key].strip() for key in schema["required"]):
        raise RunError("INVALID_INPUT")


def execution_material(graph, descriptor, inputs, mode=None):
    try:
        nodes = {node["data"]["type"]: node for node in graph["nodes"]}
        order = ["start", "input", "output", "end"] if "input" in nodes else ["start", "output", "end"]
        if set(nodes) != set(order) or len(graph["nodes"]) != len(order):
            raise RunError("VERSION_UNAVAILABLE")
        ids = [nodes[kind]["id"] for kind in order]
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
        if (
            len(set(ids)) != len(ids)
            or len(graph["edges"]) != len(ids) - 1
            or edges != set(pairwise(ids))
            or any(node["id"] != node["data"]["id"] for node in nodes.values())
            or descriptor["dependencies"]
        ):
            raise RunError("VERSION_UNAVAILABLE")
        input_schema = descriptor["input_schema"]
        output_schema = descriptor["output_schema"]
        _validate_text_contract(nodes, input_schema, output_schema)
        material = {
            "graph": graph,
            "input": inputs,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "input_node": nodes["input"]["id"] if "input" in nodes else None,
            "output_node": nodes["output"]["id"],
        }
        if mode == "interactive":
            if inputs:
                raise RunError("INVALID_INPUT")
            if not material["input_node"] or not input_schema["properties"]:
                raise RunError("VERSION_UNAVAILABLE")
            material["mode"] = mode
            required = set(input_schema["required"])
            material["input_schema"] = {
                **input_schema,
                "properties": {
                    key: {**field, "pattern": r"\S"} if key in required else field
                    for key, field in input_schema["properties"].items()
                },
            }
        else:
            validate_text_input(input_schema, inputs)
        return material
    except (KeyError, TypeError, AttributeError) as exc:
        raise RunError("VERSION_UNAVAILABLE") from exc
