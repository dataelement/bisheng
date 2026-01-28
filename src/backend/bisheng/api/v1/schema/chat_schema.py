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


class UseKnowledgeBaseParam(BaseModel):
    personal_knowledge_enabled: Optional[bool] = False
    organization_knowledge_ids: Optional[List[int]] = []

    @field_validator('organization_knowledge_ids', mode='before')
    @classmethod
    def convert_organization_knowledge_ids(cls, v: Any):
        if len(v) > 20:
            raise ValueError('Can only be used up to20organization knowledge base')

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
    search_enabled: Optional[bool] = False
    use_knowledge_base: Optional[UseKnowledgeBaseParam] = None
    files: Optional[List[Dict]] = None
    parentMessageId: Optional[str] = None
    overrideParentMessageId: Optional[str] = None
    responseMessageId: Optional[str] = None


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
    def from_chat_message_objs(cls, chat_messages: List[ChatMessage], user_model: User,
                               message_session: MessageSession):
        return [
            cls.model_validate(obj).model_copy(
                update={"user_name": user_model.user_name, "flow_name": message_session.flow_name}) for obj in
            chat_messages
        ]
