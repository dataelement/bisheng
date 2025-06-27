from typing import List, Dict

from pydantic import BaseModel, Field


# 问题提交Schema
class LinsightQuestionSubmitSchema(BaseModel):
    question: str = Field(..., description="用户提交的问题")
    knowledge_enabled: bool = Field(False, description="是否启用知识库")
    files: List[Dict] = Field(None, description="上传的文件列表")
    tools: List[Dict] = Field(None, description="可用的工具列表")


