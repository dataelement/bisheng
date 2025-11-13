from typing import Literal, Optional

from pydantic import BaseModel


# 自定义扩展字段schema
class RagMetadataFieldSchema(BaseModel):
    field_name: str
    field_type: Literal['text', 'boolean', 'int8', 'int16', 'int32', 'int64', 'float', 'double', 'json']
    kwargs: Optional[dict] = None
