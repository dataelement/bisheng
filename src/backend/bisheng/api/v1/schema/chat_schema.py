import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from bisheng.database.models.message import ChatMessage, ChatMessageQuery
from bisheng.database.models.session import MessageSession
from bisheng.user.domain.models.user import User


class AppChatFeedback(BaseModel):
    message_id: int
    comment: str
    liked: int = 0


class AppChatList(BaseModel):
    flow_name: str
    user_name: str
    user_id: int
    user_external_id: str | None = None
    department_name: str = ""
    company_name: str = ""
    office_name: str = ""
    chat_id: str
    flow_id: str
    flow_type: int
    create_time: datetime
    like_count: int | None = None
    dislike_count: int | None = None
    copied_count: int | None = None
    comment_count: int = 0
    feedback_comments: list[AppChatFeedback] = Field(default_factory=list)
    answer_abnormal: int = 0
    sensitive_status: int | None = None  # Sensitive word review status
    user_groups: list[Any] | None = None  # Groups to which the user belongs
    mark_user: str | None = None
    mark_status: int | None = None
    mark_id: int | None = None
    messages: list[dict] | None = None  # All message list data for the session

    @field_validator("user_name", mode="before")
    @classmethod
    def convert_user_name(cls, v: Any):
        if not isinstance(v, str):
            return str(v)
        return v


class APIAddQAParam(BaseModel):
    question: str
    answer: list[str]
    relative_questions: list[str] | None = []


class ToolPayload(BaseModel):
    """v2.5: frontend tool selection passed on each chat_completions request.

    Selection order:
      - id, tool_key come from the workstation config's tools[] list (the
        admin-configured available tools); the client sends whichever ones
        the user toggled on.
      - type is always 'tool' for now — knowledge bases are passed separately
        through `use_knowledge_base` to preserve existing semantics.
    """

    id: int = 0
    tool_key: str | None = None
    type: str = "tool"


class KnowledgeScopeFileRef(BaseModel):
    knowledge_space_id: int
    file_id: int


class KnowledgeScopeFolderRef(BaseModel):
    knowledge_space_id: int
    folder_id: int


class KnowledgeScopeParam(BaseModel):
    mode: Literal["none", "knowledge_space", "files"] = "none"
    knowledge_space_id: int | None = None
    folder_refs: list[KnowledgeScopeFolderRef] | None = []
    file_refs: list[KnowledgeScopeFileRef] | None = []


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: bool | None = False
    organization_knowledge_ids: list[int] | None = []
    knowledge_space_ids: list[int] | None = []
    knowledge_scope: KnowledgeScopeParam | None = None

    @field_validator("organization_knowledge_ids", mode="before")
    @classmethod
    def convert_organization_knowledge_ids(cls, v: Any):
        if v is None:
            return []
        if len(v) > 50:
            raise ValueError("Can only be used up to 50 organization knowledge base")

        return v

    @field_validator("knowledge_space_ids", mode="before")
    @classmethod
    def convert_knowledge_space_ids(cls, v: Any):
        if v is None:
            return []

        return v


class APIChatCompletion(BaseModel):
    clientTimestamp: str
    conversationId: str | None = None
    error: bool | None = False
    generation: str | None = ""
    isCreatedByUser: bool | None = False
    isContinued: bool | None = False
    model: str
    text: str | None = ""

    # --- v2.5: new Agent-mode fields ---
    # User's currently-toggled tools in the chat input (workstation.tools subset).
    # When non-empty, the backend routes through the LangGraph ReAct agent loop.
    # When empty/absent, behaviour falls back to a plain bisheng_llm.astream call.
    tools: list[ToolPayload] | None = None

    # --- Preserved (new code-path also honours use_knowledge_base / files) ---
    use_knowledge_base: UseKnowledgeBaseParam | None = None
    files: list[dict] | None = None

    # --- DEPRECATED (kept for backward compatibility; ignored by new Agent flow) ---
    search_enabled: bool | None = False  # legacy web-search mutex flag
    parentMessageId: str | None = None  # legacy tree branching
    overrideParentMessageId: str | None = None  # legacy regenerate pointer
    responseMessageId: str | None = None

    @field_validator("parentMessageId", "overrideParentMessageId", "responseMessageId", mode="before")
    @classmethod
    def _coerce_optional_str_id(cls, v: Any):
        # Frontend occasionally sends numeric DB ids here — coerce to str so
        # Pydantic's strict mode doesn't 422 the whole SSE request.
        if v is None or isinstance(v, str):
            return v
        return str(v)


class delta(BaseModel):
    id: str | None
    delta: dict


class SSEResponse(BaseModel):
    event: str
    data: delta

    def toString(self) -> str:
        return f"event: message\ndata: {json.dumps(self.dict())}\n\n"


class ChatMessageHistoryResponse(ChatMessageQuery):
    user_name: str | None = None
    flow_name: str | None = None

    @classmethod
    def from_chat_message_objs(
        cls, chat_messages: list[ChatMessage], user_model: User, message_session: MessageSession
    ) -> list["ChatMessageHistoryResponse"]:
        return [
            cls.model_validate(obj).model_copy(
                update={
                    "user_name": user_model.user_name,
                    "flow_name": message_session.flow_name,
                    "name": message_session.name,
                }
            )
            for obj in chat_messages
        ]
