import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from bisheng.core.storage.browser_object_path import rewrite_current_browser_object_text
from bisheng.database.models.message import ChatMessage, ChatMessageQuery
from bisheng.database.models.session import MessageSession
from bisheng.user.domain.models.user import User
from bisheng.workstation.domain.schemas.chat import (
    APIChatCompletion as APIChatCompletion,
)
from bisheng.workstation.domain.schemas.chat import (
    ToolPayload as ToolPayload,
)
from bisheng.workstation.domain.schemas.chat import (
    UseKnowledgeBaseParam as UseKnowledgeBaseParam,
)


class AppChatList(BaseModel):
    flow_name: str
    user_name: str
    user_id: int
    chat_id: str
    flow_id: str
    flow_type: int
    create_time: datetime
    like_count: int | None = None
    dislike_count: int | None = None
    copied_count: int | None = None
    sensitive_status: int | None = None  # Sensitive word review status
    user_groups: list[Any] | None = None  # Groups to which the user belongs
    mark_user: str | None = None
    mark_status: int | None = None
    mark_id: int | None = None
    messages: list[dict] | None = None  # All message list data for the session
    # F003: organisation snapshot (sentinels in ``database/models/org_snapshot.py``) and usage type
    operator_dept_id: int | None = None
    operator_dept_path: str | None = None
    usage_type: str | None = None  # daily | assistant | workflow | task

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
                    "message": rewrite_current_browser_object_text(obj.message),
                    "files": rewrite_current_browser_object_text(obj.files),
                }
            )
            for obj in chat_messages
        ]
