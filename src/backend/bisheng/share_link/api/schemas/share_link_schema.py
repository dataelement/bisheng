from typing import Optional, Dict

from pydantic import BaseModel, Field

from bisheng.share_link.domain.models.share_link import ResourceTypeEnum, ShareMode


class GenerateShareLinkRequest(BaseModel):
    """生成共享链接请求模型"""
    resource_type: ResourceTypeEnum = Field(..., description="资源类型")
    resource_id: str = Field(..., description="资源ID")
    share_mode: ShareMode = Field(default=ShareMode.READ_ONLY, description="共享模式")
    expire_time: int = Field(default=0, description="过期时间，单位秒，0表示永不过期")
    meta_data: Optional[Dict] = Field(None, description="元数据，存储额外信息")
