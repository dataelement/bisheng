import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from uuid import UUID

from bisheng.database.models.flow import FlowCreate, FlowRead
from langchain.docstore.document import Document
from pydantic import BaseModel, Field, validator


class ChunkInput(BaseModel):
    knowledge_id: int
    documents: List[Document]


class BuildStatus(Enum):
    """Status of the build."""

    SUCCESS = 'success'
    FAILURE = 'failure'
    STARTED = 'started'
    IN_PROGRESS = 'in_progress'


class GraphData(BaseModel):
    """Data inside the exported flow."""

    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


class ExportedFlow(BaseModel):
    """Exported flow from bisheng."""

    description: str
    name: str
    id: str
    data: GraphData


class InputRequest(BaseModel):
    input: dict


class TweaksRequest(BaseModel):
    tweaks: Optional[Dict[str, Dict[str, str]]] = Field(default_factory=dict)


class UpdateTemplateRequest(BaseModel):
    template: dict


# 创建泛型变量
DataT = TypeVar('DataT')


class UnifiedResponseModel(Generic[DataT], BaseModel):
    """统一响应模型"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """成功的代码"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)
    # return data


def resp_500(data: str = None, message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """错误的逻辑回复"""
    return UnifiedResponseModel(status_code=500, status_message=message, data=data)


class ProcessResponse(BaseModel):
    """Process response schema."""

    result: Any
    # task: Optional[TaskResponse] = None
    session_id: Optional[str] = None
    backend: Optional[str] = None


class ChatList(BaseModel):
    """Chat message list."""

    flow_name: str = None
    flow_description: str = None
    flow_id: UUID = None
    chat_id: str = None
    create_time: datetime = None
    update_time: datetime = None


class ChatMessage(BaseModel):
    """Chat message schema."""

    is_bot: bool = False
    message: Union[str, None, dict] = ''
    type: str = 'human'
    category: str = 'processing'
    intermediate_steps: str = None
    files: list = []
    user_id: int = None
    message_id: int = None
    source: int = 0
    sender: str = None
    receiver: dict = None
    liked: int = 0
    extra: str = '{}'


class ChatResponse(ChatMessage):
    """Chat response schema."""

    intermediate_steps: str = ''
    type: str
    is_bot: bool = True
    files: list = []
    category: str = 'processing'

    @validator('type')
    def validate_message_type(cls, v):
        if v not in ['start', 'stream', 'end', 'error', 'info', 'file', 'begin', 'close']:
            raise ValueError('type must be start, stream, end, error, info, or file')
        return v


class FileResponse(ChatMessage):
    """File response schema."""

    data: Any
    data_type: str
    type: str = 'file'
    is_bot: bool = True

    @validator('data_type')
    def validate_data_type(cls, v):
        if v not in ['image', 'csv']:
            raise ValueError('data_type must be image or csv')
        return v


class FlowListCreate(BaseModel):
    flows: List[FlowCreate]


class FlowListRead(BaseModel):
    flows: List[FlowRead]


class InitResponse(BaseModel):
    flowId: str


class BuiltResponse(BaseModel):
    built: bool


class UploadFileResponse(BaseModel):
    """Upload file response schema."""

    flowId: Optional[str]
    file_path: str


class StreamData(BaseModel):
    event: str
    data: dict

    def __str__(self) -> str:
        return f'event: {self.event}\ndata: {json.dumps(self.data)}\n\n'
