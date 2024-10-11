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


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]
    relative_questions: Optional[List[str]] = []
