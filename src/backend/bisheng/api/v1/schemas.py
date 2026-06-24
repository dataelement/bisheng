from datetime import datetime
from enum import Enum
from typing import Any, Generic, Literal, TypeVar, Union

from langchain_classic.docstore.document import Document
from orjson import orjson
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema
from bisheng.database.models.assistant import AssistantBase
from bisheng.database.models.flow import FlowCreate, FlowRead, FlowType
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
    documents: list[Document]


class BuildStatus(Enum):
    """Status of the build."""

    SUCCESS = "success"
    FAILURE = "failure"
    STARTED = "started"
    IN_PROGRESS = "in_progress"


class GraphData(BaseModel):
    """Data inside the exported flow."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class ExportedFlow(BaseModel):
    """Exported flow from bisheng."""

    description: str
    name: str
    id: str
    data: GraphData


class InputRequest(BaseModel):
    input: str = Field(description="question or command asked LLM to do")


class TweaksRequest(BaseModel):
    tweaks: dict[str, dict[str, str]] | None = Field(default_factory=dict, description="List of dictionaries")


class UpdateTemplateRequest(BaseModel):
    template: dict


# Create generic variables
DataT = TypeVar("DataT")


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """Unified Response Model"""

    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None, message: str = "SUCCESS") -> UnifiedResponseModel:
    """Success code"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)
    # return data


def resp_500(
    code: int = 500, data: Union[list, dict, str, Any] = None, message: str = "BAD REQUEST"
) -> UnifiedResponseModel:
    """Wrong logical response"""
    return UnifiedResponseModel(status_code=code, status_message=message, data=data)


class ProcessResponse(BaseModel):
    """Process response schema."""

    result: Any = None
    # task: Optional[TaskResponse] = None
    session_id: str | None = None
    backend: str | None = None


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

    name: str = None
    flow_name: str = None
    flow_description: str = None
    flow_id: str = None
    chat_id: str = None
    create_time: datetime = None
    update_time: datetime = None
    flow_type: int = None
    latest_message: ChatMessageRead | None = None
    logo: str | None = None


class ChatListGroup(BaseModel):
    """Chat list grouped by time dimension."""

    group_name: str = Field(description='Group display name, e.g. "今天", "昨天", "2025"')
    group_key: str = Field(description='Group identifier, e.g. "today", "yesterday", "year_2025"')
    sessions: list[ChatList] = Field(default_factory=list, description="List of chat sessions in this group")


class FlowGptsOnlineList(BaseModel):
    id: str = Field("Uniqueness quantificationID")
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
    message: Union[str, None, dict, list] = ""
    type: str = "human"
    category: str = "processing"  # system processing answer tool
    intermediate_steps: str | None = None
    files: list | None = []
    user_id: int | None = None
    message_id: int | str | None = None
    source: int | None = 0
    sender: str | None = None
    receiver: dict | None = None
    liked: int = 0
    extra: str | dict | None = "{}"
    flow_id: str | None = None
    chat_id: str | None = None


class ChatResponse(ChatMessage):
    """Chat response schema."""

    intermediate_steps: str | None = ""
    is_bot: bool | int = True
    category: str = "processing"
    citations: list[CitationRegistryItemSchema] | None = None
    citation_registry_items: list[CitationRegistryItemSchema] | None = None

    @field_validator("type")
    @classmethod
    def validate_message_type(cls, v):
        """
        end_cover: End & Overwrite Previousmessage
        """
        if v not in ["start", "stream", "end", "error", "info", "file", "begin", "close", "end_cover", "over"]:
            raise ValueError("type must be start, stream, end, error, info, or file")
        return v


class FileResponse(ChatMessage):
    """File response schema."""

    data: Any = None
    data_type: str
    type: str = "file"
    is_bot: bool = True

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, v):
        if v not in ["image", "csv"]:
            raise ValueError("data_type must be image or csv")
        return v


class FlowListCreate(BaseModel):
    flows: list[FlowCreate]


class FlowListRead(BaseModel):
    flows: list[FlowRead]


class InitResponse(BaseModel):
    flowId: str


class BuiltResponse(BaseModel):
    built: bool


class UploadFileResponse(BaseModel):
    """Upload file response schema."""

    flowId: str | None = None
    file_path: str
    relative_path: str | None = None  # minioRelative path, i.e.object_name
    file_name: str | None = None
    repeat: bool = False  # Duplicate in Knowledge Base
    repeat_file_name: str | None = None  # Returns the file name of a duplicate file if it is a duplicate
    repeat_update_time: datetime | None = None  # Returns the update time of a duplicate file if it is a duplicate


