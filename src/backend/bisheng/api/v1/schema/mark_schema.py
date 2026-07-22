from pydantic import BaseModel, Field


class MarkTaskCreate(BaseModel):
    app_list: list[str] = Field(max_length=30)
    user_list: list[int]


class MarkData(BaseModel):
    session_id: str
    task_id: int
    status: int
    flow_type: int | None = None
