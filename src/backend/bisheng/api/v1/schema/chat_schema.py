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
    like_count: Optional[int] = None
    dislike_count: Optional[int] = None
    copied_count: Optional[int] = None
    sensitive_status: Optional[int] = None  # 敏感词审查状态
    user_groups: Optional[List[Any]] = None # 用户所属的分组
    mark_user: Optional[str] = None
    mark_status: Optional[int] = None
    mark_id: Optional[int] = None
    messages: Optional[List[dict]] = None # 会话的所有消息列表数据


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