class StreamData(BaseModel):
    event: str
    data: dict | str

    def __str__(self) -> str:
        if isinstance(self.data, dict):
            return f"event: {self.event}\ndata: {orjson.dumps(self.data).decode()}\n\n"
        return f"event: {self.event}\ndata: {self.data}\n\n"


class CreateComponentReq(BaseModel):
    name: str = Field(max_length=50, description="Component Name")
    data: Any = Field(default="", description="Component Data")
    description: str | None = Field(default="", description="DESCRIPTION")


class CustomComponentCode(BaseModel):
    code: str
    field: str | None = None
    frontend_node: dict | None = None


class AssistantCreateReq(BaseModel):
    name: str = Field(max_length=50, description="The assistant name.")
    prompt: str = Field(min_length=20, max_length=1000, description="Helper Prompt")
    logo: str = Field(description="logoRelative address of the file")


class AssistantUpdateReq(BaseModel):
    id: str = Field(description="assistantID")
    name: str | None = Field("", description="The assistant name. Leave empty to not update")
    desc: str | None = Field("", description="Assistant description Leave empty to not update")
    logo: str | None = Field("", description="logoRelative address of the file, empty to not update")
    prompt: str | None = Field("", description="Visible to Userprompt， Leave empty to not update")
    guide_word: str | None = Field("", description="Ice Breaker  Leave empty to not update")
    guide_question: list | None = Field([], description="Guided Question List, Leave empty to not update")
    model_name: str | None = Field("", description="Selected model name, Leave empty to not update")
    temperature: float | None = Field(None, description="Model Temperature, Do not pass or do not update")
    max_token: int | None = Field(32000, description="MaxtokenQuantity Do not pass or do not update")

    tool_list: list[int] | None = Field(
        default=None,
        description="Tools for assistantsIDVertical,An empty list empties the bound tool forNonethen do not update",
    )
    flow_list: list[str] | None = Field(
        default=None,
        description="Assistant's SkillsIDVertical,An empty list clears the bound skills forNonethen do not update",
    )
    knowledge_list: list[int] | None = Field(
        default=None, description="The knowledge base uponIDlist, forNonethen do not update"
    )

    @field_validator("model_name", mode="before")
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
    flow_type: int | None = None
    write: bool | None = Field(default=False)
    group_ids: list[int] | None = None
    tags: list[Tag] | None = None
    create_time: datetime
    update_time: datetime


class AssistantInfo(AssistantBase):
    tool_list: list[GptsToolsRead] = Field(default_factory=list, description="Tools for assistantsIDVertical")
    flow_list: list[FlowRead] = Field(default_factory=list, description="Skills for assistantsIDVertical")
    knowledge_list: list[KnowledgeRead] = Field(default_factory=list, description="The knowledge base uponIDVertical")
    can_share: bool = Field(
        default=False, description="Current user may copy app share link (relation-model share_app)"
    )


class FlowVersionCreate(BaseModel):
    name: str | None = Field(default=None, description="Version Name")
    description: str | None = Field(default=None, description="Version description")
    data: dict | None = Field(default=None, description="Skill Version Node Data Data")
    original_version_id: int | None = Field(default=None, description="Version Source VersionID")
    flow_type: int | None = Field(default=FlowType.WORKFLOW.value, description="Type of version")  # 10:new Version


class FlowCompareReq(BaseModel):
    inputs: Any = Field(default=None, description="Inputs Required for Skill Run")
    question_list: list[str] = Field(default_factory=list, description="TestcaseVertical")
    version_list: list[int] = Field(default_factory=list, description="Compare VersionsIDVertical")
    node_id: str = Field(default=None, description="The nodes that need to be compared are uniqueID")
    thread_num: int | None = Field(default=1, description="Compare Threads")


class DeleteToolTypeReq(BaseModel):
    tool_type_id: int = Field(description="Tool category to deleteID")


class GroupAndRoles(BaseModel):
    group_id: int
    role_ids: list[int]


class CreateUserReq(BaseModel):
    user_name: str = Field(max_length=30, description="Username")
    password: str = Field(description="Passwords")
    group_roles: list[GroupAndRoles] = Field(
        default_factory=list,
        description="Optional user groups and roles; roles default to normal user when empty",
    )


