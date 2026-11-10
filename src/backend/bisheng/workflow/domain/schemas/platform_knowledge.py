"""昆联检索节点的本地合同。"""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from bisheng.common.errcode.flow import PlatformKnowledgeConfigurationError

NODE_TYPE = "platform_knowledge_retriever"
PUBLICATION_KEY = "_platform_knowledge_publication"
OUTPUT_KEYS = ("retrieved_result", "retrieved_text", "citations", "hit_count")
MISSING = object()
# TODO [F120][EXT-03] 正式检索协议确认后校准本地限制。
MAX_QUERY_LENGTH = 8192
MAX_TOP_K = 20


class KnowledgeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ConstantQuestion(KnowledgeContract):
    source: Literal["constant"]
    value: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)


class VariableQuestion(KnowledgeContract):
    source: Literal["variable"]
    variable: str = Field(pattern=r"^[\w-]+\.[\w-]+(?:#[\w-]+)?$", max_length=256)


class KnowledgeReference(KnowledgeContract):
    resource_id: str = Field(min_length=1, max_length=256, pattern=r"^[^\s]+$")


class KnowledgeNodeConfiguration(KnowledgeContract):
    user_question: Annotated[ConstantQuestion | VariableQuestion, Field(discriminator="source")]
    knowledge: KnowledgeReference
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)


class KnowledgeHit(KnowledgeContract):
    resource_id: str
    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    document_name: str | None = None
    location: str | None = None
    score: FiniteFloat | None = None


@dataclass(frozen=True)
class KnowledgeActor:
    user_id: int
    tenant_id: int
    token_version: int


def uses_platform_knowledge(graph: dict | None) -> bool:
    return bool(
        graph
        and (
            PUBLICATION_KEY in graph
            or any(row.get("data", {}).get("type") == NODE_TYPE for row in graph.get("nodes", []))
        )
    )


def node_configuration(node: dict) -> KnowledgeNodeConfiguration:
    values = {}
    try:
        for group in node.get("group_params", []):
            for param in group["params"]:
                key = param["key"]
                if key in values:
                    raise ValueError
                values[key] = param.get("value")
        declarations = values.pop("retrieved_result")
        if tuple(row["key"] for row in declarations) != OUTPUT_KEYS:
            raise ValueError
        config = KnowledgeNodeConfiguration.model_validate(values)
        if isinstance(config.user_question, ConstantQuestion) and not config.user_question.value.strip():
            raise ValueError
        return config
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PlatformKnowledgeConfigurationError() from None


def graph_nodes(graph: dict) -> list[dict]:
    ids, nodes = set(), []
    try:
        for item in graph["nodes"]:
            data = item["data"]
            node_id = data["id"]
            if not isinstance(node_id, str) or not node_id or node_id in ids or item.get("id", node_id) != node_id:
                raise ValueError
            ids.add(node_id)
            if data.get("type") == NODE_TYPE:
                nodes.append(data)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PlatformKnowledgeConfigurationError() from None
    return nodes


def resolve_question(config: KnowledgeNodeConfiguration, lookup) -> str:
    question = config.user_question
    value = question.value if isinstance(question, ConstantQuestion) else lookup(question.variable)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MAX_QUERY_LENGTH:
        raise PlatformKnowledgeConfigurationError()
    return value.strip()
