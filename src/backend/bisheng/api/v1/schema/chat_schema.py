from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class AppChatList(BaseModel):
    flow_name: str
    user_name: str
    user_id: int
    chat_id: str
    flow_id: UUID
    create_time: datetime
    like_count: int
    dislike_count: int
    copied_count: int
    flow_type: str  # flow、assistant、workflow
    mark_user: Optional[str]
    mark_status: Optional[int]
    mark_id: Optional[int]


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
