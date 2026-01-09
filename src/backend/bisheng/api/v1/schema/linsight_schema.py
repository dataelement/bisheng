from typing import List, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from bisheng.database.models.linsight_sop import LinsightSOPRecord
from bisheng_langchain.linsight.event import NeedUserInput


class ToolChildrenSchema(BaseModel):
    id: int = Field(..., description="Toolsid")
    name: Optional[str] = Field(None, description="Tool name")
    tool_key: Optional[str] = Field(None, description="Toolskey")
    desc: Optional[str] = Field(None, description="Tools Description")


# Opt-IntoolSchema
class LinsightToolSchema(BaseModel):
    id: int = Field(..., description="Tool LevelID")
    name: Optional[str] = Field(None, description="Tool name")
    is_preset: int = Field(1, description="Whether or not it is a preset tool")
    desc: Optional[str] = Field(None, description="Tools Description")
    # childTools List
    children: Optional[List[ToolChildrenSchema]] = Field(..., description="Subtools List")


class SubmitFileSchema(BaseModel):
    file_id: str = Field(..., description="File UniqueID")
    file_name: str = Field(..., description="File Name")
    parsing_status: str = Field(..., description="File parsing status")


# Submit a problemSchema
class LinsightQuestionSubmitSchema(BaseModel):
    question: str = Field(..., description="User Submitted Questions")
    org_knowledge_enabled: bool = Field(False, description="Whether to enable organization knowledge base")
    personal_knowledge_enabled: bool = Field(False, description="Whether or not to enable Personal Knowledge Base")
    files: Optional[List[SubmitFileSchema]] = Field(None, description="Uploaded files list:")
    tools: Optional[List[LinsightToolSchema]] = Field(None, description="List of available tools")

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: List[LinsightToolSchema]) -> List[Dict]:
        if not v:
            return []
        # Convert tool to dictionary format
        return [tool.model_dump() for tool in v]


class DownloadFilesSchema(BaseModel):
    file_name: str = Field(..., description="File Name")
    file_url: str = Field(..., description="File download link")


class SopRecordRead(LinsightSOPRecord, table=False):
    user_name: Optional[str] = Field(default=None, description="Client Name")


class UserInputEventSchema(NeedUserInput):
    files: Optional[List[Dict[str, str]]] = Field(None, description="Uploaded files list:")
    user_input: Optional[str] = Field(None, description="User input")
    is_completed: bool = Field(False, description="Is it completed")
