from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union
from uuid import UUID

from bisheng.database.models.assistant import AssistantBase
from bisheng.database.models.finetune import TrainMethod
from bisheng.database.models.flow import FlowCreate, FlowRead
from bisheng.database.models.gpts_tools import AuthMethod, AuthType, GptsToolsRead
from bisheng.database.models.knowledge import KnowledgeRead
from bisheng.database.models.llm_server import LLMModelBase, LLMServerBase
from bisheng.database.models.message import ChatMessageRead
from bisheng.database.models.tag import Tag
from langchain.docstore.document import Document
from orjson import orjson
from pydantic import BaseModel, Field, root_validator, validator


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


class AddChatMessages(BaseModel):
    """Add a pair of chat messages."""

    flow_id: UUID  # 技能或助手ID
    chat_id: str  # 会话ID
    human_message: str = None  # 用户问题
    answer_message: str = None  # 执行结果


class ChatList(BaseModel):
    """Chat message list."""

    flow_name: str = None
    flow_description: str = None
    flow_id: UUID = None
    chat_id: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: str = None  # flow: 技能 assistant：gpts助手
    latest_message: ChatMessageRead = None
    logo: Optional[str] = None


class FlowGptsOnlineList(BaseModel):
    id: str = Field('唯一ID')
    name: str = None
    desc: str = None
    logo: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: str = None  # flow: 技能 assistant：gpts助手
    count: int = 0


class ChatMessage(BaseModel):
    """Chat message schema."""

    is_bot: bool = False
    message: Union[str, None, dict, list] = ''
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
    extra: str | dict = '{}'
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
        """
        end_cover: 结束并覆盖上一条message
        """
        if v not in [
                'start', 'stream', 'end', 'error', 'info', 'file', 'begin', 'close', 'end_cover',
                'over'
        ]:
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
    relative_path: Optional[str]  # minio的相对路径，即object_name


class StreamData(BaseModel):
    event: str
    data: dict | str

    def __str__(self) -> str:
        if isinstance(self.data, dict):
            return f'event: {self.event}\ndata: {orjson.dumps(self.data).decode()}\n\n'
        return f'event: {self.event}\ndata: {self.data}\n\n'


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
    flow_type: Optional[int]
    write: Optional[bool] = Field(default=False)
    group_ids: Optional[List[int]]
    tags: Optional[List[Tag]]
    create_time: datetime
    update_time: datetime


class AssistantInfo(AssistantBase):
    tool_list: List[GptsToolsRead] = Field(default=[], description='助手的工具ID列表')
    flow_list: List[FlowRead] = Field(default=[], description='助手的技能ID列表')
    knowledge_list: List[KnowledgeRead] = Field(default=[], description='知识库ID列表')


class FlowVersionCreate(BaseModel):
    name: Optional[str] = Field(default=..., description='版本的名字')
    description: Optional[str] = Field(default=None, description='版本的描述')
    data: Optional[Dict] = Field(default=None, description='技能版本的节点数据数据')
    original_version_id: Optional[int] = Field(default=None, description='版本的来源版本ID')
    flow_type: Optional[int] = Field(default=1, description='版本的类型') # 1:普通版本 10:new 版本


class FlowCompareReq(BaseModel):
    inputs: Any = Field(default=None, description='技能运行所需要的输入')
    question_list: List[str] = Field(default=[], description='测试case列表')
    version_list: List[int] = Field(default=[], description='对比版本ID列表')
    node_id: str = Field(default=None, description='需要对比的节点唯一ID')
    thread_num: Optional[int] = Field(default=1, description='对比线程数')


class DeleteToolTypeReq(BaseModel):
    tool_type_id: int = Field(description='要删除的工具类别ID')


class TestToolReq(BaseModel):
    server_host: str = Field(default='', description='服务的根地址')
    extra: str = Field(default='', description='Api 对象解析后的extra字段')
    auth_method: int = Field(default=AuthMethod.NO.value, description='认证类型')
    auth_type: Optional[str] = Field(default=AuthType.BASIC.value, description='Auth Type')
    api_key: Optional[str] = Field(default='', description='api key')

    request_params: Dict = Field(default=None, description='用户填写的请求参数')


class GroupAndRoles(BaseModel):
    group_id: int
    role_ids: List[int]


class CreateUserReq(BaseModel):
    user_name: str = Field(max_length=30, description='用户名')
    password: str = Field(description='密码')
    group_roles: List[GroupAndRoles] = Field(description='要加入的用户组和角色列表')


class OpenAIChatCompletionReq(BaseModel):
    messages: List[dict] = Field(..., description='聊天消息列表，只支持user、assistant。system用数据库内的数据')
    model: str = Field(..., description='助手的唯一ID')
    n: int = Field(default=1, description='返回的答案个数, 助手侧默认为1，暂不支持多个回答')
    stream: bool = Field(default=False, description='是否开启流式回复')
    temperature: float = Field(default=0.0, description='模型温度, 传入0或者不传表示不覆盖')
    tools: List[dict] = Field(default=[], description='工具列表, 助手暂不支持，使用助手的配置')


class OpenAIChoice(BaseModel):
    index: int = Field(..., description='选项的索引')
    message: dict = Field(default=None, description='对应的消息内容，和输入的格式一致')
    finish_reason: str = Field(default='stop', description='结束原因, 助手只有stop')
    delta: dict = Field(default=None, description='对应的openai流式返回消息内容')


