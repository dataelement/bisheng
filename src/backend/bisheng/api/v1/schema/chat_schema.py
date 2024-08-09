from datetime import datetime
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
