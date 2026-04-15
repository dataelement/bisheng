import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

from bisheng.database.models.message import ChatMessage, ChatMessageQuery
from bisheng.database.models.session import MessageSession
from bisheng.user.domain.models.user import User


class AppChatList(BaseModel):
    flow_name: str
    user_name: str
    user_id: int
    chat_id: str
    flow_id: str
    flow_type: int
    create_time: datetime
    like_count: Optional[int] = None
    dislike_count: Optional[int] = None
    copied_count: Optional[int] = None
    sensitive_status: Optional[int] = None  # Sensitive word review status
    user_groups: Optional[List[Any]] = None  # Groups to which the user belongs
    mark_user: Optional[str] = None
    mark_status: Optional[int] = None
    mark_id: Optional[int] = None
    messages: Optional[List[dict]] = None  # All message list data for the session

    @field_validator('user_name', mode='before')
    @classmethod
    def convert_user_name(cls, v: Any):
        if not isinstance(v, str):
            return str(v)
        return v


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]
    relative_questions: Optional[List[str]] = []


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
    tool_key: Optional[str] = None
    type: str = 'tool'


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: Optional[bool] = False
    organization_knowledge_ids: Optional[List[int]] = []
    knowledge_space_ids: Optional[List[int]] = []

    @field_validator('organization_knowledge_ids', mode='before')
    @classmethod
    def convert_organization_knowledge_ids(cls, v: Any):
        if len(v) > 50:
            raise ValueError('Can only be used up to 50 organization knowledge base')

        return v

    @field_validator('knowledge_space_ids', mode='before')
    @classmethod
    def convert_knowledge_space_ids(cls, v: Any):
        if len(v) > 50:
            raise ValueError('Can only be used up to 50 knowledge space')

        return v


class APIChatCompletion(BaseModel):
    clientTimestamp: str
    conversationId: Optional[str] = None
    error: Optional[bool] = False
    generation: Optional[str] = ''
    isCreatedByUser: Optional[bool] = False
    isContinued: Optional[bool] = False
    model: str
    text: Optional[str] = ''

    # --- v2.5: new Agent-mode fields ---
    # User's currently-toggled tools in the chat input (workstation.tools subset).
    # When non-empty, the backend routes through the LangGraph ReAct agent loop.
    # When empty/absent, behaviour falls back to a plain bisheng_llm.astream call.
    tools: Optional[List[ToolPayload]] = None

    # --- Preserved (new code-path also honours use_knowledge_base / files) ---
    use_knowledge_base: Optional[UseKnowledgeBaseParam] = None
    files: Optional[List[Dict]] = None

    # --- DEPRECATED (kept for backward compatibility; ignored by new Agent flow) ---
    search_enabled: Optional[bool] = False  # legacy web-search mutex flag
    parentMessageId: Optional[str] = None  # legacy tree branching
    overrideParentMessageId: Optional[str] = None  # legacy regenerate pointer
    responseMessageId: Optional[str] = None

    @field_validator('parentMessageId', 'overrideParentMessageId', 'responseMessageId', mode='before')
    @classmethod
    def _coerce_optional_str_id(cls, v: Any):
        # Frontend occasionally sends numeric DB ids here — coerce to str so
        # Pydantic's strict mode doesn't 422 the whole SSE request.
        if v is None or isinstance(v, str):
            return v
        return str(v)


class delta(BaseModel):
    id: Optional[str]
    delta: Dict


class SSEResponse(BaseModel):
    event: str
    data: delta

    def toString(self) -> str:
        return f'event: message\ndata: {json.dumps(self.dict())}\n\n'


class ChatMessageHistoryResponse(ChatMessageQuery):
    user_name: Optional[str] = None
    flow_name: Optional[str] = None

    @classmethod
    def from_chat_message_objs(
            cls,
            chat_messages: List[ChatMessage],
            user_model: User,
            message_session: MessageSession
    ) -> List["ChatMessageHistoryResponse"]:
        return [
            cls.model_validate(obj).model_copy(
                update={
                    "user_name": user_model.user_name,
                    "flow_name": message_session.flow_name,
                    "name": message_session.name
                }
            )
            for obj in chat_messages
        ]