class OpenAIChatCompletionReq(BaseModel):
    messages: list[dict] = Field(
        ..., description="Chat message list, only supporteduser、assistant。systemUse data from within the database"
    )
    model: str = Field(..., description="The only assistantID")
    n: int = Field(
        default=1,
        description="Number of answers returned, The assistant side defaults to1, multiple answers are not supported at this time",
    )
    stream: bool = Field(default=False, description="Whether to turn on streaming replies")
    temperature: float = Field(
        default=0.0, description="Model Temperature, Incoming0or don't post means don't overwrite"
    )
    tools: list[dict] = Field(
        default_factory=list,
        description="Tools List, The assistant is temporarily unsupported, use the configuration of the assistant",
    )


class OpenAIChoice(BaseModel):
    index: int = Field(..., description="Index of options")
    message: dict = Field(default=None, description="The corresponding message content matches the format of the input")
    finish_reason: str = Field(default="stop", description="End Reason, Assistants onlystop")
    delta: dict = Field(default=None, description="counterpart&apos;sopenaiStreaming Return Message Content")


class OpenAIChatCompletionResp(BaseModel):
    id: str = Field(..., description="The only one requestedID")
    object: str = Field(default="chat.completion", description="Type of posts to return.")
    created: int = Field(default=..., description="Returned creation timestamp")
    model: str = Field(..., description="returned model, corresponding to the assistant'sid")
    choices: list[OpenAIChoice] = Field(..., description="Back to answers list")
    usage: dict = Field(default=None, description="Various of concerntokenQuantity, Assistant This value is empty")
    system_fingerprint: str | None = Field(default=None, description="System Fingerprint")


class Icon(BaseModel):
    enabled: bool
    image: str | None = None
    relative_path: str | None = None


class WSModel(BaseModel):
    key: str | None = None
    id: str
    name: str | None = None
    displayName: str | None = None
    visual: bool | None = False


class WSPrompt(BaseModel):
    enabled: bool
    prompt: str | None = None


# v2.5 Agent Mode: Available Tool Group (shape mirrors LinSight linsight_config.tools).
# The daily-chat input bar resolves individual tools from `children[]`; the parent
# row only stores display metadata and per-group `default_checked`.
class ToolConfig(BaseModel):
    """Available tool group item for the daily-chat Agent input bar."""

    id: int = Field(description="GptsToolsType.id (parent type id)")
    name: str = Field(description="Display name shown in the UI")
    is_preset: int | None = Field(default=None, description="0=custom, 1=builtin, 2=mcp")
    description: str | None = Field(default=None)
    default_checked: bool = Field(default=False, description="Initial checked state for new sessions")
    children: list[dict] = Field(default_factory=list, description="Selected leaf tools: [{id, name, tool_key, desc}]")


# v2.5 Agent Mode: Configured Organizational Knowledge Base Items
class OrgKbConfig(BaseModel):
    """Organization knowledge-base item surfaced in the PlusMenu."""

    id: int = Field(description="Knowledge.id")
    name: str = Field(description="Knowledge-base display name")
    type: int | None = Field(default=None, description="Knowledge type: 0=doc, 1=qa")
    default_checked: bool = Field(default=False, description="Initial checked state for new sessions")
    sort_order: int = Field(default=0, description="Display order (ascending)")


# linsight Configuration
class LinsightConfig(BaseModel):
    """
    Ideas Management Configuration
    """

    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True)

    linsight_entry: bool = Field(default=True, description="Whether to open the Ideas entrance")
    input_placeholder: str = Field(..., description="Input Box Prompt")
    tools: list[dict] | None = Field(default=None, description="List of optional tools for Ideas")
    tab_display_name: str | None = Field(default="Linsight", description="Tab Display Name")


