from typing import List

from pydantic import BaseModel


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]


class APIAppendQAParam(BaseModel):
    relative_questions: List[str] = []
    id: str = None
