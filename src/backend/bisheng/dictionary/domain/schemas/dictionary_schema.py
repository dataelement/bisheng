"""Dictionary domain schemas - 字典模块请求/响应 DTO"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DictionaryTypeEnum(str, Enum):
    """字典类型枚举"""

    EXPERT_MAJOR = "岗位"
    EXPERT_POSITION = "职务"
    EXPERT_JOB_FAMILY = "职位族"
    EXPERT_JOB_CATEGORY = "职位类"


# 数据库类型 code -> 展示中文(与 DictionaryTypeEnum 展示值保持一致)
DICTIONARY_TYPE_CODE_TO_LABEL: dict[str, str] = {
    "expert_position": "岗位",
    "expert_title": "职务",
    "expert_job_family": "职位族",
    "expert_job_category": "职位类",
}
DICTIONARY_TYPE_LABEL_TO_CODE: dict[str, str] = {label: code for code, label in DICTIONARY_TYPE_CODE_TO_LABEL.items()}

# Excel 导入导出使用的列标题
DICTIONARY_EXPORT_HEADERS: list[str] = [
    "类型",
    "字典键",
    "字典取值",
    "排序权重",
    "是否启用",
]


class DictionaryCreateRequest(BaseModel):
    """创建字典条目请求"""

    type: str = Field(..., max_length=64, description="字典类型")
    dict_key: str = Field(..., max_length=255, description="字典键")
    dict_value: str = Field(..., max_length=255, description="字典取值")
    sort_order: int = Field(default=0, ge=0, description="排序权重")
    is_enabled: bool = Field(default=True, description="是否启用")


class DictionaryUpdateRequest(BaseModel):
    """更新字典条目请求"""
    dict_key: str = Field(..., max_length=255, description="字典键")
    dict_value: str | None = Field(None, max_length=255, description="字典取值")
    sort_order: int | None = Field(None, ge=0, description="排序权重")
    is_enabled: bool | None = Field(None, description="是否启用")


class DictionaryResponse(BaseModel):
    """字典条目响应"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="字典条目 ID")
    type: str = Field(..., description="字典类型")
    dict_key: str = Field(..., description="字典键")
    dict_value: str = Field(..., description="字典取值")
    sort_order: int = Field(..., description="排序权重")
    is_enabled: bool = Field(..., description="是否启用")
    tenant_id: int = Field(..., description="租户 ID")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime | None = Field(None, description="更新时间")


class DictionaryTypeResponse(BaseModel):
    """字典类型响应"""

    type: str = Field(..., description="字典类型值")
    name: str = Field(..., description="字典类型名称")


class DictionaryImportResult(BaseModel):
    """字典导入结果"""

    total: int = Field(..., description="解析到的总行数")
    success: int = Field(..., description="成功导入条数")
    failed: int = Field(..., description="失败条数")
    errors: list[str] = Field(default_factory=list, description="失败原因列表")
