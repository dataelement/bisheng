from typing import List, Optional, Any

from pydantic import BaseModel, Field, field_validator


class MarkTaskCreate(BaseModel):
    app_list: List[str] = Field(max_length=30)
    user_list: List[str]

    @field_validator('user_list', mode='before')
    @classmethod
    def convert_user_list(cls, v: Any):
        ret = []
        for one in v:
            if isinstance(one, str):
                ret.append(one)
            else:
                ret.append(str(one))
        return ret


class MarkData(BaseModel):
    session_id: str
    task_id: int
    status: int
    flow_type: Optional[int] = None
