"""Dictionary domain schemas - 字典模块请求/响应 DTO"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DictionaryTypeEnum(str, Enum):
    """字典类型枚举"""

    EXPERT_POSITION = "expert_position"
    EXPERT_TITLE = "expert_title"
    EXPERT_JOB_FAMILY = "expert_job_family"
    EXPERT_JOB_CATEGORY = "expert_job_category"


class DictionaryCreateRequest(BaseModel):
    """创建字典条目请求"""

    type: str = Field(..., max_length=64, description="字典类型")
    value: str = Field(..., max_length=255, description="字典取值")
    sort_order: int = Field(default=0, ge=0, description="排序权重")
    is_enabled: bool = Field(default=True, description="是否启用")


class DictionaryUpdateRequest(BaseModel):
    """更新字典条目请求"""

    value: str | None = Field(None, max_length=255, description="字典取值")
    sort_order: int | None = Field(None, ge=0, description="排序权重")
    is_enabled: bool | None = Field(None, description="是否启用")


class DictionaryResponse(BaseModel):
    """字典条目响应"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="字典条目 ID")
    type: str = Field(..., description="字典类型")
    value: str = Field(..., description="字典取值")
    sort_order: int = Field(..., description="排序权重")
    is_enabled: bool = Field(..., description="是否启用")
    tenant_id: int = Field(..., description="租户 ID")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime | None = Field(None, description="更新时间")