# Daily Chat Configuration
class WorkstationConfig(BaseModel):
    model_config = ConfigDict(validate_by_alias=True, validate_by_name=True, validate_assignment=True)

    tabDisplayName: str | None = Field(default="", alias="tabDisplayName", description="Tab Display Name")
    maxTokens: int | None = Field(default=15000, description="Max chunk size for knowledge rag or web search")
    sidebarIcon: Icon | None = None
    assistantIcon: Icon | None = None
    welcomeMessage: str | None = Field(default="")
    functionDescription: str | None = Field(default="")
    inputPlaceholder: str | None = ""
    models: Union[list[WSModel], str] | None = None
    # --- Legacy: kept for backward compatibility during rollout ---
    webSearch: WSPrompt | None = None  # DEPRECATED, superseded by `tools`
    knowledgeBase: WSPrompt | None = None
    fileUpload: WSPrompt | None = None
    # F035 (v2.6): gate for the client 添加技能 (Add Skill) entry. Defaults to
    # off — the entry only shows in the input when admin enables it.
    skillEntry: WSPrompt | None = None
    systemPrompt: str | None = None
    # --- v2.5 Agent-mode additions ---
    tools: list[ToolConfig] | None = Field(
        default=None,
        description="Available tools for the chat input bar (max 20 enforced by UI)",
    )
    orgKbs: list[OrgKbConfig] | None = Field(
        default=None,
        description="Configured organization knowledge bases surfaced in the PlusMenu",
    )
    applicationCenterWelcomeMessage: str | None = Field(
        default="",
        max_length=1000,
        pattern=r'^[\u4e00-\u9fff\w\s\.,;:!@#$%^&*()\-_=+\[\]{}|\\\'"<>/?`~·！￥（）【】、《》，。；：“”‘’？]+$',
        description="App Center Welcome Message",
    )
    applicationCenterDescription: str | None = Field(
        default="",
        max_length=1000,
        pattern=r'^[\u4e00-\u9fff\w\s\.,;:!@#$%^&*()\-_=+\[\]{}|\\\'"<>/?`~·！￥（）【】、《》，。；：“”‘’？]+$',
        description="App Center Description",
    )
    recommendedApps: list[str] | None = Field(
        default=None, description="Ordered list of recommended app IDs configured by admin"
    )


class SubscriptionConfig(BaseModel):
    system_prompt: str | None = Field(default="", description="System Prompt")
    user_prompt: str | None = Field(default="", description="User Prompt")
    max_chunk_size: int | None = Field(default=15000, description="Max chunk size for file chunks")
    feedback_tips: str | None = Field(default="", description="Feedback Tips")
    # Custom display name for the AI assistant on the subscription/channel chat
    # surface. Empty means the client falls back to its localized default ("AI 助手").
    assistant_name: str | None = Field(
        default="", description="AI assistant display name on the subscription surface; empty = client i18n default"
    )


class KnowledgeSpaceConfig(BaseModel):
    system_prompt: str | None = Field(default="", description="System Prompt")
    user_prompt: str | None = Field(default="", description="User Prompt")
    max_chunk_size: int | None = Field(default=15000, description="Max chunk size for file chunks")
    auto_tag_visible: bool | None = Field(
        default=False,
        description="Whether the knowledge-space auto-tag UI is visible to users in this tenant",
    )
    # Custom display name for the AI assistant on the knowledge-space chat surface.
    # Empty means the client falls back to its localized default ("AI 助手").
    assistant_name: str | None = Field(
        default="", description="AI assistant display name on the knowledge-space surface; empty = client i18n default"
    )


class ExcelRule(BaseModel):
    slice_length: int | None = Field(default=10, description="Data Line")
    header_start_row: int | None = Field(default=1, description="Table header start")
    header_end_row: int | None = Field(default=1, description="End of header")
    append_header: int | None = Field(default=1, description="Whether to add a header")


