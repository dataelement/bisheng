"""Stable request contracts for API-key workflow execution."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OpenWorkflowInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID = Field(description="Workflow UniqueID")
    override: dict | None = Field(default=None, description="Override node parameters")
    stream: bool | None = Field(default=True, description="Whether to stream calls")
    input: dict | None = Field(default=None, description="User input")
    message_id: int | None = Field(default=None, description="Unique user-input message ID")
    session_id: str | None = Field(default=None, description="Workflow call session ID")
