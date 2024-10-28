from typing import Any, Optional, List

from pydantic import BaseModel, Field


# 节点开始事件数据
class NodeStartData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')


class NodeEndData(NodeStartData):
    reason: Optional[str] = Field(None, description='Reason for node exec error')


class UserInputData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    group_params: Any = Field(..., description='User input data')


class GuideWordData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    guide_word: str = Field(..., description='Guide word')


class GuideQuestionData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    guide_question: List[str] = Field(..., description='Guide question')


class OutputMsgData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    msg: str = Field(..., description='Output msg')
    group_params: Optional[Any] = Field(None, description='User input data, if not need input, use None')