# File Split Request Base Parameters
class FileProcessBase(BaseModel):
    knowledge_id: int = Field(..., description="The knowledge base uponID")
    split_mode: Literal["auto", "custom", "hierarchical"] = Field(
        default="auto", description="Document split mode: auto/custom/hierarchical"
    )
    separator: list[str] | None = Field(
        default=None, description="Split text rule, If not passed on, it is the default"
    )
    separator_rule: list[str] | None = Field(
        default=None, description="Segmentation before or after the segmentation rule;before/after"
    )
    chunk_size: int | None = Field(default=1000, description="Split text length, default if not passed")
    chunk_overlap: int | None = Field(default=100, description="Split text overlap length, default if not passed")
    hierarchy_level: int | None = Field(default=3, ge=1, le=6, description="Max hierarchy level to retain")
    append_title: bool | None = Field(default=False, description="Whether to prepend title path to chunk text")
    max_chunk_size: int | None = Field(default=1000, ge=1, description="Max chunk size for hierarchical mode")
    retain_images: int | None = Field(default=1, description="Keep document image")
    force_ocr: int | None = Field(default=0, description="EnableOCR")
    enable_formula: int | None = Field(default=1, description="latexFormula Recognition")
    filter_page_header_footer: int | None = Field(default=0, description="Filter Header Footer")
    excel_rule: ExcelRule | None = Field(default=None, description="excel rule")
    cache: bool | None = Field(
        default=True, description="Whether to fetch data from the cache when previewing the document"
    )

    @model_validator(mode="before")
    @classmethod
    def check_separator_rule(cls, values: Any):
        if values.get("split_mode") is None:
            values["split_mode"] = "auto"
        if not values.get("separator", None):
            values["separator"] = ["\n\n", "\n", "。", "\\."]
        if not values.get("separator_rule", None):
            values["separator_rule"] = ["after" for _ in values["separator"]]
        if values.get("chunk_size", None) is None:
            values["chunk_size"] = 1000
        if values.get("chunk_overlap") is None:
            values["chunk_overlap"] = 100
        if values.get("hierarchy_level") is None:
            values["hierarchy_level"] = 3
        if values.get("append_title") is None:
            values["append_title"] = False
        if values.get("max_chunk_size") is None:
            values["max_chunk_size"] = 1000
        if values.get("filter_page_header_footer") is None:
            values["filter_page_header_footer"] = 0
        if values.get("force_ocr") is None:
            values["force_ocr"] = 1
        if values.get("enable_formula") is None:
            values["enable_formula"] = 1
        if values.get("retain_images") is None:
            values["retain_images"] = 1
        if values.get("excel_rule") is None:
            values["excel_rule"] = ExcelRule()
        if values.get("knowledge_id") is None:
            raise ValueError("knowledge_id is required")

        return values


# File chunked data format
class FileChunk(BaseModel):
    text: str = Field(..., description="Text block Content")
    parse_type: str | None = Field(default=None, description="File parsing type to which the text belongs")
    metadata: Metadata = Field(..., description="Text block metadata")


# Preview File Chunked Content Request Parameters
class PreviewFileChunk(FileProcessBase):
    file_path: str = Field(..., description="FilePath")
    cache: bool = Field(default=True, description="Whether to fetch from cache")
    excel_rule: ExcelRule | None = Field(default=None, description="excel rule")


class UpdatePreviewFileChunk(BaseModel):
    knowledge_id: int = Field(..., description="The knowledge base uponID")
    file_path: str = Field(..., description="FilePath")
    text: str = Field(..., description="Text block Content")
    chunk_index: int = Field(..., description="Text block index, Insidemetadatamile")
    bbox: str | None = Field(default="", description="Text blocksbboxMessage")


class KnowledgeFileOne(BaseModel):
    file_path: str = Field(..., description="FilePath")
    excel_rule: ExcelRule | None = Field(default=None, description="Excel rules")


# Knowledge Base File Processing
class KnowledgeFileProcess(FileProcessBase):
    file_list: list[KnowledgeFileOne] = Field(..., description="List of files")
    callback_url: str | None = Field(default=None, description="Asynchronous Task Callback Address")
    extra: str | None = Field(default=None, description="Additional Information")


# Knowledge Base Re-Segment Adjustment
class KnowledgeFileReProcess(FileProcessBase):
    kb_file_id: int = Field(..., description="Knowledge Base FilesID")
    file_path: str = Field(default="", description="FilePath")
    excel_rule: ExcelRule | None = Field(default=None, description="Excel rules")
    callback_url: str | None = Field(default=None, description="Asynchronous Task Callback Address")
    extra: dict | None = Field(default=None, description="Additional Information")


class FrequentlyUsedChat(BaseModel):
    user_link_type: str = Field(..., description="User-associatedtype")
    type_detail: str = Field(..., description="User-associatedtype_id")


class UsedAppPin(BaseModel):
    """Schema for pinning/unpinning used apps"""

    flow_id: str = Field(..., description="Application ID to pin/unpin")


class UpdateKnowledgeReq(BaseModel):
    """Update Knowledge Base Model Request"""

    model_id: int = Field(..., description="embeddingModelsID")
    model_type: str | None = Field(
        default=None, description="Model type, when not passed on, it will be based onmodel_idAuto Query"
    )
    knowledge_id: int | None = Field(
        default=None, description="The knowledge base uponID, if empty, update all private repositories"
    )
    knowledge_name: str | None = Field(default=None, description="Library Name")
    description: str | None = Field(default=None, description="KB Description")
