from ast import List
from typing import Optional

from pydantic import BaseModel


class CreateDatasetParam(BaseModel):
    name: str
    description: str
    file_url: Optional[str]
    qa_list: Optional[List[str]]
