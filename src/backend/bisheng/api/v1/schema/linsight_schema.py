from typing import List, Dict

from pydantic import BaseModel, Field, field_validator

from bisheng.database.constants import ToolPresetType


class ToolChildrenSchema(BaseModel):
    id: int = Field(..., description="工具id")
    name: str = Field(..., description="工具名称")
    tool_key: str = Field(..., description="工具key")


# 选择的toolSchema
class LinsightToolSchema(BaseModel):
    id: int = Field(..., description="工具一级ID")
    name: str = Field(..., description="工具一级名称")
    description: str = Field(..., description="工具一级描述")
    is_preset: ToolPresetType = Field(..., description="工具类型")
    # child工具列表
    children: List[ToolChildrenSchema] = Field(..., description="子工具列表")

    @field_validator("is_preset")
    @classmethod
    def validate_is_preset(cls, v: ToolPresetType) -> int:
        return v.value


class SubmitFileSchema(BaseModel):
    file_id: str = Field(..., description="文件唯一ID")
    file_name: str = Field(..., description="文件名称")
    parsing_status: str = Field(..., description="文件解析状态")


# 问题提交Schema
class LinsightQuestionSubmitSchema(BaseModel):
    question: str = Field(..., description="用户提交的问题")
    org_knowledge_enabled: bool = Field(False, description="是否启用组织知识库")
    personal_knowledge_enabled: bool = Field(False, description="是否启用个人知识库")
    files: List[SubmitFileSchema] = Field(None, description="上传的文件列表")
    tools: List[LinsightToolSchema] = Field(None, description="可用的工具列表")

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: List[LinsightToolSchema]) -> List[Dict]:
        if not v:
            return []
        # 将工具转换为字典格式
        return [tool.model_dump() for tool in v]
