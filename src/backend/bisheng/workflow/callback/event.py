from typing import Any, List, Optional

from pydantic import BaseModel, Field


# Node start event data
class NodeStartData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')


class NodeEndData(NodeStartData):
    reason: Optional[str] = Field(None, description='Reason for node exec error')
    log_data: Any = Field(None, description='Log data on node exec success')
    input_data: Any = Field(None, description='Input variable data for node exec')


class UserInputData(BaseModel):
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')
    input_schema: Any = Field(..., description='Input schema')


class GuideWordData(BaseModel):
    unique_id: Optional[str] = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')
    guide_word: str = Field(..., description='Guide word')


class GuideQuestionData(BaseModel):
    unique_id: Optional[str] = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')
    guide_question: List[str] = Field(..., description='Guide question')


class OutputMsgData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')
    msg: str = Field('', description='Output msg')
    files: List[dict] = Field(default_factory=list, description='Output files', exclude=True)
    output_key: str = Field(..., description='Whether the message is stream')
    source_documents: Optional[Any] = Field(None, description='Source documents')


class OutputMsgInputData(OutputMsgData):
    key: str = Field('', description='variable key')
    unique_id: Optional[str] = Field('', description='Unique execution id')
    input_msg: str = Field('', description='default input msg')


class OutputMsgChooseData(OutputMsgData):
    key: str = Field('', description='variable key')
    unique_id: Optional[str] = Field('', description='Unique execution id')
    options: Any = Field(None, description='default msg')


class StreamMsgData(BaseModel):
    unique_id: str = Field(..., description='Unique execution id')
    node_id: str = Field(..., description='Node unique id')
    name: str = Field(..., description='Node name')
    msg: Optional[str] = Field('', description='Stream msg')
    reasoning_content: Optional[str] = Field(None, description='Reasoning content')
    output_key: str = Field(..., description='Whether the message is stream')


class StreamMsgOverData(StreamMsgData):
    source_documents: Optional[List[Any]] = Field(default=[], description='Source documents')
