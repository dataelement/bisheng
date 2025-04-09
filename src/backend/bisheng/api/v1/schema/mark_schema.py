from typing import List, Optional

from pydantic import BaseModel, Field


class MarkTaskCreate(BaseModel):
    app_list: List[str] = Field(max_items=30)
    user_list: List[str]

class MarkData(BaseModel):
    session_id: str
    task_id: int
    status: int
    flow_type:Optional[int]

