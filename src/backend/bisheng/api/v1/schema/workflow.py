from enum import Enum
from typing import Optional, Any, List

from pydantic import BaseModel, Field, field_validator


class WorkflowEventType(Enum):
    NodeRun = 'node_run'
    GuideWord = 'guide_word'
    GuideQuestion = 'guide_question'
    UserInput = 'input'
    # UserInput = 'user_input'
    OutputMsg = 'output_msg'
    OutputWithInput = 'output_with_input_msg'
    # OutputWithInput = 'output_input_msg'
    OutputWithChoose = 'output_with_choose_msg'
    # OutputWithChoose = 'output_choose_msg'
    StreamMsg = 'stream_msg'
    Close = 'close'
    Error = 'error'


class WorkflowOutputSchema(BaseModel):
    message: Any = Field(default=None, description='The message content')
    reasoning_content: Optional[str] = Field(default=None, description='The reasoning content')
    output_key: Optional[str] = Field(default=None, description='output message key')
    files: Optional[List[Any]] = Field(default=None, description='The files list')
    source_url: Optional[str] = Field(default=None, description='The document source url, is web url')
    extra: Optional[str] = Field(default=None, description='The extra data')


class WorkflowInputItem(BaseModel):
    key: str = Field(default=None, description='Unique key corresponding to user input')
    type: str = Field(default=None, description='The input type, select or dialog or file')
    value: Any = Field(default=None, description='The input default value')
    label: str = Field(default=None, description='The key label')
    multiple: bool = Field(default=False, description='The input is multi select')
    required: bool = Field(default=False, description='The input is required')
    options: Optional[Any] = Field(default=None, description='The select type options')
    file_type: Optional[str] = Field(default=None, description='The allow upload file type')


class WorkflowInputSchema(BaseModel):
    input_type: str = Field(default=None, description='The judge user input is dialog or form')
    value: List[WorkflowInputItem] = Field(default=None, description='The input schema items')


class WorkflowEvent(BaseModel):
    event: str = Field(default=None, description='The event type')
    message_id: Optional[str] = Field(default=None, description='message id for save into mysql')
    status: Optional[str] = Field(default='end', description='The event status')
    node_id: Optional[str] = Field(default=None, description='The node id')
    node_execution_id: Optional[str] = Field(default=None, description='The node exec unique id')
    output_schema: Optional[WorkflowOutputSchema] = Field(default=None, description='The output schema')
    input_schema: Optional[WorkflowInputSchema] = Field(default=None, description='The input schema')

    @field_validator('message_id', mode='before')
    @classmethod
    def validate_message_id(cls, v: Any) -> Optional[str]:
        if isinstance(v, str) or v is None:
            return v
        return str(v)

class WorkflowStream(BaseModel):
    session_id: str = Field(default=None, description='The session id')
    data: WorkflowEvent | list[WorkflowEvent] = Field(default=None, description='The event data or event data list')
