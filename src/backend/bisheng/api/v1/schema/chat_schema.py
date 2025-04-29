import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


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
    sensitive_status: Optional[int] = None  # 敏感词审查状态
    user_groups: Optional[List[Any]] = None # 用户所属的分组
    mark_user: Optional[str] = None
    mark_status: Optional[int] = None
    mark_id: Optional[int] = None
    messages: Optional[List[dict]] = None # 会话的所有消息列表数据

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
    knowledge_enabled: Optional[bool] = False
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
