from typing import Optional

from pydantic import Field, BaseModel, field_validator


# SOP管理 Schema
class SOPManagementSchema(BaseModel):
    """SOP管理 Schema"""
    name: str = Field(..., description="SOP名称")
    description: str = Field(None, description="SOP描述")
    content: str = Field(..., description="SOP内容")
    rating: int = Field(0, ge=0, le=5, description="SOP评分，范围0-5")
    linsight_session_id: Optional[str] = Field(default=None, description="Linsight会话ID")

    @field_validator("name", mode="before")
    def validate_name(cls, v):
        # 限制SOP名称长度不超过500个字符
        return v[:500]


class SOPManagementUpdateSchema(SOPManagementSchema):
    """SOP管理更新 Schema"""
    id: int = Field(..., description="SOP唯一ID")
