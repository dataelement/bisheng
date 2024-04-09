from datetime import datetime

import pytz
from langchain.pydantic_v1 import BaseModel, Field
from langchain.tools import tool


class GetCurTimeInput(BaseModel):
    timezone: str = Field(
        default='Asia/Shanghai',
        description="The timezone to get the current time in. Such as 'Asia/Shanghai','Pacific/Palau' or 'US/Mountain'.",
    )


@tool(args_schema=GetCurTimeInput)
def get_current_time(timezone='Asia/Shanghai'):
    """
    获取当前UTC时间以及主要时区的时间，可用于时间、日期等场景相关的计算。当问题涉及到时间，调用此工具来查询和时间有关的内容。
    """
    tz = pytz.timezone(timezone)
    current_time = datetime.now(tz)
    formatted_time = current_time.strftime("%A, %B %d, %Y %I:%M %p")
    return formatted_time
