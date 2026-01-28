import copy
from enum import Enum
from typing import Optional, Any, List

from pydantic import BaseModel, Field, field_validator


class NodeType(Enum):
    """ Node type """
    START = "start"
    END = "end"
    INPUT = "input"
    AGENT = "agent"
    CODE = "code"
    CONDITION = "condition"
    LLM = "llm"
    OUTPUT = "output"
    FAKE_OUTPUT = "fake_output"
    QA_RETRIEVER = "qa_retriever"
    RAG = "rag"
    REPORT = "report"
    TOOL = "tool"
    KNOWLEDGE_RETRIEVER = "knowledge_retriever"

    NOTE = 'note'  # Notes node Knowledge is used to display annotations, not actual execution nodes


class NodeParams(BaseModel):
    key: str = Field(default="", description="Variablekey")
    label: Optional[str] = Field("", description="Variable description text")
    value: Optional[Any] = Field(None, description="Value of the variable")

    # Variable type -> Detailed reference for data format https://dataelem.feishu.cn/wiki/IfBvwwvfFiHjuQkjFJgcxzoGnxb
    type: Optional[str] = Field("", description="Variable type")
    help: Optional[str] = Field("", description="Variable Help Text")
    tab: Optional[str] = Field("", description="Variable belongs totab, empty to show all")
    placeholder: Optional[str] = Field("", description="Variable placeholder text")
    required: Optional[bool] = Field(False, description="Required?")
    options: Optional[Any] = Field(None, description="Variable options")


class NodeGroupParams(BaseModel):
    name: Optional[str] = Field(default="", description="Group name")
    params: List[NodeParams] = Field(..., description="Group params")
    description: Optional[str] = Field(default="", description="Node description")


class BaseNodeData(BaseModel):
    id: str = Field(default="", description="Unique id for node")
    type: str = Field(..., description="Node type")
    name: Optional[str] = Field(default="", description="Node name")
    description: Optional[str] = Field(default="", description="Node description")
    group_params: Optional[List[NodeGroupParams]] = Field(default=None, description="Node group params")
    tab: Optional[dict] = Field({}, description="tab config")
    tool_key: Optional[str] = Field("", description="unique tool id, only for tool node")
    v: Optional[int] = Field(default=0, description="node version")

    @field_validator('v', mode='before')
    @classmethod
    def convert_v_to_int(cls, v: str | int | None) -> int:
        if isinstance(v, str):
            return int(v)
        elif v is None:
            return 0
        return v

    def get_variable_info(self, variable_key: str) -> NodeParams | None:
        for group_info in self.group_params:
            for one in group_info.params:
                if one.key == variable_key:
                    return copy.deepcopy(one)
        return None
