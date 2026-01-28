from typing import Optional

from pydantic import Field, BaseModel, field_validator


# SOPManaging Schema
class SOPManagementSchema(BaseModel):
    """SOPManaging Schema"""
    name: str = Field(..., description="SOPPart Name")
    description: str = Field(None, description="SOPDescription")
    content: str = Field(..., description="SOPContents")
    rating: int = Field(0, ge=0, le=5, description="SOPScore, Range0-5")
    linsight_version_id: Optional[str] = Field(default=None, description="LinsightSession Version ofID")

    @field_validator("name", mode="before")
    def validate_name(cls, v):
        # LimitSOPName length does not exceed500characters
        return v[:500]


class SOPManagementUpdateSchema(SOPManagementSchema):
    """SOPManage updates Schema"""
    id: int = Field(..., description="SOPUniqueness quantificationID")
    user_id: Optional[int] = Field(None, description="UsersID")
    showcase: Optional[bool] = Field(None, description="Whether to display")
