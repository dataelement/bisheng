from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from uuid import UUID

from bisheng.database.models.assistant import AssistantBase
from bisheng.database.models.finetune import TrainMethod
from bisheng.database.models.flow import FlowCreate, FlowRead
from bisheng.database.models.gpts_tools import GptsToolsRead, AuthMethod, AuthType
from bisheng.database.models.knowledge import KnowledgeRead
from langchain.docstore.document import Document
from orjson import orjson
from pydantic import BaseModel, Field, validator


class CaptchaInput(BaseModel):
    captcha_key: str
    captcha: str


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
    input: str = Field(description='question or command asked LLM to do')


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


def resp_500(code: int = 500,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """错误的逻辑回复"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


class ProcessResponse(BaseModel):
    """Process response schema."""

    result: Any
    # task: Optional[TaskResponse] = None
    session_id: Optional[str] = None
    backend: Optional[str] = None


class ChatInput(BaseModel):
    message_id: int
    comment: str = None
    liked: int = 0


class ChatList(BaseModel):
    """Chat message list."""

    flow_name: str = None
    flow_description: str = None
    flow_id: UUID = None
    chat_id: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: str = None  # flow: 技能 assistant：gpts助手


class FlowGptsOnlineList(BaseModel):
    id: str = Field('唯一ID')
    name: str = None
    desc: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: str = None  # flow: 技能 assistant：gpts助手


class ChatMessage(BaseModel):
    """Chat message schema."""

    is_bot: bool = False
    message: Union[str, None, dict] = ''
    type: str = 'human'
    category: str = 'processing'  # system processing answer tool
    intermediate_steps: str = None
    files: list = []
    user_id: int = None
    message_id: int = None
    source: int = 0
    sender: str = None
    receiver: dict = None
    liked: int = 0
    extra: str = '{}'
    flow_id: str = None
    chat_id: str = None


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
        return f'event: {self.event}\ndata: {orjson.dumps(self.data).decode()}\n\n'


class FinetuneCreateReq(BaseModel):
    server: int = Field(description='关联的RT服务ID')
    base_model: int = Field(description='基础模型ID')
    model_name: str = Field(max_length=50, description='模型名称')
    method: TrainMethod = Field(description='训练方法')
    extra_params: Dict = Field(default_factory=dict, description='训练任务所需额外参数')
    train_data: Optional[List[Dict]] = Field(default=None, description='个人训练数据')
    preset_data: Optional[List[Dict]] = Field(default=None, description='预设训练数据')


class CreateComponentReq(BaseModel):
    name: str = Field(max_length=50, description='组件名称')
    data: Any = Field(default='', description='组件数据')
    description: Optional[str] = Field(default='', description='组件描述')


class CustomComponentCode(BaseModel):
    code: str
    field: Optional[str] = None
    frontend_node: Optional[dict] = None


class AssistantCreateReq(BaseModel):
    name: str = Field(max_length=50, description='助手名称')
    prompt: str = Field(min_length=20, max_length=1000, description='助手提示词')
    logo: str = Field(description='logo文件的相对地址')


class AssistantUpdateReq(BaseModel):
    id: UUID = Field(description='助手ID')
    name: Optional[str] = Field('', description='助手名称， 为空则不更新')
    desc: Optional[str] = Field('', description='助手描述， 为空则不更新')
    logo: Optional[str] = Field('', description='logo文件的相对地址，为空则不更新')
    prompt: Optional[str] = Field('', description='用户可见prompt， 为空则不更新')
    guide_word: Optional[str] = Field('', description='开场白， 为空则不更新')
    guide_question: Optional[List] = Field([], description='引导问题列表， 为空则不更新')
    model_name: Optional[str] = Field('', description='选择的模型名， 为空则不更新')
    temperature: Optional[float] = Field(None, description='模型温度， 不传则不更新')

    tool_list: List[int] | None = Field(default=None,
                                        description='助手的工具ID列表,空列表则清空绑定的工具，为None则不更新')
    flow_list: List[str] | None = Field(default=None, description='助手的技能ID列表，为None则不更新')
    knowledge_list: List[int] | None = Field(default=None, description='知识库ID列表，为None则不更新')


class AssistantSimpleInfo(BaseModel):
    id: UUID
    name: str
    desc: str
    logo: str
    user_id: int
    user_name: str
    status: int
    write: Optional[bool] = Field(default=False)
    create_time: datetime
    update_time: datetime


class AssistantInfo(AssistantBase):
    tool_list: List[GptsToolsRead] = Field(default=[], description='助手的工具ID列表')
    flow_list: List[FlowRead] = Field(default=[], description='助手的技能ID列表')
    knowledge_list: List[KnowledgeRead] = Field(default=[], description='知识库ID列表')


class FlowVersionCreate(BaseModel):
    name: Optional[str] = Field(default=None, description="版本的名字")
    description: Optional[str] = Field(default=None, description="版本的描述")
    data: Optional[Dict] = Field(default=None, description='技能版本的节点数据数据')


class FlowCompareReq(BaseModel):
    inputs: Any = Field(default=None, description='技能运行所需要的输入')
    question_list: List[str] = Field(default=[], description='测试case列表')
    version_list: List[int] = Field(default=[], description='对比版本ID列表')
    node_id: str = Field(default=None, description='需要对比的节点唯一ID')
    thread_num: Optional[int] = Field(default=1, description='对比线程数')


class DeleteToolTypeReq(BaseModel):
    tool_type_id: int = Field(description="要删除的工具类别ID")


class TestToolReq(BaseModel):
    server_host: str = Field(default='', description="服务的根地址")
    extra: str = Field(default='', description="Api 对象解析后的extra字段")
    auth_method: int = Field(default=AuthMethod.NO.value, description="认证类型")
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description="Auth Type")
    api_key: Optional[str] = Field(default='', description="api key")

    request_params: Dict = Field(default=None, description="用户填写的请求参数")
