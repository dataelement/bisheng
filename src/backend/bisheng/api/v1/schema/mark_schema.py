
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class MarkTaskCreate(BaseModel):
    app_list: List[str]
    user_list: List[str]
