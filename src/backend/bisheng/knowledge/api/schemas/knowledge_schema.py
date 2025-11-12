from typing import Optional, List

from pydantic import BaseModel, Field

from bisheng.knowledge.domain.models.knowledge import MetadataField


class UpdatePreviewFileChunk(BaseModel):
    knowledge_id: int = Field(..., description='知识库ID')
    file_path: str = Field(..., description='文件路径')
    text: str = Field(..., description='文本块内容')
    chunk_index: int = Field(..., description='文本块索引, 在metadata里')
    bbox: Optional[str] = Field(default='', description='文本块bbox信息')


class AddKnowledgeMetadataFieldsReq(BaseModel):
    """添加知识库元数据字段请求体"""
    knowledge_id: int = Field(..., description='知识库ID')
    metadata_fields: List[MetadataField] = Field(..., description='要添加的元数据字段列表')
