from typing import Literal, Optional

from pydantic import BaseModel


# Custom Extended Fields schema
class RagMetadataFieldSchema(BaseModel):
    field_name: str
    # 'array_int64' renders as Milvus DataType.ARRAY with element_type INT64;
    # kwargs must carry element_type ('int64') and max_capacity (1-4096).
    field_type: Literal['text', 'boolean', 'int8', 'int16', 'int32', 'int64', 'float', 'double', 'json', 'array_int64']
    kwargs: Optional[dict] = None
