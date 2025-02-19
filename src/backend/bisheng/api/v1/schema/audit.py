from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field

class DayCron(Enum):
    Day: str = 'Day'  # 每天
    Mon: str = 'Mon'  # 每周一
    Tue: str = 'Tue'  # 每周二
    Wed: str = 'Wed'  # 每周三
    Thur: str = 'Thur'  # 每周四
    Fri: str = 'Fri'  # 每周五
    Sat: str = 'Sat'  # 每周六
    Sun: str = 'Sun'  # 每周日

class ReviewSessionConfig(BaseModel):
    flag: Optional[bool] = Field(default=False, description='是否开启违规审查策略')
    prompt: Optional[str] = Field(default='', description='违规审查的prompt')
    day_cron: Optional[str] = Field(default='', description='每天还是每周')
    hour_cron: Optional[str] = Field(default='', description='几点执行')

