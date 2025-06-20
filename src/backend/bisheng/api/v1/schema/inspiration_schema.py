from pydantic import Field, BaseModel


# SOP管理 Schema
class SOPManagementSchema(BaseModel):
    """SOP管理 Schema"""
    name: str = Field(..., description="SOP名称")
    description: str = Field(None, description="SOP描述")
    content: str = Field(..., description="SOP内容")
    rating: int = Field(0, ge=0, le=5, description="SOP评分，范围0-5")



