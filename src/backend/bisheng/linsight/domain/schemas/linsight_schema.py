from pydantic import BaseModel, Field, field_validator

from bisheng.linsight.domain.models.linsight_sop import LinsightSOPRecord
from bisheng_langchain.linsight.event import NeedUserInput


class ToolChildrenSchema(BaseModel):
    id: int = Field(..., description="Toolsid")
    name: str | None = Field(None, description="Tool name")
    tool_key: str | None = Field(None, description="Toolskey")
    desc: str | None = Field(None, description="Tools Description")


# Opt-IntoolSchema
class LinsightToolSchema(BaseModel):
    id: int = Field(..., description="Tool LevelID")
    name: str | None = Field(None, description="Tool name")
    is_preset: int = Field(1, description="Whether or not it is a preset tool")
    desc: str | None = Field(None, description="Tools Description")
    # childTools List
    children: list[ToolChildrenSchema] | None = Field(..., description="Subtools List")


class SubmitFileSchema(BaseModel):
    file_id: str = Field(..., description="File UniqueID")
    file_name: str = Field(..., description="File Name")
    parsing_status: str = Field(..., description="File parsing status")
    # F035 unified-resource: when set, the file came from the DAILY upload bucket
    # (workstation), not the linsight pipeline. Carries the raw MinIO path;
    # linsight parses it on-the-fly via TempFilePipeline at ingestion instead of
    # resolving a linsight Redis temp_info / pre-parsed markdown.
    file_url: str | None = Field(None, description="Daily-bucket raw file path (workstation upload)")


# Submit a problemSchema
class LinsightQuestionSubmitSchema(BaseModel):
    question: str = Field(..., description="User Submitted Questions")
    org_knowledge_enabled: bool = Field(False, description="Whether to enable organization knowledge base")
    personal_knowledge_enabled: bool = Field(False, description="Whether or not to enable Personal Knowledge Base")
    # Exact KB selection carried from the daily picker. These are the SPECIFIC ids
    # the user chose, so the task agent searches exactly those — not every KB of a
    # coarse type. organization = NORMAL-type KB ids; knowledge_space = SPACE-type
    # ids. The coarse booleans above are kept for storage/back-compat but no longer
    # drive knowledge injection.
    organization_knowledge_ids: list[int] | None = Field(None, description="Selected organization knowledge base ids")
    knowledge_space_ids: list[int] | None = Field(None, description="Selected knowledge space ids")
    files: list[SubmitFileSchema] | None = Field(None, description="Uploaded files list:")
    tools: list[LinsightToolSchema] | None = Field(None, description="List of available tools")
    # F035: per-task selected execution model id; None falls back to the tenant
    # ``linsight_default_model_id`` at resolve time (agent_factory._resolve_model).
    model: str | None = Field(None, description="Per-task selected execution model id")
    # F035: continue an existing session (a follow-up round in the same 会话).
    # None creates a brand-new session.
    session_id: str | None = Field(None, description="Existing session id to continue; None creates a new session")

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: list[LinsightToolSchema]) -> list[dict]:
        if not v:
            return []
        # Convert tool to dictionary format
        return [tool.model_dump() for tool in v]


class DownloadFilesSchema(BaseModel):
    file_name: str = Field(..., description="File Name")
    file_url: str = Field(..., description="File download link")


class SopRecordRead(LinsightSOPRecord, table=False):
    user_name: str | None = Field(default=None, description="Client Name")


class UserInputEventSchema(NeedUserInput):
    files: list[dict[str, str]] | None = Field(None, description="Uploaded files list:")
    user_input: str | None = Field(None, description="User input")
    is_completed: bool = Field(False, description="Is it completed")
