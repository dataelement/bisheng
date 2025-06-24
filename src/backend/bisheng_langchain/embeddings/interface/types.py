from typing import Any, Dict, List, Union

from pydantic import BaseModel


class EmbeddingInput(BaseModel):
    model: str
    input: Union[str, List[str]]


class Embedding(BaseModel):
    object: str = 'embedding'
    embedding: List[float]
    index: int


class EmbeddingOutput(BaseModel):
    status_code: int
    status_message: str = 'success'
    object: str = None
    data: List[Embedding] = []
    model: str = None
    usage: Dict[str, Any] = None
