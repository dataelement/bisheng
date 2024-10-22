from typing import Any

from pydantic import BaseModel, Field


# 节点开始事件数据
class NodeStartData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')


class NodeEndData(BaseModel):
    unique_id: str
    node_id: str
    name: str


class UserInputData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    group_params: Any = Field(..., description='User input data')

