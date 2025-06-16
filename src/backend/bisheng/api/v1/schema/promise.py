from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BusinessUserPromise(BaseModel):
    business_id: str = Field(default=None, description='业务唯一标识')
    promise_id: str = Field(default=None, description='承诺书唯一标识')
    user_id: str = Field(default=None, description='用户ID')
    user_name: str = Field(default=None, description='用户名称')
    write: bool = Field(default=False, description='是否已签署承诺书')
    create_time: Optional[datetime] = Field(default=None, description='签署时间')