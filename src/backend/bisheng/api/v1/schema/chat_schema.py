import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AppChatList(BaseModel):
    flow_name: str
    user_name: str
    user_id: int
    chat_id: str
    flow_id: str
    flow_type: int
    create_time: datetime
    like_count: Optional[int]
    dislike_count: Optional[int]
    copied_count: Optional[int]
    sensitive_status: Optional[int]  # 敏感词审查状态
    user_groups: Optional[List[Any]]  # 用户所属的分组
    mark_user: Optional[str]
    mark_status: Optional[int]
    mark_id: Optional[int]
    messages: Optional[List[dict]]  # 会话的所有消息列表数据


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
