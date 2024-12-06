from enum import Enum
from typing import Optional, Any, List

from pydantic import BaseModel, Field


class NodeType(Enum):
    """ 节点类型 """
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


class NodeParams(BaseModel):
    key: str = Field(default="", description="变量的key")
    label: Optional[str] = Field("", description="变量描述文本")
    value: Optional[Any] = Field(description="变量的值")

    # 变量类型 -> 数据格式的详情参考 https://dataelem.feishu.cn/wiki/IfBvwwvfFiHjuQkjFJgcxzoGnxb
    type: Optional[str] = Field("", description="变量类型")
    help: Optional[str] = Field("", description="变量帮助文本")
    tab: Optional[str] = Field("", description="变量所属的tab，为空则都展示")
    placeholder: Optional[str] = Field("", description="变量的占位提示文本")
    required: Optional[bool] = Field(False, description="是否必填")
    options: Optional[Any] = Field(None, description="变量的选项")


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

    def get_variable_info(self, variable_key: str) -> NodeParams | None:
        for group_info in self.group_params:
            for one in group_info.params:
                if one.key == variable_key:
                    return one

