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
    Get the current UTC time and the time in the major time zones, which can be used for calculations related to time, date, and other scenarios.
    """
    tz = pytz.timezone(timezone)
    current_time = datetime.now(tz)
    formatted_time = current_time.strftime("%A, %B %d, %Y %I:%M %p")
    return formatted_time
