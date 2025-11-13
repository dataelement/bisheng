from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, Field

from bisheng.knowledge.domain.models.knowledge import MetadataFieldType


class UpdatePreviewFileChunk(BaseModel):
    knowledge_id: int = Field(..., description='知识库ID')
    file_path: str = Field(..., description='文件路径')
    text: str = Field(..., description='文本块内容')
    chunk_index: int = Field(..., description='文本块索引, 在metadata里')
    bbox: Optional[str] = Field(default='', description='文本块bbox信息')


class MetadataField(BaseModel):
    """元数据字段模型"""
    field_name: str = Field(..., description='元数据字段名')
    field_type: MetadataFieldType = Field(..., description='元数据字段类型')
    updated_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()),
                            description='元数据字段更新时间戳')


class AddKnowledgeMetadataFieldsReq(BaseModel):
    """添加知识库元数据字段请求体"""
    knowledge_id: int = Field(..., description='知识库ID')
    metadata_fields: List[MetadataField] = Field(..., description='要添加的元数据字段列表')


class UpdateKnowledgeMetadataFieldsReq(BaseModel):
    """更新知识库元数据字段请求体"""

    class UpdateMetadataFieldName(BaseModel):
        """更新元数据字段名称模型"""
        old_field_name: str = Field(..., description='旧的元数据字段名')
        new_field_name: str = Field(..., description='新的元数据字段名')

    knowledge_id: int = Field(..., description='知识库ID')
    metadata_fields: List[UpdateMetadataFieldName] = Field(..., description='要更新的元数据字段列表')


class FileUserMetaDataInfo(BaseModel):
    field_name: str = Field(..., description='元数据字段名')
    field_value: Optional[Any] = Field(default=None, description='元数据字段值')


class ModifyKnowledgeFileMetaDataReq(BaseModel):
    """更改知识库文件元数据请求体"""
    knowledge_file_id: int = Field(..., description='知识库文件ID')
    user_metadata_list: List[FileUserMetaDataInfo] = Field(..., description='要添加的文件元数据列表')
