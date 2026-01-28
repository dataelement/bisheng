from typing import Optional, Dict

from pydantic import BaseModel, Field

from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareMode


class GenerateShareLinkRequest(BaseModel):
    """Generate shared link request model"""
    resource_type: ResourceTypeEnum = Field(..., description="Resource Type")
    resource_id: str = Field(..., description="reasourseID")
    share_mode: ShareMode = Field(default=ShareMode.READ_ONLY, description="sharing mode")
    expire_time: int = Field(default=0, description="Expiration time, in seconds,0Indicates never expires")
    meta_data: Optional[Dict] = Field(None, description="Metadata to store additional information")
