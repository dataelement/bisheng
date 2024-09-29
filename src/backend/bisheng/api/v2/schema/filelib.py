from typing import Dict, List, Optional

from pydantic import BaseModel


class APIAddQAParam(BaseModel):
    question: str
    answer: List[str]
    extra: Optional[Dict] = {}


class APIAppendQAParam(BaseModel):
    relative_questions: List[str] = []
    id: str = None


class QueryQAParam(BaseModel):
    timeRange: List[str]
