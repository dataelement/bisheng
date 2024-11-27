from typing import Any, List, Optional, Dict

from pydantic import BaseModel, Field


# 节点开始事件数据
class NodeStartData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')


class NodeEndData(NodeStartData):
    reason: Optional[str] = Field(None, description='Reason for node exec error')
    log_data: Dict = Field(None, description='Log data on node exec success')


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
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    msg: str = Field('', description='Output msg')
    files: List[dict] = Field([], description='Output files', exclude=True)
    output_key: str = Field(..., description='Whether the message is stream')
    stream: bool = Field(False, description='Whether the message is stream', exclude=True)


class OutputMsgInputData(OutputMsgData):
    key: str = Field('', description='variable key')
    unique_id: Optional[str] = Field('', description='Unique execution id')
    input_msg: str = Field('', description='default input msg')


class OutputMsgChooseData(OutputMsgData):
    key: str = Field('', description='variable key')
    unique_id: Optional[str] = Field('', description='Unique execution id')
    options: Any = Field(None, description='default msg')
