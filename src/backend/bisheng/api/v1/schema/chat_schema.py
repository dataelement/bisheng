from datetime import datetime
from typing import List, Optional, Any

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
    user_groups: Optional[List[Any]] # 用户所属的分组
    mark_user: Optional[str]
    mark_status: Optional[int]
    mark_id: Optional[int]
    messages: Optional[List[dict]] # 会话的所有消息列表数据


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]
    relative_questions: Optional[List[str]] = []


class APIChatCompletion(BaseModel):
    model: str
    messages: Optional[List[dict]] = []
    session_id: Optional[str] = None
    streaming: Optional[bool] = True
    file: Optional[str] = None
    tweaks: Optional[dict] = {}
