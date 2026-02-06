from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from langchain.docstore.document import Document
from orjson import orjson
from pydantic import BaseModel, Field, model_validator, field_validator

from bisheng.database.models.assistant import AssistantBase
from bisheng.database.models.flow import FlowCreate, FlowRead
from bisheng.database.models.message import ChatMessageRead
from bisheng.database.models.tag import Tag
from bisheng.knowledge.domain.models.knowledge import KnowledgeRead
from bisheng.knowledge.domain.schemas.knowledge_rag_schema import Metadata
from bisheng.tool.domain.models.gpts_tools import GptsToolsRead


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
    tweaks: Optional[Dict[str, Dict[str, str]]] = Field(default_factory=dict, description='List of dictionaries')


class UpdateTemplateRequest(BaseModel):
    template: dict


# Create generic variables
DataT = TypeVar('DataT')


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """Unified Response Model"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """Success code"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)
    # return data


def resp_500(code: int = 500,
             data: Union[list, dict, str, Any] = None,
             message: str = 'BAD REQUEST') -> UnifiedResponseModel:
    """Wrong logical response"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


class ProcessResponse(BaseModel):
    """Process response schema."""

    result: Any = None
    # task: Optional[TaskResponse] = None
    session_id: Optional[str] = None
    backend: Optional[str] = None


class ChatInput(BaseModel):
    message_id: int
    comment: str = None
    liked: int = 0


class AddChatMessages(BaseModel):
    """Add a pair of chat messages."""

    flow_id: str  # Skills or assistantsID
    chat_id: str  # SessionsID
    human_message: str = None  # User Questions
    answer_message: str = None  # Execution Status


class ChatList(BaseModel):
    """Chat message list."""

    flow_name: str = None
    flow_description: str = None
    flow_id: str = None
    chat_id: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: int = None
    latest_message: Optional[ChatMessageRead] = None
    logo: Optional[str] = None


class FlowGptsOnlineList(BaseModel):
    id: str = Field('Uniqueness quantificationID')
    name: str = None
    desc: str = None
    logo: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: str = None  # flow: Skill assistant：gptsassistant
    count: int = 0


class ChatMessage(BaseModel):
    """Chat message schema."""

    is_bot: bool = False
    message: Union[str, None, dict, list] = ''
    type: str = 'human'
    category: str = 'processing'  # system processing answer tool
    intermediate_steps: Optional[str] = None
    files: Optional[list] = []
    user_id: Optional[int] = None
    message_id: Optional[int | str] = None
    source: Optional[int] = 0
    sender: Optional[str] = None
    receiver: Optional[dict] = None
    liked: int = 0
    extra: Optional[str | dict] = '{}'
    flow_id: Optional[str] = None
    chat_id: Optional[str] = None


class ChatResponse(ChatMessage):
    """Chat response schema."""

    intermediate_steps: Optional[str] = ''
    is_bot: bool | int = True
    category: str = 'processing'

    @field_validator('type')
    @classmethod
    def validate_message_type(cls, v):
        """
        end_cover: End & Overwrite Previousmessage
        """
        if v not in [
            'start', 'stream', 'end', 'error', 'info', 'file', 'begin', 'close', 'end_cover',
            'over'
        ]:
            raise ValueError('type must be start, stream, end, error, info, or file')
        return v


class FileResponse(ChatMessage):
    """File response schema."""

    data: Any = None
    data_type: str
    type: str = 'file'
    is_bot: bool = True

    @field_validator('data_type')
    @classmethod
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

    flowId: Optional[str] = None
    file_path: str
    relative_path: Optional[str] = None  # minioRelative path, i.e.object_name
    file_name: Optional[str] = None
    repeat: bool = False  # Duplicate in Knowledge Base
    repeat_file_name: Optional[str] = None  # Returns the file name of a duplicate file if it is a duplicate
    repeat_update_time: Optional[datetime] = None  # Returns the update time of a duplicate file if it is a duplicate


class StreamData(BaseModel):
    event: str
    data: dict | str

    def __str__(self) -> str:
        if isinstance(self.data, dict):
            return f'event: {self.event}\ndata: {orjson.dumps(self.data).decode()}\n\n'
        return f'event: {self.event}\ndata: {self.data}\n\n'


class CreateComponentReq(BaseModel):
    name: str = Field(max_length=50, description='Component Name')
    data: Any = Field(default='', description='Component Data')
    description: Optional[str] = Field(default='', description='DESCRIPTION')


class CustomComponentCode(BaseModel):
    code: str
    field: Optional[str] = None
    frontend_node: Optional[dict] = None


class AssistantCreateReq(BaseModel):
    name: str = Field(max_length=50, description='The assistant name.')
    prompt: str = Field(min_length=20, max_length=1000, description='Helper Prompt')
    logo: str = Field(description='logoRelative address of the file')


class AssistantUpdateReq(BaseModel):
    id: str = Field(description='assistantID')
    name: Optional[str] = Field('', description='The assistant name. Leave empty to not update')
    desc: Optional[str] = Field('', description='Assistant description Leave empty to not update')
    logo: Optional[str] = Field('', description='logoRelative address of the file, empty to not update')
    prompt: Optional[str] = Field('', description='Visible to Userprompt， Leave empty to not update')
    guide_word: Optional[str] = Field('', description='Ice Breaker  Leave empty to not update')
    guide_question: Optional[List] = Field([], description='Guided Question List, Leave empty to not update')
    model_name: Optional[str] = Field('', description='Selected model name, Leave empty to not update')
    temperature: Optional[float] = Field(None, description='Model Temperature, Do not pass or do not update')
    max_token: Optional[int] = Field(32000, description='MaxtokenQuantity Do not pass or do not update')

    tool_list: List[int] | None = Field(default=None,
                                        description='Tools for assistantsIDVertical,An empty list empties the bound tool forNonethen do not update')
    flow_list: List[str] | None = Field(default=None,
                                        description="Assistant's SkillsIDVertical,An empty list clears the bound skills forNonethen do not update")
    knowledge_list: List[int] | None = Field(default=None,
                                             description='The knowledge base uponIDlist, forNonethen do not update')

    @field_validator('model_name', mode='before')
    @classmethod
    def convert_model_name(cls, v):
        return str(v)


class AssistantSimpleInfo(BaseModel):
    id: str
    name: str
    desc: str
    logo: str
    user_id: int
    user_name: str
    status: int
    flow_type: Optional[int] = None
    write: Optional[bool] = Field(default=False)
    group_ids: Optional[List[int]] = None
    tags: Optional[List[Tag]] = None
    create_time: datetime
    update_time: datetime


class AssistantInfo(AssistantBase):
    tool_list: List[GptsToolsRead] = Field(default_factory=list, description='Tools for assistantsIDVertical')
    flow_list: List[FlowRead] = Field(default_factory=list, description='Skills for assistantsIDVertical')
    knowledge_list: List[KnowledgeRead] = Field(default_factory=list, description='The knowledge base uponIDVertical')


class FlowVersionCreate(BaseModel):
    name: Optional[str] = Field(default=None, description='Version Name')
    description: Optional[str] = Field(default=None, description='Version description')
    data: Optional[Dict] = Field(default=None, description='Skill Version Node Data Data')
    original_version_id: Optional[int] = Field(default=None, description='Version Source VersionID')
    flow_type: Optional[int] = Field(default=1, description='Type of version')  # 1:common version 10:new Version


class FlowCompareReq(BaseModel):
    inputs: Any = Field(default=None, description='Inputs Required for Skill Run')
    question_list: List[str] = Field(default_factory=list, description='TestcaseVertical')
    version_list: List[int] = Field(default_factory=list, description='Compare VersionsIDVertical')
    node_id: str = Field(default=None, description='The nodes that need to be compared are uniqueID')
    thread_num: Optional[int] = Field(default=1, description='Compare Threads')


class DeleteToolTypeReq(BaseModel):
    tool_type_id: int = Field(description='Tool category to deleteID')


class GroupAndRoles(BaseModel):
    group_id: int
    role_ids: List[int]


class CreateUserReq(BaseModel):
    user_name: str = Field(max_length=30, description='Username')
    password: str = Field(description='Passwords')
    group_roles: List[GroupAndRoles] = Field(description='List of user groups and roles to join')


class OpenAIChatCompletionReq(BaseModel):
    messages: List[dict] = Field(...,
                                 description='Chat message list, only supporteduser、assistant。systemUse data from within the database')
    model: str = Field(..., description='The only assistantID')
    n: int = Field(default=1,
                   description='Number of answers returned, The assistant side defaults to1, multiple answers are not supported at this time')
    stream: bool = Field(default=False, description='Whether to turn on streaming replies')
    temperature: float = Field(default=0.0,
                               description="Model Temperature, Incoming0or don't post means don't overwrite")
    tools: List[dict] = Field(default_factory=list,
                              description='Tools List, The assistant is temporarily unsupported, use the configuration of the assistant')


class OpenAIChoice(BaseModel):
    index: int = Field(..., description='Index of options')
    message: dict = Field(default=None, description='The corresponding message content matches the format of the input')
    finish_reason: str = Field(default='stop', description='End Reason, Assistants onlystop')
    delta: dict = Field(default=None, description='counterpart&apos;sopenaiStreaming Return Message Content')


class OpenAIChatCompletionResp(BaseModel):
    id: str = Field(..., description='The only one requestedID')
    object: str = Field(default='chat.completion', description='Type of posts to return.')
    created: int = Field(default=..., description='Returned creation timestamp')
    model: str = Field(..., description="returned model, corresponding to the assistant'sid")
    choices: List[OpenAIChoice] = Field(..., description='Back to answers list')
    usage: dict = Field(default=None, description='Various of concerntokenQuantity, Assistant This value is empty')
    system_fingerprint: Optional[str] = Field(default=None, description='System Fingerprint')


class Icon(BaseModel):
    enabled: bool
    image: Optional[str] = None
    relative_path: Optional[str] = None


class WSModel(BaseModel):
    key: Optional[str] = None
    id: str
    name: Optional[str] = None
    displayName: Optional[str] = None
    visual: Optional[bool] = False


class WSPrompt(BaseModel):
    enabled: bool
    prompt: Optional[str] = None
    model: Optional[str] = None
    tool: Optional[str] = None  # Enumeration of tools
    params: Optional[dict] = None  # Tools Input Parameters
    bingKey: Optional[str] = None
    bingUrl: Optional[str] = None


class LinsightConfig(BaseModel):
    """
    Ideas Management Configuration
    """
    linsight_entry: bool = Field(default=True, description='Whether to open the Ideas entrance')
    input_placeholder: str = Field(..., description='Input Box Prompt')
    tools: Optional[List[Dict]] = Field(None, description='List of optional tools for Ideas')


class WorkstationConfig(BaseModel):
    maxTokens: Optional[int] = Field(default=1500, description='MaxtokenQuantity')
    sidebarIcon: Optional[Icon] = None
    assistantIcon: Optional[Icon] = None
    sidebarSlogan: Optional[str] = Field(default='', description='Sidebarslogan')
    welcomeMessage: Optional[str] = Field(default='')
    functionDescription: Optional[str] = Field(default='')
    inputPlaceholder: Optional[str] = ''
    models: Optional[Union[List[WSModel], str]] = None
    voiceInput: Optional[WSPrompt] = None
    webSearch: Optional[WSPrompt] = None
    knowledgeBase: Optional[WSPrompt] = None
    fileUpload: Optional[WSPrompt] = None
    systemPrompt: Optional[str] = None
    applicationCenterWelcomeMessage: Optional[str] = Field(default='', max_length=1000,
                                                           pattern=r'^[\u4e00-\u9fff\w\s\.,;:!@#$%^&*()\-_=+\[\]{}|\\\'"<>/?`~·！￥（）【】、《》，。；：“”‘’？]+$',
                                                           description='App Center Welcome Message')
    applicationCenterDescription: Optional[str] = Field(default='', max_length=1000,
                                                        pattern=r'^[\u4e00-\u9fff\w\s\.,;:!@#$%^&*()\-_=+\[\]{}|\\\'"<>/?`~·！￥（）【】、《》，。；：“”‘’？]+$',
                                                        description='App Center Description')
    linsightConfig: Optional[LinsightConfig] = Field(default=None, description='Inspiration Configuration')


class ExcelRule(BaseModel):
    slice_length: Optional[int] = Field(default=10, description='Data Line')
    header_start_row: Optional[int] = Field(default=1, description='Table header start')
    header_end_row: Optional[int] = Field(default=1, description='End of header')
    append_header: Optional[int] = Field(default=1, description='Whether to add a header')


# File Split Request Base Parameters
class FileProcessBase(BaseModel):
    knowledge_id: int = Field(..., description='The knowledge base uponID')
    separator: Optional[List[str]] = Field(default=None,
                                           description='Split text rule, If not passed on, it is the default')
    separator_rule: Optional[List[str]] = Field(default=None,
                                                description='Segmentation before or after the segmentation rule;before/after')
    chunk_size: Optional[int] = Field(default=1000, description='Split text length, default if not passed')
    chunk_overlap: Optional[int] = Field(default=100, description='Split text overlap length, default if not passed')
    retain_images: Optional[int] = Field(default=1, description='Keep document image')
    force_ocr: Optional[int] = Field(default=0, description='EnableOCR')
    enable_formula: Optional[int] = Field(default=1, description='latexFormula Recognition')
    filter_page_header_footer: Optional[int] = Field(default=0, description='Filter Header Footer')
    excel_rule: Optional[ExcelRule] = Field(default=None, description="excel rule")
    cache: Optional[bool] = Field(default=True,
                                  description='Whether to fetch data from the cache when previewing the document')

    @model_validator(mode='before')
    @classmethod
    def check_separator_rule(cls, values: Any):
        if not values.get('separator', None):
            values['separator'] = ['\n\n', '\n']
        if not values.get('separator_rule', None):
            values['separator_rule'] = ['after' for _ in values['separator']]
        if values.get('chunk_size', None) is None:
            values['chunk_size'] = 1000
        if values.get('chunk_overlap') is None:
            values['chunk_overlap'] = 100
        if values.get('filter_page_header_footer') is None:
            values['filter_page_header_footer'] = 0
        if values.get('force_ocr') is None:
            values['force_ocr'] = 1
        if values.get('enable_formula') is None:
            values['enable_formula'] = 1
        if values.get("retain_images") is None:
            values['retain_images'] = 1
        if values.get("excel_rule") is None:
            values['excel_rule'] = ExcelRule()
        if values.get("knowledge_id") is None:
            raise ValueError('knowledge_id is required')

        return values


# File chunked data format
class FileChunk(BaseModel):
    text: str = Field(..., description='Text block Content')
    parse_type: Optional[str] = Field(default=None, description='File parsing type to which the text belongs')
    metadata: Metadata = Field(..., description='Text block metadata')


# Preview File Chunked Content Request Parameters
class PreviewFileChunk(FileProcessBase):
    file_path: str = Field(..., description='FilePath')
    cache: bool = Field(default=True, description='Whether to fetch from cache')
    excel_rule: Optional[ExcelRule] = Field(default=None, description="excel rule")


class UpdatePreviewFileChunk(BaseModel):
    knowledge_id: int = Field(..., description='The knowledge base uponID')
    file_path: str = Field(..., description='FilePath')
    text: str = Field(..., description='Text block Content')
    chunk_index: int = Field(..., description='Text block index, Insidemetadatamile')
    bbox: Optional[str] = Field(default='', description='Text blocksbboxMessage')


class KnowledgeFileOne(BaseModel):
    file_path: str = Field(..., description='FilePath')
    excel_rule: Optional[ExcelRule] = Field(default=None, description="Excel rules")


# Knowledge Base File Processing
class KnowledgeFileProcess(FileProcessBase):
    file_list: List[KnowledgeFileOne] = Field(..., description='List of files')
    callback_url: Optional[str] = Field(default=None, description='Asynchronous Task Callback Address')
    extra: Optional[str] = Field(default=None, description='Additional Information')


# Knowledge Base Re-Segment Adjustment
class KnowledgeFileReProcess(FileProcessBase):
    kb_file_id: int = Field(..., description='Knowledge Base FilesID')
    file_path: str = Field(default="", description='FilePath')
    excel_rule: Optional[ExcelRule] = Field(default=None, description="Excel rules")
    callback_url: Optional[str] = Field(default=None, description='Asynchronous Task Callback Address')
    extra: Optional[Dict] = Field(default=None, description='Additional Information')


class FrequentlyUsedChat(BaseModel):
    user_link_type: str = Field(..., description='User-associatedtype')
    type_detail: str = Field(..., description='User-associatedtype_id')


class UpdateKnowledgeReq(BaseModel):
    """Update Knowledge Base Model Request"""
    model_id: int = Field(..., description='embeddingModelsID')
    model_type: Optional[str] = Field(default=None,
                                      description='Model type, when not passed on, it will be based onmodel_idAuto Query')
    knowledge_id: Optional[int] = Field(default=None,
                                        description='The knowledge base uponID, if empty, update all private repositories')
    knowledge_name: Optional[str] = Field(default=None, description='Library Name')
    description: Optional[str] = Field(default=None, description='KB Description')
