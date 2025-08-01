from typing import List, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from bisheng.database.models.linsight_sop import LinsightSOPRecord


class ToolChildrenSchema(BaseModel):
    id: int = Field(..., description="工具id")
    name: Optional[str] = Field(None, description="工具名称")
    tool_key: Optional[str] = Field(None, description="工具key")
    desc: Optional[str] = Field(None, description="工具描述")


# 选择的toolSchema
class LinsightToolSchema(BaseModel):
    id: int = Field(..., description="工具一级ID")
    name: Optional[str] = Field(None, description="工具名称")
    is_preset: int = Field(1, description="是否为预设工具")
    desc: Optional[str] = Field(None, description="工具描述")
    # child工具列表
    children: Optional[List[ToolChildrenSchema]] = Field(..., description="子工具列表")


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


class BatchDownloadFilesSchema(BaseModel):
    file_name: str = Field(..., description="文件名称")
    file_url: str = Field(..., description="文件下载链接")


class SopRecordRead(LinsightSOPRecord, table=False):
    user_name: Optional[str] = Field(default=None, description="用户名称")