class OpenAIChatCompletionResp(BaseModel):
    id: str = Field(..., description='请求的唯一ID')
    object: str = Field(default='chat.completion', description='返回的类型')
    created: int = Field(default=..., description='返回的创建时间戳')
    model: str = Field(..., description='返回的模型，对应助手的id')
    choices: List[OpenAIChoice] = Field(..., description='返回的答案列表')
    usage: dict = Field(default=None, description='返回的token用量, 助手此值为空')
    system_fingerprint: Optional[str] = Field(default=None, description='系统指纹')


class LLMModelCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='模型唯一ID, 更新时需要传')
    name: str = Field(..., description='模型展示名称')
    description: Optional[str] = Field(default='', description='模型描述')
    model_name: str = Field(..., description='模型名称')
    model_type: str = Field(..., description='模型类型')
    online: bool = Field(default=True, description='是否在线')
    config: Optional[dict] = Field(default=None, description='模型配置')


class LLMServerCreateReq(BaseModel):
    id: Optional[int] = Field(default=None, description='服务提供方ID, 更新时需要传')
    name: str = Field(..., description='服务提供方名称')
    description: Optional[str] = Field(default='', description='服务提供方描述')
    type: str = Field(..., description='服务提供方类型')
    limit_flag: Optional[bool] = Field(default=False, description='是否开启每日调用次数限制')
    limit: Optional[int] = Field(default=0, description='每日调用次数限制')
    config: Optional[dict] = Field(default=None, description='服务提供方配置')
    models: Optional[List[LLMModelCreateReq]] = Field(default=[], description='服务提供方下的模型列表')


class LLMModelInfo(LLMModelBase):
    id: Optional[int]


class LLMServerInfo(LLMServerBase):
    id: Optional[int]
    models: List[LLMModelInfo] = Field(default=[], description='模型列表')


class KnowledgeLLMConfig(BaseModel):
    embedding_model_id: Optional[int] = Field(description='知识库默认embedding模型的ID')
    source_model_id: Optional[int] = Field(description='知识库溯源模型的ID')
    extract_title_model_id: Optional[int] = Field(description='文档知识库提取标题模型的ID')
    qa_similar_model_id: Optional[int] = Field(description='QA知识库相似问模型的ID')


class AssistantLLMItem(BaseModel):
    model_id: Optional[int] = Field(description='模型的ID')
    agent_executor_type: Optional[str] = Field(default='ReAct',
                                               description='执行模式。function call 或者 ReAct')
    knowledge_max_content: Optional[int] = Field(default=15000, description='知识库检索最大字符串数')
    knowledge_sort_index: Optional[bool] = Field(default=False, description='知识库检索后是否重排')
    streaming: Optional[bool] = Field(default=True, description='是否开启流式')
    default: Optional[bool] = Field(default=False, description='是否为默认模型')


class AssistantLLMConfig(BaseModel):
    llm_list: Optional[List[AssistantLLMItem]] = Field(default=[], description='助手可选的LLM列表')
    auto_llm: Optional[AssistantLLMItem] = Field(description='助手画像自动优化模型的配置')


class EvaluationLLMConfig(BaseModel):
    model_id: Optional[int] = Field(description='评测功能默认模型的ID')


# 文件切分请求基础参数
class FileProcessBase(BaseModel):
    knowledge_id: int = Field(..., description='知识库ID')
    separator: Optional[List[str]] = Field(default=['\n\n'], description='切分文本规则, 不传则为默认')
    separator_rule: Optional[List[str]] = Field(default=['after'],
                                                description='切分规则前还是后进行切分；before/after')
    chunk_size: Optional[int] = Field(default=1000, description='切分文本长度，不传则为默认')
    chunk_overlap: Optional[int] = Field(default=100, description='切分文本重叠长度，不传则为默认')

    @root_validator
    def check_separator_rule(cls, values):
        if values['separator'] is None:
            values['separator'] = ['\n\n']
        if values['separator_rule'] is None:
            values['separator_rule'] = ['after' for _ in values['separator']]
        if values['chunk_size'] is None:
            values['chunk_size'] = 1000
        if values['chunk_overlap'] is None:
            values['chunk_overlap'] = 100
        return values


class FileChunkMetadata(BaseModel):
    source: str = Field(default='', description='源文件名')
    title: str = Field(default='', description='源文件内容总结的标题')
    chunk_index: int = Field(default=0, description='文本块索引')
    bbox: str = Field(default='', description='文本块bbox信息')
    page: int = Field(default=0, description='文本块所在页码')
    extra: str = Field(default='', description='文本块额外信息')
    file_id: int = Field(default=0, description='文本块所属文件ID')


# 文件分块数据格式
class FileChunk(BaseModel):
    text: str = Field(..., description='文本块内容')
    parse_type: Optional[str] = Field(default=None, description='文本所属的文件解析类型')
    metadata: FileChunkMetadata = Field(..., description='文本块元数据')


# 预览文件分块内容请求参数
class PreviewFileChunk(FileProcessBase):
    file_path: str = Field(..., description='文件路径')
    cache: bool = Field(default=True, description='是否从缓存获取')


class UpdatePreviewFileChunk(BaseModel):
    knowledge_id: int = Field(..., description='知识库ID')
    file_path: str = Field(..., description='文件路径')
    text: str = Field(..., description='文本块内容')
    chunk_index: int = Field(..., description='文本块索引, 在metadata里')
    bbox: Optional[str] = Field(default='', description='文本块bbox信息')


class KnowledgeFileOne(BaseModel):
    file_path: str = Field(..., description='文件路径')


# 知识库文件处理
class KnowledgeFileProcess(FileProcessBase):
    file_list: List[KnowledgeFileOne] = Field(..., description='文件列表')
    callback_url: Optional[str] = Field(default=None, description='异步任务回调地址')
    extra: Optional[str] = Field(default=None, description='附加信息')
