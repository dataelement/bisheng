from typing import Any

from pydantic import BaseModel, Field


# 节点开始事件数据
class NodeStartData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')


class NodeEndData(NodeStartData):
    pass


class UserInputData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    group_params: Any = Field(..., description='User input data')


class GuideWordData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    guide_word: str = Field(..., description='Guide word')


class GuideQuestionData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    guide_question: str = Field(..., description='Guide question')
